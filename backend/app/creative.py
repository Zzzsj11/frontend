from __future__ import annotations

import asyncio
import mimetypes
import time
import uuid
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .agent_attribution import current_agent_attribution
from .auth import CurrentUser
from .database import database_session, session_factory
from .jobs import Job, jobs
from .models import PromptOptimizationTaskModel
from .prompt_optimizer import MEDIA_LIMITS, PROVIDERS, RATIOS, call_gemini, create_minimax, provider_status, query_minimax
from .storage import get_storage, is_user_owned_tos_url, put_image_with_thumbnail, safe_key
from .token_usage import add_llm_call_log, add_token_usage
from .usage_quota import consume_daily_quota

router = APIRouter(prefix="/api/creative", tags=["creative"])
Db = Depends(database_session)


class CreativeMediaIn(BaseModel):
    kind: str = Field(pattern="^(image|video|audio)$")
    url: str = Field(min_length=1, max_length=2000)
    thumbnail_url: str | None = Field(default=None, alias="thumbnailUrl")
    name: str = Field(default="", max_length=255)
    mime_type: str = Field(default="", max_length=120, alias="mimeType")
    role: str = Field(default="reference", max_length=120)

    model_config = {"populate_by_name": True}


class CreativeOptimizeIn(BaseModel):
    provider: str
    prompt: str = Field(min_length=1, max_length=7000)
    duration: int = Field(default=8, ge=4, le=15)
    ratio: str = "16:9"
    media: list[CreativeMediaIn] = Field(default_factory=list, max_length=15)


def task_json(item: PromptOptimizationTaskModel) -> dict[str, Any]:
    return {
        "id": item.id,
        "provider": item.provider,
        "model": item.model,
        "status": item.status,
        "inputPrompt": item.input_prompt,
        "outputPrompt": item.output_prompt,
        "duration": item.duration,
        "ratio": item.ratio,
        "media": item.input_media,
        "providerTaskId": item.provider_task_id,
        "usage": item.usage_data,
        "error": item.error,
        "createdAt": item.created_at.isoformat(),
    }


@router.get("/status")
async def creative_status(user: CurrentUser):
    return {
        "providers": provider_status(),
        "limits": {"images": 9, "videos": 3, "audios": 3, "videoSeconds": 15, "audioSeconds": 15},
        "ratios": list(RATIOS),
        "durationRange": [4, 15],
    }


@router.post("/upload")
async def creative_upload(file: UploadFile, user: CurrentUser):
    content = await file.read(50 * 1024 * 1024 + 1)
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(413, "素材不能超过 50MB")
    mime_type = (file.content_type or mimetypes.guess_type(file.filename or "")[0] or "application/octet-stream").lower()
    kind = "image" if mime_type.startswith("image/") else "video" if mime_type.startswith("video/") else "audio" if mime_type.startswith("audio/") else ""
    if not kind:
        raise HTTPException(422, "仅支持图片、视频或音频素材")
    suffix = Path(file.filename or "").suffix.lower()
    allowed = {
        "image": {".jpg", ".jpeg", ".png", ".webp"},
        "video": {".mp4", ".mov"},
        "audio": {".wav", ".mp3", ".m4a"},
    }
    if suffix not in allowed[kind]:
        raise HTTPException(422, "文件扩展名与支持的媒体类型不匹配")
    if kind == "image":
        try:
            with Image.open(BytesIO(content)) as image:
                image.verify()
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(422, "图片文件无法解析") from exc
    key = safe_key(f"users/{user.id}/creative/{kind}", file.filename or f"reference-{kind}")
    if kind == "image":
        url, thumbnail_url = await put_image_with_thumbnail(key, content, mime_type)
    else:
        url = await get_storage().put_bytes(key, content, mime_type)
        thumbnail_url = None
    return {"kind": kind, "url": url, "thumbnailUrl": thumbnail_url, "name": file.filename or "", "mimeType": mime_type, "size": len(content), "role": "reference"}


@router.post("/optimizations", status_code=201)
async def create_optimization(payload: CreativeOptimizeIn, user: CurrentUser, db: AsyncSession = Db):
    if payload.provider not in PROVIDERS or payload.ratio not in RATIOS:
        raise HTTPException(422, "不支持的提示词优化参数")
    status = provider_status()[payload.provider]
    if not status["configured"]:
        raise HTTPException(503, f"{payload.provider} 提示词优化密钥未配置")
    media = [item.model_dump(by_alias=True) for item in payload.media]
    counts = {kind: sum(item["kind"] == kind for item in media) for kind in MEDIA_LIMITS}
    if any(counts[kind] > limit for kind, limit in MEDIA_LIMITS.items()):
        raise HTTPException(422, "参考素材数量超过限制")
    if payload.provider == "minimax" and not media:
        raise HTTPException(422, "MiniMax 优化至少需要一个参考素材")
    if any(not is_user_owned_tos_url(item["url"], user.id) for item in media):
        raise HTTPException(422, "参考素材必须先通过当前账号上传到 TOS")
    await consume_daily_quota(db, user_id=user.id, category="chat")
    origin, agent_name, agent_run_id = current_agent_attribution()
    item = PromptOptimizationTaskModel(
        id=f"prompt-opt-{uuid.uuid4().hex}",
        user_id=user.id,
        provider=payload.provider,
        model=status["model"],
        status="running",
        input_prompt=payload.prompt,
        duration=payload.duration,
        ratio=payload.ratio,
        input_media=media,
        generation_origin=origin,
        agent_name=agent_name,
        agent_run_id=agent_run_id,
    )
    db.add(item)
    job = await jobs.enqueue(
        db,
        "prompt_optimization",
        {"optimization_task_id": item.id, "_provider": payload.provider, "_operation": "creative_prompt_optimization", "_agentName": agent_name, "_agentRunId": agent_run_id},
        user_id=user.id,
    )
    await db.commit()
    await jobs.dispatch(job, run_prompt_optimization_job)
    return task_json(item)


