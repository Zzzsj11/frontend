from __future__ import annotations

import uuid
import asyncio
import tempfile
from pathlib import Path
from typing import Any

import httpx

from .config import settings
from .jobs import Job, jobs
from .schemas import ImageGenerationCreate, VideoGenerationCreate
from .storage import import_remote, import_remote_image, put_image_with_thumbnail, safe_key


class ProviderError(RuntimeError):
    pass


def _headers(api_key: str, *, x_api_key: bool = False) -> dict[str, str]:
    auth = {"x-api-key": api_key} if x_api_key else {"Authorization": f"Bearer {api_key}"}
    return {**auth, "Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("code") != 200:
        raise ProviderError(body.get("msg") or f"上游接口返回错误：{body.get('code')}")
    return body.get("data") or {}


def _usage(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("usage"), dict):
        return data["usage"]
    keys = ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "output_tokens", "outputTokens", "completion_tokens", "completionTokens", "total_tokens", "totalTokens")
    return {key: data[key] for key in keys if key in data}


async def _poll(client: httpx.AsyncClient, url: str, headers: dict[str, str], job: Job) -> dict[str, Any]:
    import asyncio

    for _ in range(120):
        await asyncio.sleep(3)
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        data = _unwrap(response.json())
        status = str(data.get("status", "")).upper()
        await jobs.update_progress(job, int(data.get("progress") or job.progress + 2))
        if status == "SUCCESS":
            return data
        if status in {"FAILED", "CANCELLED"} or "FAIL" in status:
            raise ProviderError(data.get("failReason") or f"生成任务状态：{status}")
    raise ProviderError("生成任务超时，请稍后查询")


async def generate_image(request: ImageGenerationCreate, job: Job) -> dict[str, Any]:
    if not settings.image_api_key:
        raise ProviderError("IMAGE_API_KEY 未配置")
    base = settings.image_api_base_url.rstrip("/")
    headers = _headers(settings.image_api_key, x_api_key=True)
    payload: dict[str, Any] = {
        "model": request.model or settings.image_model,
        "prompt": request.prompt,
        "size": request.size,
        "quality": request.quality,
        "n": request.n,
    }
    if request.images:
        payload["image"] = request.images if len(request.images) > 1 else request.images[0]
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/image/generation/tasks", headers=headers, json=payload)
        response.raise_for_status()
        created = _unwrap(response.json())
        task_id = created.get("taskId")
        if not task_id:
            raise ProviderError("生图接口未返回 taskId")
        data = await _poll(client, f"{base}/image/generation/tasks/{task_id}", headers, job)
    urls = data.get("resultUrls") or ([data["resultUrl"]] if data.get("resultUrl") else [])
    if not urls:
        raise ProviderError("生图成功但未返回图片地址")
    owner_prefix = f"users/{job.user_id}/generated/images"
    stored_assets = [await import_remote_image(url, owner_prefix) for url in urls]
    return {"provider": "yinghe", "providerTaskId": task_id, "model": request.model or settings.image_model, "urls": [item[0] for item in stored_assets], "thumbnailUrls": [item[1] for item in stored_assets], "sourceUrls": urls, "usage": _usage(data) or _usage(created)}


async def generate_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    if not settings.video_api_key:
        raise ProviderError("VIDEO_API_KEY 未配置")
    base = settings.video_api_base_url.rstrip("/")
    headers = _headers(settings.video_api_key)
    content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
    content.extend(
        {"type": "image_url", "image_url": {"url": url}, "role": "reference_image"}
        for url in request.image_urls
    )
    payload = {
        "model": request.model or settings.video_model,
        "content": content,
        "generate_audio": request.generate_audio,
        "ratio": request.ratio,
        "resolution": request.resolution,
        "duration": request.duration,
        "watermark": request.watermark,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        response.raise_for_status()
        created = _unwrap(response.json())
        task_id = created.get("taskId")
        if not task_id:
            raise ProviderError("视频接口未返回 taskId")
        data = await _poll(client, f"{base}/video/generation/tasks/{task_id}", headers, job)
    source_url = data.get("resultUrl")
    if not source_url:
        raise ProviderError("视频生成成功但未返回地址")
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"{task_id}.mp4")
    cover_url = data.get("coverUrl") or data.get("firstFrameUrl")
    stored_cover, stored_cover_thumbnail = await import_remote_image(cover_url, f"{owner_prefix}/covers") if cover_url else await _video_first_frame(source_url, task_id, job.user_id)
    return {
        "provider": "yinghe",
        "providerTaskId": task_id,
        "model": request.model or settings.video_model,
        "usage": _usage(data) or _usage(created),
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": request.duration,
        "ratio": request.ratio,
    }


async def _video_first_frame(video_url: str, task_id: str, user_id: str | None) -> tuple[str, str]:
    """Extract the default shot cover from the generated video's first frame."""
    async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
        response = await client.get(video_url)
        response.raise_for_status()
    with tempfile.TemporaryDirectory(prefix="mvagent-cover-") as temp_dir:
        video_path = Path(temp_dir) / "source.mp4"
        cover_path = Path(temp_dir) / "cover.jpg"
        video_path.write_bytes(response.content)
        from imageio_ffmpeg import get_ffmpeg_exe
        process = await asyncio.create_subprocess_exec(
            get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y", "-ss", "0", "-i", str(video_path),
            "-frames:v", "1", "-q:v", "2", str(cover_path),
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode or not cover_path.is_file():
            raise ProviderError(f"提取视频首帧失败：{stderr.decode(errors='replace')[:300]}")
        return await put_image_with_thumbnail(safe_key(f"users/{user_id}/generated/covers", f"{task_id}.jpg"), cover_path.read_bytes(), "image/jpeg")
