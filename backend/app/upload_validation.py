"""上传音视频以容器和流信息校验内容，避免信任客户端 MIME。"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from fastapi import HTTPException

FORMATS = {
    ".mp3": {"mp3"},
    ".wav": {"wav"},
    ".ogg": {"ogg"},
    ".mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    ".mov": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    ".m4a": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    ".webm": {"matroska", "webm"},
}


ALLOWED_UPLOAD_TYPES: dict[str, set[str]] = {
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
    ".gif": {"image/gif"},
    ".mp4": {"video/mp4"},
    ".mov": {"video/quicktime"},
    ".webm": {"video/webm"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/vnd.wave"},
    ".m4a": {"audio/mp4", "audio/x-m4a"},
    ".ogg": {"audio/ogg", "video/ogg"},
}


async def validate_av_content(filename: str, content_type: str, content: bytes) -> None:
    suffix = Path(filename).suffix.lower()
    with tempfile.TemporaryDirectory(prefix="mv-upload-validation-") as directory:
        path = Path(directory) / ("upload" + suffix)
        await asyncio.to_thread(path.write_bytes, content)
        await validate_av_path(path, suffix, content_type)


async def validate_av_path(path: Path, suffix: str, content_type: str) -> None:
    from .providers import _communicate_bounded

    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-protocol_whitelist",
        "file,pipe",
        "-v",
        "error",
        "-show_entries",
        "format=format_name:stream=codec_type",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, _ = await _communicate_bounded(process, 30)
    except TimeoutError as exc:
        raise HTTPException(422, "音视频解析超时，请重新导出后上传") from exc
    try:
        metadata = json.loads(stdout)
        formats = set(metadata.get("format", {}).get("format_name", "").split(","))
        streams = {item.get("codec_type") for item in metadata.get("streams", [])}
    except (ValueError, AttributeError, TypeError) as exc:
        raise HTTPException(422, "音视频文件无法解析") from exc
    required = "video" if content_type.startswith("video/") else "audio"
    if process.returncode or required not in streams or not formats.intersection(FORMATS.get(suffix, set())):
        raise HTTPException(422, "文件内容与声明的音视频格式不一致")