@router.get("/optimizations/{task_id}")
async def get_optimization(task_id: str, user: CurrentUser, db: AsyncSession = Db):
    item = (
        await db.execute(
            select(PromptOptimizationTaskModel).where(
                PromptOptimizationTaskModel.id == task_id, PromptOptimizationTaskModel.user_id == user.id, PromptOptimizationTaskModel.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if not item:
        raise HTTPException(404, "提示词优化任务不存在")
    return task_json(item)


async def run_prompt_optimization_job(job: Job) -> dict[str, Any]:
    task_id = str((job.request or {}).get("optimization_task_id") or "")
    agent_name = str((job.request or {}).get("_agentName") or "")
    agent_run_id = str((job.request or {}).get("_agentRunId") or "")
    operation = str((job.request or {}).get("_operation") or "creative_prompt_optimization")
    async with session_factory() as session:
        item = await session.get(PromptOptimizationTaskModel, task_id)
        if not item or item.deleted_at is not None:
            raise RuntimeError("提示词优化任务不存在")
        provider, prompt, duration, ratio = item.provider, item.input_prompt, item.duration, item.ratio
        media, model, user_id = list(item.input_media or []), item.model, item.user_id
    started = time.perf_counter()
    try:
        if provider == "gemini":
            result = await call_gemini(prompt=prompt, duration=duration, ratio=ratio, media=media, agent_name=agent_name, agent_run_id=agent_run_id)
        else:
            created = await create_minimax(prompt=prompt, duration=duration, ratio=ratio, media=media, agent_name=agent_name, agent_run_id=agent_run_id)
            async with session_factory() as session:
                current = await session.get(PromptOptimizationTaskModel, task_id)
                if current:
                    current.provider_task_id, current.request_id = created["taskId"], created.get("requestId")
                    await session.commit()
            deadline = time.monotonic() + 20 * 60
            while True:
                result = await query_minimax(created["taskId"], agent_name=agent_name, agent_run_id=agent_run_id)
                normalized = str(result.get("status") or "running").lower()
                if normalized in {"success", "succeeded", "completed", "failed", "error", "cancelled"}:
                    result["status"] = "succeeded" if normalized in {"success", "succeeded", "completed"} else "failed"
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError("MiniMax 提示词优化超过 20 分钟仍未完成")
                await asyncio.sleep(3.5)
        if result.get("status") == "failed":
            raise RuntimeError(str(result.get("error") or f"{provider} 提示词优化失败"))
        if not str(result.get("prompt") or "").strip():
            raise RuntimeError(f"{provider} 优化完成但未返回提示词")
        async with session_factory() as session:
            current = await session.get(PromptOptimizationTaskModel, task_id)
            if not current:
                raise RuntimeError("提示词优化任务不存在")
            current.status, current.output_prompt, current.error = "succeeded", result["prompt"], ""
            current.request_id = current.request_id or result.get("requestId")
            current.usage_data = {**(result.get("usage") or {}), "usageRecorded": True}
            add_token_usage(session, operation=operation, provider=provider, model=model, usage=result.get("usage"), user_id=user_id, request_id=current.request_id)
            add_llm_call_log(
                session,
                operation=operation,
                provider=provider,
                model=model,
                usage=result.get("usage"),
                user_id=user_id,
                request_id=current.request_id,
                duration_ms=round((time.perf_counter() - started) * 1000),
                response_text=current.output_prompt,
            )
            await session.commit()
        return {"optimizationTaskId": task_id, "provider": provider}
    except Exception as exc:
        async with session_factory() as session:
            current = await session.get(PromptOptimizationTaskModel, task_id)
            if current:
                current.status, current.error = "failed", str(exc)[:2000]
                add_llm_call_log(
                    session,
                    operation=operation,
                    provider=provider,
                    model=model,
                    usage={},
                    user_id=user_id,
                    status="error",
                    error=current.error,
                    duration_ms=round((time.perf_counter() - started) * 1000),
                )
                await session.commit()
        raise
