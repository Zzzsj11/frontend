from __future__ import annotations

import asyncio
import io
import ipaddress
import mimetypes
import re
import socket
import tempfile
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Awaitable, Callable, Protocol
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx
from anyio import CapacityLimiter, to_thread
from PIL import Image, ImageOps

from .config import settings
from .oss_storage import OssStorage, internal_read_url, is_oss_host

_IMAGE_WORKERS = CapacityLimiter(2)
MAX_IMAGE_BYTES = 32 * 1024**2
MAX_IMAGE_PIXELS = 40_000_000


class Storage(Protocol):
    async def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str: ...

    async def put_file(
        self,
        key: str,
        path: str | Path,
        content_type: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        content_disposition: str | None = None,
    ) -> str: ...


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


def is_platform_storage_host(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    allowed = {settings.tos_public_domain.lower()} if settings.tos_public_domain else set()
    endpoint = settings.tos_endpoint.replace("https://", "").replace("http://", "").strip("/").lower()
    for bucket in (settings.tos_reference_bucket, settings.tos_video_bucket):
        if bucket and endpoint:
            allowed.add(f"{bucket}.{endpoint}")
    return host in allowed or is_oss_host(url)


def is_tos_url(url: str) -> bool:
    return urlparse(url).scheme == "https" and is_platform_storage_host(url) and not is_oss_host(url)


def is_user_owned_tos_url(url: str, user_id: str) -> bool:
    """Accept only TOS objects stored below the authenticated user's prefix."""
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not (is_tos_url(url) or is_oss_host(url)) or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
    except ValueError:
        return False
    path = parsed.path
    # 校验与 HTTP 客户端必须使用相同路径；拒绝多次编码、分隔符和目录跳转歧义。
    for _ in range(5):
        decoded = unquote(path)
        if decoded == path:
            break
        path = decoded
    else:
        return False
    if "\\" in path or any(part in {".", ".."} for part in path.split("/")):
        return False
    if is_oss_host(url):
        return path.startswith(f"/{settings.oss_prefix}/users/{user_id}/")
    prefixes = {"", "mv-agent/references", "mv-agent/generated-videos", settings.tos_reference_prefix.strip("/"), settings.tos_video_prefix.strip("/")}
    return any(path.startswith(f"/{prefix + '/' if prefix else ''}users/{user_id}/") for prefix in prefixes)


class TosStorage:
    def __init__(self) -> None:
        import tos

        try:
            self.client = tos.TosClientV2(
                settings.tos_access_key,
                settings.tos_secret_key,
                settings.tos_endpoint,
                settings.tos_region,
                request_timeout=settings.tos_request_timeout_seconds,
                socket_timeout=settings.tos_socket_timeout_seconds,
                max_retry_count=settings.tos_max_retry_count,
            )
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

    async def put_file(
        self,
        key: str,
        path: str | Path,
        content_type: str | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        content_disposition: str | None = None,
    ) -> str:
        bucket, object_key = self._bucket_for(key)
        file_path = str(path)

        def upload() -> None:
            # TOS SDK 的 data_transfer_listener 为 (consumed, total, rw_once, type) 同步回调，
            # 统一包装成 (consumed, total) 供上层估算上传进度
            listener = None
            if progress_callback:
                listener = lambda consumed, total, _rw, _type: progress_callback(consumed, total)  # noqa: E731
            # 大文件使用 SDK 的分片并发上传；相比 put_object_from_file 单路上传，能更充分利用带宽。
            self.client.upload_file(
                bucket,
                object_key,
                file_path,
                content_type=content_type or "application/octet-stream",
                part_size=settings.export_upload_part_size_mb * 1024 * 1024,
                task_num=settings.export_upload_concurrency,
                enable_checkpoint=False,
                data_transfer_listener=listener,
                **({"content_disposition": content_disposition} if content_disposition else {}),
            )

        await asyncio.to_thread(upload)
        return self._public_url(bucket, object_key)


def get_storage() -> Storage:
    if settings.storage_backend == "oss":
        return OssStorage()
    if settings.storage_backend != "tos":
        raise RuntimeError("不支持的媒体存储类型")
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


async def import_remote(
    url: str, category: str, filename: str | None = None, *, validate_media: bool = False, authorize_source: Callable[[str], Awaitable[None]] | None = None
) -> str:
    with tempfile.TemporaryDirectory(prefix="mvagent-import-") as temp_dir:
        target = Path(temp_dir) / "remote.bin"
        response_url, content_type, _size = await download_public_url_to_path(url, target)
        if authorize_source:
            await authorize_source(response_url)
        guessed = filename or Path(httpx.URL(response_url).path).name or "asset.bin"
        if "." not in guessed:
            guessed += mimetypes.guess_extension(content_type) or ""
        key = safe_key(category, guessed)
        if validate_media:
            from .upload_validation import ALLOWED_UPLOAD_TYPES, validate_av_path

            suffix = Path(guessed).suffix.lower()
            if suffix not in ALLOWED_UPLOAD_TYPES or content_type not in ALLOWED_UPLOAD_TYPES[suffix]:
                raise ValueError("文件扩展名与受支持的媒体格式不符")
            if content_type.startswith("image/"):
                if _size > MAX_IMAGE_BYTES:
                    raise ValueError("图片文件过大")
                thumbnail = await image_thumbnail(target, content_type)
                storage = get_storage()
                url = await storage.put_file(key, target, content_type)
                await storage.put_bytes(f"{key.rsplit('.', 1)[0]}-thumbnail.jpg", thumbnail, "image/jpeg")
                return url
            await validate_av_path(target, suffix, content_type)
        return await get_storage().put_file(key, target, content_type)


def make_image_thumbnail(content: bytes | Path, max_size: tuple[int, int] = (640, 640), expected_type: str | None = None) -> bytes:
    """Create a lightweight JPEG preview while preserving the complete image aspect ratio."""
    if isinstance(content, bytes) and len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片文件过大")
    with Image.open(io.BytesIO(content) if isinstance(content, bytes) else content) as source:
        if source.width * source.height > MAX_IMAGE_PIXELS or (expected_type and Image.MIME.get(source.format) != expected_type):
            raise ValueError("图片尺寸超限或格式与声明不一致")
        source.thumbnail(max_size, Image.Resampling.LANCZOS)
        image = ImageOps.exif_transpose(source).convert("RGB")
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        output = io.BytesIO()
        image.save(output, format="JPEG", quality=78, optimize=True, progressive=True)
        return output.getvalue()


async def image_thumbnail(content: bytes | Path, content_type: str | None = None) -> bytes:
    try:
        return await to_thread.run_sync(make_image_thumbnail, content, (640, 640), content_type, limiter=_IMAGE_WORKERS)
    except (Image.DecompressionBombError, OSError) as exc:
        raise ValueError("图片文件无法解析或尺寸过大") from exc


async def put_image_with_thumbnail(key: str, content: bytes, content_type: str | None = None) -> tuple[str, str]:
    storage = get_storage()
    thumbnail = await image_thumbnail(content, content_type)
    original_url = await storage.put_bytes(key, content, content_type)
    thumbnail_key = f"{key.rsplit('.', 1)[0]}-thumbnail.jpg"
    thumbnail_url = await storage.put_bytes(thumbnail_key, thumbnail, "image/jpeg")
    return original_url, thumbnail_url


async def import_remote_image(url: str, category: str, filename: str | None = None) -> tuple[str, str]:
    with tempfile.TemporaryDirectory(prefix="mv-image-") as directory:
        target = Path(directory) / "image"
        response_url, content_type, _ = await download_public_url_to_path(url, target, max_bytes=MAX_IMAGE_BYTES)
        thumbnail = await image_thumbnail(target)
        key = safe_key(category, filename or Path(httpx.URL(response_url).path).name or "image.png")
        storage = get_storage()
        original = await storage.put_file(key, target, content_type)
        preview = await storage.put_bytes(f"{key.rsplit('.', 1)[0]}-thumbnail.jpg", thumbnail, "image/jpeg")
        return original, preview


_HTTP_PUBLIC_URL_ALLOWLIST = frozenset({"store.vod-qcloud.com"})
_TRUSTED_PROXY_DNS_HOSTS = frozenset({"files.toapis.cn"})
_PROXY_DNS_RANGE = ipaddress.ip_network("198.18.0.0/15")


async def _validate_public_url(url: str) -> str:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    scheme_allowed = parsed.scheme == "https" or (parsed.scheme == "http" and hostname in _HTTP_PUBLIC_URL_ALLOWLIST)
    if not scheme_allowed or not hostname or parsed.username or parsed.password:
        raise ValueError("仅支持不含凭证的 HTTPS 公网地址（受信任供应商域名除外）")
    default_port = 443 if parsed.scheme == "https" else 80
    addresses = await asyncio.get_running_loop().getaddrinfo(hostname, parsed.port or default_port, type=socket.SOCK_STREAM)
    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0])
        if hostname in _TRUSTED_PROXY_DNS_HOSTS and parsed.scheme == "https" and (parsed.port is None or parsed.port == 443) and address in _PROXY_DNS_RANGE:
            continue
        if not address.is_global:
            raise ValueError("禁止访问内网、回环或链路本地地址")
    if not addresses:
        raise ValueError("远程地址未解析到可用 IP")
    return str(addresses[0][4][0])


