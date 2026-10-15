"""Convert owned TOS references into the platform's image/WAV chat inputs."""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
from pathlib import Path
from typing import Any

import httpx

from .storage import is_user_owned_tos_url


async def _command(*args: str) -> bytes:
    process = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, error = await asyncio.wait_for(process.communicate(), timeout=60)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    if process.returncode:
        raise ValueError("参考媒体无法解析：" + error.decode(errors="replace")[-300:])
    return out


async def content_parts(media: list[dict[str, Any]], user_id: str) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    counters = {"image": 0, "video": 0, "audio": 0}
    for item in media:
        kind, url = item["kind"], item["url"]
        if not is_user_owned_tos_url(url, user_id):
            raise ValueError("参考素材必须属于当前账号的 TOS")
        counters[kind] += 1
        label = {"image": "Picture", "video": "Video", "audio": "Audio"}[kind] + f" {counters[kind]}"
        result.append({"type": "text", "text": f"<{label}>"})
        if kind == "image":
            result.append({"type": "image_url", "image_url": {"url": url}})
            continue
        with tempfile.TemporaryDirectory(prefix="mv-optimizer-") as folder:
            source = Path(folder) / "source"
            async with httpx.AsyncClient(timeout=60) as client, client.stream("GET", url) as response:
                response.raise_for_status()
                size = 0
                with source.open("wb") as output:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 50 * 1024 * 1024:
                            raise ValueError("参考媒体不能超过 50MB")
                        output.write(chunk)
            probe = json.loads(await _command("ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type", "-of", "json", str(source)))
            seconds = float(probe.get("format", {}).get("duration", 0))
            if not 0 < seconds <= 15.1:
                raise ValueError("参考视频或音频需在 15 秒以内")
            if kind == "video":
                for index, offset in enumerate((0, seconds / 2, max(0, seconds - 0.2))):
                    frame = Path(folder) / f"frame-{index}.jpg"
                    await _command("ffmpeg", "-v", "error", "-ss", str(offset), "-i", str(source), "-frames:v", "1", "-vf", "scale=768:-2", "-y", str(frame))
                    result.extend(
                        [
                            {"type": "text", "text": f"<{label}> sampled frame at {offset:.2f}s; infer motion only from these samples."},
                            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(frame.read_bytes()).decode()}},
                        ]
                    )
            if any(stream.get("codec_type") == "audio" for stream in probe.get("streams", [])):
                audio = Path(folder) / "audio.wav"
                await _command("ffmpeg", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-y", str(audio))
                result.append({"type": "input_audio", "input_audio": {"data": base64.b64encode(audio.read_bytes()).decode(), "format": "wav"}})
            elif kind == "audio":
                raise ValueError("参考音频没有可解析的音轨")
    return result
