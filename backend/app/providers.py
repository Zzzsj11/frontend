from __future__ import annotations

import uuid
from typing import Any

import httpx

from .config import settings
from .jobs import Job, jobs
from .schemas import ImageGenerationCreate, VideoGenerationCreate
from .storage import import_remote


class ProviderError(RuntimeError):
    pass


def _headers(api_key: str, *, x_api_key: bool = False) -> dict[str, str]:
    auth = {"x-api-key": api_key} if x_api_key else {"Authorization": f"Bearer {api_key}"}
    return {**auth, "Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    if body.get("code") != 200:
        raise ProviderError(body.get("msg") or f"上游接口返回错误：{body.get('code')}")
    return body.get("data") or {}


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
        task_id = _unwrap(response.json()).get("taskId")
        if not task_id:
            raise ProviderError("生图接口未返回 taskId")
        data = await _poll(client, f"{base}/image/generation/tasks/{task_id}", headers, job)
    urls = data.get("resultUrls") or ([data["resultUrl"]] if data.get("resultUrl") else [])
    if not urls:
        raise ProviderError("生图成功但未返回图片地址")
    stored = [await import_remote(url, "images") for url in urls]
    return {"provider": "yinghe", "providerTaskId": task_id, "urls": stored, "sourceUrls": urls}


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
        "duration": request.duration,
        "watermark": request.watermark,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        response.raise_for_status()
        task_id = _unwrap(response.json()).get("taskId")
        if not task_id:
            raise ProviderError("视频接口未返回 taskId")
        data = await _poll(client, f"{base}/video/generation/tasks/{task_id}", headers, job)
    source_url = data.get("resultUrl")
    if not source_url:
        raise ProviderError("视频生成成功但未返回地址")
    stored_url = await import_remote(source_url, "videos", f"{task_id}.mp4")
    cover_url = data.get("coverUrl") or data.get("firstFrameUrl")
    stored_cover = await import_remote(cover_url, "covers") if cover_url else None
    return {
        "provider": "yinghe",
        "providerTaskId": task_id,
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "sourceUrl": source_url,
        "duration": request.duration,
        "ratio": request.ratio,
    }
