"""Write objects over the regional OSS intranet and publish stable HTTPS URLs."""

import asyncio
import os
import tempfile
from urllib.parse import quote, unquote, urlsplit

import oss2

from .config import settings


def public_host() -> str:
    return f"{settings.oss_bucket}.oss-{settings.oss_region}.aliyuncs.com" if settings.oss_bucket else ""


def is_oss_host(url: str) -> bool:
    return bool(public_host() and (urlsplit(url).hostname or "").rstrip(".").lower() == public_host())


def internal_read_url(url: str) -> str | None:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.netloc != public_host() or not public_host() or parsed.query or parsed.fragment:
        return None
    path = unquote(parsed.path)
    if "%" in path or "\\" in path or any(part in {".", ".."} for part in path.split("/")) or not path.startswith(f"/{settings.oss_prefix}/"):
        return None
    return f"https://{settings.oss_bucket}.oss-{settings.oss_region}-internal.aliyuncs.com{parsed.path}"


class OssStorage:
    def __init__(self):
        if not all((settings.oss_access_key_id, settings.oss_access_key_secret, settings.oss_bucket, settings.oss_region, settings.oss_prefix)):
            raise RuntimeError("OSS 配置不完整")
        auth = oss2.AuthV4(settings.oss_access_key_id, settings.oss_access_key_secret)
        endpoint = f"https://oss-{settings.oss_region}"
        self.bucket = oss2.Bucket(auth, endpoint + "-internal.aliyuncs.com", settings.oss_bucket, region=settings.oss_region)
        self.public_bucket = oss2.Bucket(auth, endpoint + ".aliyuncs.com", settings.oss_bucket, region=settings.oss_region)

    async def put_bytes(self, key: str, content: bytes, content_type: str | None = None) -> str:
        object_key = f"{settings.oss_prefix}/{key}"
        await asyncio.to_thread(self.bucket.put_object, object_key, content, headers={"Content-Type": content_type or "application/octet-stream"})
        return f"https://{public_host()}/{quote(object_key, safe='/')}"

    async def put_file(self, key, path, content_type=None, progress_callback=None, content_disposition=None) -> str:
        object_key = f"{settings.oss_prefix}/{key}"
        headers = {"Content-Type": content_type or "application/octet-stream"}
        if content_disposition:
            headers["Content-Disposition"] = content_disposition
        part_size = settings.export_upload_part_size_mb * 1024**2

        def upload():
            with tempfile.TemporaryDirectory(prefix="mv-oss-checkpoint-") as checkpoint:
                oss2.resumable_upload(
                    self.bucket,
                    object_key,
                    os.fspath(path),
                    store=oss2.ResumableStore(root=checkpoint),
                    headers=headers,
                    multipart_threshold=part_size,
                    part_size=part_size,
                    num_threads=settings.export_upload_concurrency,
                    progress_callback=progress_callback,
                )

        # Keep the caller's temporary file until the SDK thread has stopped reading it.
        transfer = asyncio.create_task(asyncio.to_thread(upload))
        try:
            await asyncio.shield(transfer)
        except asyncio.CancelledError:
            await transfer
            raise
        return f"https://{public_host()}/{quote(object_key, safe='/')}"
