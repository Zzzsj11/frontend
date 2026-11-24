from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from .config import settings
from .storage import download_public_url_to_path

video_result_slots = asyncio.Semaphore(settings.video_result_processing_concurrency)


def provider_resolution(model: str, requested: str, capabilities: dict[str, Any] | None = None) -> str:
    configured = (capabilities or {}).get("providerResolutionMap") or {}
    value = configured.get(requested)
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value.get("label"):
        return str(value["label"])
    if model == "minimax-h3":
        return "2K" if requested == "1080p" else "768P"
    if model == "minimax-h3-runninghub":
        return {"480p": "0.4MP", "720p": "0.9MP", "1080p": "1.8MP"}.get(requested, requested)
    return requested.upper()


async def probe_video_url(url: str) -> dict[str, Any]:
    async with video_result_slots:
        with tempfile.TemporaryDirectory(prefix="mv-video-probe-") as directory:
            path = Path(directory) / "video.mp4"
            await download_public_url_to_path(url, path)
            return await probe_video_file(path)


async def probe_video_file(path: Path) -> dict[str, Any]:
    from .providers import _communicate_bounded

    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-protocol_whitelist",
        "file,pipe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,r_frame_rate,codec_name:format=duration,size",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await _communicate_bounded(process)
    if process.returncode != 0:
        raise ValueError(f"ffprobe failed: {stderr.decode(errors='ignore')[:200]}")
    body = json.loads(stdout)
    stream = (body.get("streams") or [{}])[0]
    format_data = body.get("format") or {}
    numerator, _, denominator = str(stream.get("r_frame_rate") or "0/1").partition("/")
    fps = float(numerator or 0) / float(denominator or 1)
    return {
        "actualWidth": int(stream.get("width") or 0),
        "actualHeight": int(stream.get("height") or 0),
        "fps": round(fps, 4),
        "codec": str(stream.get("codec_name") or ""),
        "actualDuration": round(float(format_data.get("duration") or 0), 3),
        "fileSize": int(format_data.get("size") or path.stat().st_size),
    }
