from __future__ import annotations

import asyncio
import io
import ipaddress
import mimetypes
import re
import socket
import uuid
from pathlib import Path
from typing import Protocol
from urllib.parse import quote, urljoin, urlparse

import httpx
from PIL import Image, ImageOps

from .config import settings


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


def is_tos_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    allowed = {settings.tos_public_domain.lower()} if settings.tos_public_domain else set()
    endpoint = settings.tos_endpoint.replace("https://", "").replace("http://", "").strip("/").lower()
    for bucket in (settings.tos_reference_bucket, settings.tos_video_bucket):
        if bucket and endpoint:
            allowed.add(f"{bucket}.{endpoint}")
    return urlparse(url).scheme == "https" and host in allowed


class TosStorage:
    def __init__(self) -> None:
        import tos

        try:
            self.client = tos.TosClientV2(settings.tos_access_key, settings.tos_secret_key, settings.tos_endpoint, settings.tos_region)
        except TypeError:
            self.client = tos.TosClientV2(settings.tos_access_key, settings.tos_secret_key, settings.tos_endpoint)

    @staticmethod
    def _bucket_for(key: str) -> tuple[str, str]:
        if key.startswith("videos/") or "/videos/" in key:
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
                self.client.put_object(bucket, object_key, len(content), content_type or "application/octet-stream", content=stream)

        await asyncio.to_thread(upload)
        return self._public_url(bucket, object_key)


def get_storage() -> Storage:
    if settings.storage_backend != "tos":
        raise RuntimeError("持久媒体仅支持 TOS，请设置 STORAGE_BACKEND=tos")
    required = (
        settings.tos_endpoint,
        settings.tos_region,
        settings.tos_access_key,
        settings.tos_secret_key,
        settings.tos_reference_bucket or settings.tos_video_bucket,
    )
    if not all(required):
        raise RuntimeError("TOS 配置不完整")
    return TosStorage()


async def import_remote(url: str, category: str, filename: str | None = None) -> str:
    response_url, content, content_type = await download_public_url(url)
    guessed = filename or Path(httpx.URL(response_url).path).name or "asset.bin"
    if "." not in guessed:
        guessed += mimetypes.guess_extension(content_type) or ""
    return await get_storage().put_bytes(safe_key(category, guessed), content, content_type)


def make_image_thumbnail(content: bytes, max_size: tuple[int, int] = (640, 640)) -> bytes:
    """Create a lightweight JPEG preview while preserving the complete image aspect ratio."""
    with Image.open(io.BytesIO(content)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=78, optimize=True, progressive=True)
        return output.getvalue()


async def put_image_with_thumbnail(key: str, content: bytes, content_type: str | None = None) -> tuple[str, str]:
    storage = get_storage()
    original_url = await storage.put_bytes(key, content, content_type)
    thumbnail_key = f"{key.rsplit('.', 1)[0]}-thumbnail.jpg"
    thumbnail_url = await storage.put_bytes(thumbnail_key, make_image_thumbnail(content), "image/jpeg")
    return original_url, thumbnail_url


async def import_remote_image(url: str, category: str, filename: str | None = None) -> tuple[str, str]:
    response_url, content, content_type = await download_public_url(url)
    guessed = filename or Path(httpx.URL(response_url).path).name or "image.png"
    return await put_image_with_thumbnail(safe_key(category, guessed), content, content_type)


async def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("仅支持不含凭证的 HTTPS 公网地址")
    addresses = await asyncio.get_running_loop().getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0])
        if not address.is_global:
            raise ValueError("禁止访问内网、回环或链路本地地址")


async def download_public_url(url: str, max_bytes: int = 500 * 1024 * 1024) -> tuple[str, bytes, str]:
    current = url
    async with httpx.AsyncClient(timeout=180, follow_redirects=False) as client:
        for _ in range(4):
            await _validate_public_url(current)
            async with client.stream("GET", current) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        response.raise_for_status()
                    current = urljoin(current, location)
                    continue
                response.raise_for_status()
                declared = int(response.headers.get("content-length") or 0)
                if declared > max_bytes:
                    raise ValueError("远程文件超过允许大小")
                chunks, size = [], 0
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > max_bytes:
                        raise ValueError("远程文件超过允许大小")
                    chunks.append(chunk)
                content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
                return current, b"".join(chunks), content_type
    raise ValueError("远程地址重定向次数过多")
