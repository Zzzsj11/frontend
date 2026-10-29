"""User-owned generation defaults and authenticated platform channel discovery."""

from contextvars import ContextVar
from typing import Literal
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import all_in_one
from .auth import CurrentUser
from .config import settings
from .database import database_session
from .models import AiModelModel, UserModel

router = APIRouter(prefix="/api")
text_selection: ContextVar[dict | None] = ContextVar("text_selection", default=None)


async def read_selection(db: AsyncSession, user_id: str, modality: str) -> dict:
    owner = await db.get(UserModel, user_id)
    return dict((owner.generation_preferences or {}).get(modality) or {}) if owner else {}


async def snapshot_text_selection(db: AsyncSession, user_id: str, kind: str) -> dict:
    selection = await read_selection(db, user_id, "text")
    if selection:
        model = await visible_model(db, selection["model"])
        if selection.get("channel"):
            catalog = await fetch_channels(model.provider_model_id, user_id)
            if not any(item.get("channel") == selection["channel"] and item.get("available") is True for item in catalog["channels"]):
                raise HTTPException(422, "所选文本渠道不可用，请重新选择")
        return selection
    model = settings.general_outline_llm_model if kind in {"ass_outline", "general_outline", "ass_segment_retry"} else settings.llm_model
    return {"model": model, "channel": None}


async def apply_media_preference(db: AsyncSession, user_id: str, modality: str, payload) -> None:
    selection = await read_selection(db, user_id, modality)
    if selection:
        payload.model = selection["model"]
        payload.channel = selection.get("channel")
    if payload.channel:
        model = await visible_model(db, payload.model)
        catalog = await fetch_channels(model.provider_model_id, user_id)
        channel = next((item for item in catalog["channels"] if item.get("channel") == payload.channel and item.get("available") is True), None)
        if channel is None:
            raise HTTPException(422, "所选渠道不可用，请重新选择")
        validate_channel_parameters(modality, payload, channel.get("capabilities") or {})


def validate_channel_parameters(modality: str, payload, capabilities: dict) -> None:
    """Reject channel-specific incompatibilities before creating a paid job."""
    from .image_model_policy import image_ratio

    resolution = str(payload.resolution).lower()
    supported = capabilities.get("resolutions") or capabilities.get("resolution")
    if isinstance(supported, list) and supported and resolution not in {str(item).lower() for item in supported}:
        raise HTTPException(422, "所选渠道不支持当前清晰度，请调整参数或主动切换渠道")
    ratio = image_ratio(payload.size) if modality == "image" else payload.ratio
    ratios = capabilities.get("aspect_ratios")
    if isinstance(ratios, list) and ratios and ratio not in ratios:
        raise HTTPException(422, "所选渠道不支持当前画幅，请调整参数或主动切换渠道")
    media = {"images": payload.images} if modality == "image" else {"images": payload.image_urls, "videos": payload.video_urls, "audios": payload.audio_urls}
    for kind, values in media.items():
        maximum = capabilities.get("max_" + kind)
        if isinstance(maximum, int) and len(values) > maximum:
            raise HTTPException(422, f"所选渠道最多支持 {maximum} 个 {kind} 参考素材，请调整参数或主动切换渠道")


class GenerationPreference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=160)
    channel: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$")


async def visible_model(db: AsyncSession, code: str) -> AiModelModel:
    model = await db.scalar(
        select(AiModelModel).where(
            AiModelModel.code == code,
            AiModelModel.deleted_at.is_(None),
            AiModelModel.status == "active",
            AiModelModel.user_visible.is_(True),
        )
    )
    if model is None:
        raise HTTPException(422, "模型不可用，请重新选择")
    return model


async def fetch_channels(model: str, user_id: str) -> dict:
    upstream = quote(all_in_one.upstream_model(model), safe="")
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                settings.all_in_one_base_url.rstrip("/") + f"/v1/models/{upstream}/channels",
                params={"available_only": "true"},
                headers=all_in_one.headers(user_id=user_id),
            )
            response.raise_for_status()
            data = response.json()
        if data.get("selection_parameter") != "channel" or not isinstance(data.get("channels"), list):
            raise ValueError("Unsupported channel contract")
        return data
    except (httpx.HTTPError, ValueError, RuntimeError) as exc:
        raise HTTPException(502, "平台渠道目录暂不可用，请稍后重试；原选择未改变") from exc


@router.get("/model-options/{model}/channels")
async def model_channels(model: str, user: CurrentUser, db: AsyncSession = Depends(database_session)):
    row = await visible_model(db, model)
    return await fetch_channels(row.provider_model_id, user.id)


@router.get("/generation-preferences")
async def get_preferences(user: CurrentUser, db: AsyncSession = Depends(database_session)):
    owner = await db.get(UserModel, user.id)
    return owner.generation_preferences or {}


@router.put("/generation-preferences/{modality}")
async def save_preference(
    modality: Literal["text", "image", "video"],
    payload: GenerationPreference,
    user: CurrentUser,
    db: AsyncSession = Depends(database_session),
):
    model = await visible_model(db, payload.model)
    if model.modality != ("chat" if modality == "text" else modality):
        raise HTTPException(422, "模型类型不匹配")
    if payload.channel is not None:
        catalog = await fetch_channels(model.provider_model_id, user.id)
        channel = next((item for item in catalog["channels"] if item.get("channel") == payload.channel and item.get("available") is True), None)
        if channel is None:
            raise HTTPException(422, "所选渠道不可用，请重新选择")
    owner = await db.scalar(select(UserModel).where(UserModel.id == user.id).with_for_update())
    owner.generation_preferences = {**(owner.generation_preferences or {}), modality: payload.model_dump()}
    await db.commit()
    return owner.generation_preferences
