from __future__ import annotations

import mimetypes
import io
import re
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import quote

import httpx

from .config import DATA_DIR, settings


class Storage(Protocol):
    async def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str: ...


def safe_key(category: str, filename: str) -> str:
    category_parts = []
    for part in category.replace("\\", "/").split("/"):
        if not part or part in {".", ".."}:
            continue
        clean_part = re.sub(r"[^A-Za-z0-9_-]", "-", part).strip("-")
        if clean_part:
            category_parts.append(clean_part)
    clean_category = "/".join(category_parts) or "misc"
    clean_name = re.sub(r"[^A-Za-z0-9._-]", "-", Path(filename).name) or uuid.uuid4().hex
    return f"{clean_category}/{uuid.uuid4().hex[:12]}-{clean_name}"


class LocalStorage:
    root = DATA_DIR / "media"

    async def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str:
        target = (self.root / key).resolve()
        target.relative_to(self.root.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return f"/media/{key}"


class TosStorage:
    def __init__(self) -> None:
        import tos

        try:
            self.client = tos.TosClientV2(
                settings.tos_access_key, settings.tos_secret_key, settings.tos_endpoint, settings.tos_region
            )
        except TypeError:
            self.client = tos.TosClientV2(settings.tos_access_key, settings.tos_secret_key, settings.tos_endpoint)

    @staticmethod
    def _bucket_for(key: str) -> tuple[str, str]:
        if key.startswith("videos/"):
            bucket = settings.tos_video_bucket or settings.tos_reference_bucket
            prefix = settings.tos_video_prefix
        else:
            bucket = settings.tos_reference_bucket or settings.tos_video_bucket
            prefix = settings.tos_reference_prefix
        return bucket, f"{prefix}/{key}" if prefix else key

    @staticmethod
    def _public_url(bucket: str, key: str) -> str:
        safe = quote(key, safe="/-_.~")
        if settings.tos_public_domain:
            return f"https://{settings.tos_public_domain}/{safe}"
        return f"https://{bucket}.{settings.tos_endpoint.strip('/')}/{safe}"

    async def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str:
        import asyncio

        bucket, object_key = self._bucket_for(key)
        stream = io.BytesIO(content)

        def upload() -> None:
            try:
                self.client.put_object(
                    bucket,
                    object_key,
                    content_length=len(content),
                    content_type=content_type or "application/octet-stream",
                    content=stream,
                )
            except TypeError:
                stream.seek(0)
                self.client.put_object(
                    bucket, object_key, len(content), content_type or "application/octet-stream", content=stream
                )

        await asyncio.to_thread(upload)
        return self._public_url(bucket, object_key)


def get_storage() -> Storage:
    if settings.storage_backend == "tos":
        required = (
            settings.tos_endpoint,
            settings.tos_region,
            settings.tos_access_key,
            settings.tos_secret_key,
            settings.tos_reference_bucket or settings.tos_video_bucket,
        )
        if not all(required):
            raise RuntimeError("STORAGE_BACKEND=tos，但 TOS 配置不完整")
        return TosStorage()
    return LocalStorage()


async def import_remote(url: str, category: str, filename: str | None = None) -> str:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
    guessed = filename or Path(httpx.URL(url).path).name or "asset.bin"
    content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
    if "." not in guessed:
        guessed += mimetypes.guess_extension(content_type) or ""
    return await get_storage().put_bytes(safe_key(category, guessed), response.content, content_type)
