"""Import a platform-owned OSS archive into this MV user's media directory."""

import asyncio
import logging
import re
from urllib.parse import urlsplit

import httpx

from .config import settings
from .oss_storage import OssStorage, public_host

logger = logging.getLogger(__name__)


def source_key(url, platform_id, suffix):
    if not isinstance(url, str):
        return None
    path = urlsplit(url)
    if path.scheme != "https" or not public_host() or path.netloc != public_host() or path.query or path.fragment:
        return None
    # Only object names minted by the platform archiver. Never copy a caller-supplied
    # URL, an MV upload or a result stored under a different platform job.
    pattern = rf"(?:[\w-]+/)*clients/[\w-]+/users/u-[a-f0-9]{{32}}/{re.escape(platform_id)}/{re.escape(suffix)}"
    key = path.path.removeprefix("/")
    return key if re.fullmatch(pattern, key, re.ASCII) else None


async def copy_platform_archive(job, body, owner):
    result = body.get("result") or {}
    manifest = result.get("archive")
    platform_id = job.provider_task_id
    if settings.storage_backend != "oss" or not platform_id or body.get("id") != platform_id or manifest != {"version": 1, "job_id": platform_id, "storage": "oss"}:
        return None
    media = result.get("media") or []
    if len(media) != 1:
        return None
    item = media[0]
    imported = {}
    if job.kind == "video":
        meta = item.get("metadata") or {}
        stream = meta.get("stream") or {}
        if not all(meta.get(key) for key in ("width", "height", "file_size", "duration", "fps")) or not stream.get("codec_name"):
            return None
        imported.update(
            actualWidth=meta["width"],
            actualHeight=meta["height"],
            fileSize=meta["file_size"],
            actualDuration=round(meta["duration"], 3),
            fps=round(meta["fps"], 4),
            codec=stream["codec_name"],
            sourceUrl=item["url"],
        )
        objects = [
            ("videoUrl", "url", "videos/0.mp4", f"videos/{job.id}.mp4"),
            ("coverUrl", "cover_url", "covers/0.jpg", f"covers/{job.id}.jpg"),
            ("coverThumbnailUrl", "thumbnail_url", "covers/0-thumbnail.jpg", f"covers/{job.id}-thumbnail.jpg"),
        ]
    else:
        fmt = item.get("archived_format")
        if fmt not in ("jpeg", "png", "gif", "webp"):
            return None
        objects = [("urls", "url", f"images/0.{fmt}", f"images/{job.id}.{fmt}"), ("thumbnailUrls", "thumbnail_url", "images/0-thumbnail.jpg", f"images/{job.id}-thumbnail.jpg")]
        imported["sourceUrls"] = [item["url"]]
    sources = [source_key(item.get(field), platform_id, suffix) for _, field, suffix, _ in objects]
    if not all(sources) or len({key.rsplit("/", 2)[0] for key in sources}) != 1:
        return None
    storage = OssStorage()
    try:
        # Deterministic destinations also tolerate resuming a partially copied job.
        copies = await asyncio.gather(*(storage.copy_object(source, f"{owner}/{dest}") for source, (_, _, _, dest) in zip(sources, objects)), return_exceptions=True)
        for (name, _, _, _), copied in zip(objects, copies):
            if isinstance(copied, BaseException):
                raise copied
            imported[name] = [copied] if job.kind == "image" else copied
    except Exception as exc:
        logger.warning("Platform OSS copy failed for job=%s error=%s", job.id, type(exc).__name__)
        return None
    if job.kind == "video":
        job.video_metadata_probed = True
    return imported


async def verify_deployment():
    from .all_in_one import headers

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(settings.all_in_one_base_url + "/v1/account/archive-config", headers=headers(user_id="mv-deployment-check"))
        response.raise_for_status()
    expected = {"storage": "oss", "version": 1, "bucket": settings.oss_bucket, "region": settings.oss_region, "host": public_host()}
    actual = response.json()
    mismatch = [field for field, value in expected.items() if actual.get(field) != value]
    if settings.storage_backend != "oss" or mismatch:
        raise RuntimeError("MV 与同环境平台的 OSS 归档配置不兼容，请检查 " + ", ".join(mismatch or ["storage"]))


if __name__ == "__main__":
    asyncio.run(verify_deployment())