def _pinned_request(url: str, address: str) -> tuple[httpx.URL, dict]:
    original = httpx.URL(url)
    # 保留 HTTP Host 与 TLS SNI/证书校验，但连接使用刚校验过的 IP。
    # 禁止连接复用，避免共享 IP 的不同主机复用错误的 TLS 身份。
    return original.copy_with(host=address), {
        "headers": {"Host": original.netloc.decode("ascii"), "Connection": "close"},
        "extensions": {"sni_hostname": original.host},
    }


async def _download_request(url: str):
    internal = internal_read_url(url)
    if internal:
        # Unsigned GET of the same public object, using only the configured bucket endpoint.
        return httpx.URL(internal), {}
    return _pinned_request(url, await _validate_public_url(url))


@asynccontextmanager
async def stream_public_download(url: str, client: httpx.AsyncClient):
    current = url
    for _ in range(4):
        target, options = await _download_request(current)
        async with client.stream("GET", target, **options) as response:
            if response.is_redirect and (location := response.headers.get("location")):
                current = urljoin(current, location)
                continue
            response.raise_for_status()
            yield response
            return
    raise ValueError("远程地址重定向次数过多")


async def download_public_url(url: str, max_bytes: int = 500 * 1024 * 1024) -> tuple[str, bytes, str]:
    current = url
    async with httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False) as client:
        for _ in range(4):
            target, options = await _download_request(current)
            async with client.stream("GET", target, **options) as response:
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


async def download_public_url_to_path(
    url: str,
    destination: str | Path,
    max_bytes: int = 500 * 1024 * 1024,
    progress_callback: Callable[[int, int | None], Awaitable[None]] | None = None,
    client: httpx.AsyncClient | None = None,
) -> tuple[str, str, int]:
    """Stream a public HTTPS object to disk instead of retaining it in memory."""
    current = url
    target = Path(destination)
    owned_client = client is None
    active_client = client or httpx.AsyncClient(timeout=180, follow_redirects=False, trust_env=False)
    try:
        for _ in range(4):
            pinned_url, options = await _download_request(current)
            async with active_client.stream("GET", pinned_url, **options) as response:
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
                size = 0
                total = declared or None
                with target.open("wb") as output:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValueError("远程文件超过允许大小")
                        output.write(chunk)
                        if progress_callback:
                            await progress_callback(size, total)
                content_type = response.headers.get("content-type", "application/octet-stream").split(";", 1)[0]
                return current, content_type, size
        raise ValueError("远程地址重定向次数过多")
    finally:
        if owned_client:
            await active_client.aclose()
