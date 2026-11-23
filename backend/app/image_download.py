"""短期原图下载链接：不代理文件，不依赖浏览器跨域读取权限。"""

from __future__ import annotations

import asyncio
import re
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from tos.enum import HttpMethodType

from .auth import CurrentUser
from .config import settings
from .database import database_session
from .models import DigitalHumanModel
from .oss_storage import OssStorage, internal_read_url, is_oss_host
from .rbac import is_super_admin
from .storage import TosStorage, is_tos_url, is_user_owned_tos_url

router = APIRouter(prefix="/api/media")


async def sign_download_url(src: str, name: str) -> str:
    parsed = urlparse(src)
    extension = re.search(r"\.(png|jpe?g|webp|gif|avif)$", parsed.path, re.I)
    suffix = extension.group(1).lower() if extension else "png"
    filename = re.sub(r'[\\/:*?"<>|\r\n]', "_", name)[:120] + "." + suffix
    disposition = f"attachment; filename=\"image.{suffix}\"; filename*=UTF-8''{quote(filename, safe='')}"
    if is_oss_host(src):
        if not internal_read_url(src):
            raise HTTPException(422, "不属于当前环境的素材目录")
        return OssStorage().public_bucket.sign_url("GET", unquote(parsed.path.lstrip("/")), 300, params={"response-content-disposition": disposition}, slash_safe=True)
    buckets = [settings.tos_reference_bucket, settings.tos_video_bucket]
    bucket = next((item for item in buckets if item and (parsed.hostname or "").startswith(item + ".")), "")
    if not bucket and settings.tos_public_domain == parsed.hostname:
        bucket = settings.tos_reference_bucket or settings.tos_video_bucket
        if settings.tos_video_prefix and parsed.path.startswith("/" + settings.tos_video_prefix.strip("/") + "/"):
            bucket = settings.tos_video_bucket or bucket
    if not bucket:
        raise HTTPException(422, "无法识别图片存储桶")
    storage = TosStorage()
    signed = await asyncio.to_thread(
        storage.client.pre_signed_url,
        HttpMethodType.Http_Method_Get,
        bucket,
        unquote(parsed.path.lstrip("/")),
        expires=300,
        query={"response-content-disposition": disposition},
    )
    return signed.signed_url


@router.get("/image-download")
async def image_download(
    user: CurrentUser, src: str = Query(max_length=4096), name: str = Query(default="原图", max_length=160), db: AsyncSession = Depends(database_session)
) -> dict:
    try:
        parsed = urlparse(src)
        valid = (
            parsed.scheme == "https"
            and (is_tos_url(src) or is_oss_host(src))
            and not parsed.query
            and not parsed.fragment
            and not parsed.username
            and not parsed.password
            and parsed.port in (None, 443)
        )
    except ValueError:
        valid = False
    if not valid:
        raise HTTPException(422, "仅支持平台存储的图片")
    if not is_user_owned_tos_url(src, user.id) and not is_super_admin(user):
        human = await db.scalar(
            select(DigitalHumanModel.id).where(
                DigitalHumanModel.deleted_at.is_(None),
                DigitalHumanModel.scope == "system",
                or_(DigitalHumanModel.avatar_url == src, DigitalHumanModel.avatar_thumbnail_url == src),
            )
        )
        if not human:
            raise HTTPException(403, "无权下载该图片")
    return {"url": await sign_download_url(src, name), "expiresIn": 300}
