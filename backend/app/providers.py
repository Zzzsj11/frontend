from __future__ import annotations

import asyncio
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import settings
from .jobs import Job, jobs
from .schemas import ImageGenerationCreate, VideoGenerationCreate
from .storage import import_remote, import_remote_image, put_image_with_thumbnail, safe_key


class ProviderError(RuntimeError):
    pass


# AIGC 供应商错误码 → 用户友好提示
_AIGC_FRIENDLY_ERRORS: dict[str, str] = {
    "VID-4030": "视频生成额度已用尽，请联系管理员充值或更换 API Key",
    "IMG-4030": "图片生成额度已用尽，请联系管理员充值或更换 API Key",
}


def _raise_for_status(response: httpx.Response) -> None:
    """对 AIGC 返回的 HTTP 错误，尝试解析 body 中的业务错误码并翻译为友好提示。"""
    try:
        response.raise_for_status()
        return
    except httpx.HTTPStatusError as exc:
        try:
            body = response.json()
            code = (body.get("data") or {}).get("code", "")
            msg = body.get("msg", "")
        except Exception:
            raise ProviderError(str(exc)) from exc
        friendly = _AIGC_FRIENDLY_ERRORS.get(code)
        if friendly:
            raise ProviderError(friendly) from exc
        if msg:
            raise ProviderError(msg) from exc
        raise ProviderError(str(exc)) from exc


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


IMAGE_POLL_TIMEOUT_SECONDS = 360
VIDEO_POLL_TIMEOUT_SECONDS = 900
POLL_INTERVAL_SECONDS = 30
POLL_MAX_CONSECUTIVE_ERRORS = 5


def _image_config() -> tuple[str, dict[str, str]]:
    if not settings.image_api_key:
        raise ProviderError("IMAGE_API_KEY 未配置")
    return settings.image_api_base_url.rstrip("/"), _headers(settings.image_api_key, x_api_key=True)


def _video_config() -> tuple[str, dict[str, str]]:
    if not settings.video_api_key:
        raise ProviderError("VIDEO_API_KEY 未配置")
    return settings.video_api_base_url.rstrip("/"), _headers(settings.video_api_key)


async def _query_task(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> dict[str, Any]:
    response = await client.get(url, headers=headers)
    _raise_for_status(response)
    return _unwrap(response.json())


async def _poll(
    client: httpx.AsyncClient,
    url: str,
    headers: dict[str, str],
    job: Job,
    *,
    timeout_seconds: int,
    interval_seconds: int = POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """轮询供应商任务至终态。生成任务昂贵：瞬时网络/5xx 抖动连续 5 次才判败，不轻易放弃已计费任务"""
    deadline = time.monotonic() + timeout_seconds
    consecutive_errors = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(interval_seconds)
        try:
            data = await _query_task(client, url, headers)
        except Exception as exc:
            consecutive_errors += 1
            if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                raise ProviderError(f"查询生成状态连续失败：{str(exc)[:500]}") from exc
            continue
        consecutive_errors = 0
        status = str(data.get("status", "")).upper()
        await jobs.update_progress(job, int(data.get("progress") or job.progress + 2))
        if status == "SUCCESS":
            return data
        if status in {"FAILED", "CANCELLED"} or "FAIL" in status:
            raise ProviderError(data.get("failReason") or f"生成任务状态：{status}")
    raise ProviderError("生成任务超时，请稍后查询")


async def generate_image(request: ImageGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _image_config()
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
        _raise_for_status(response)
        created = _unwrap(response.json())
        task_id = created.get("taskId")
        if not task_id:
            raise ProviderError("生图接口未返回 taskId")
        await jobs.set_provider_task(job, "yinghe", task_id, idempotency_key=headers.get("Idempotency-Key"))
        data = await _poll(client, f"{base}/image/generation/tasks/{task_id}", headers, job, timeout_seconds=IMAGE_POLL_TIMEOUT_SECONDS)
    return await _store_image_result(job, task_id, data, created)


async def _store_image_result(job: Job, task_id: str, data: dict[str, Any], created: dict[str, Any]) -> dict[str, Any]:
    urls = data.get("resultUrls") or ([data["resultUrl"]] if data.get("resultUrl") else [])
    if not urls:
        raise ProviderError("生图成功但未返回图片地址")
    owner_prefix = f"users/{job.user_id}/generated/images"
    stored_assets = [await import_remote_image(url, owner_prefix) for url in urls]
    return {
        "provider": "yinghe",
        "providerTaskId": task_id,
        "model": (job.request or {}).get("model") or settings.image_model,
        "urls": [item[0] for item in stored_assets],
        "thumbnailUrls": [item[1] for item in stored_assets],
        "sourceUrls": urls,
        "usage": _usage(data) or _usage(created),
    }


async def generate_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _video_config()
    content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
    content.extend({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"} for url in request.image_urls)
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
        _raise_for_status(response)
        created = _unwrap(response.json())
        task_id = created.get("taskId")
        if not task_id:
            raise ProviderError("视频接口未返回 taskId")
        await jobs.set_provider_task(job, "yinghe", task_id, idempotency_key=headers.get("Idempotency-Key"))
        data = await _poll(client, f"{base}/video/generation/tasks/{task_id}", headers, job, timeout_seconds=VIDEO_POLL_TIMEOUT_SECONDS)
    return await _store_video_result(job, task_id, data, created)


async def _store_video_result(job: Job, task_id: str, data: dict[str, Any], created: dict[str, Any]) -> dict[str, Any]:
    request = job.request or {}
    source_url = data.get("resultUrl")
    if not source_url:
        raise ProviderError("视频生成成功但未返回地址")
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"{task_id}.mp4")
    cover_url = data.get("coverUrl") or data.get("firstFrameUrl")
    stored_cover, stored_cover_thumbnail = (
        await import_remote_image(cover_url, f"{owner_prefix}/covers") if cover_url else await _video_first_frame(source_url, task_id, job.user_id)
    )
    return {
        "provider": "yinghe",
        "providerTaskId": task_id,
        "model": request.get("model") or settings.video_model,
        "usage": _usage(data) or _usage(created),
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": request.get("duration"),
        "ratio": request.get("ratio"),
    }


async def resume_generation(job: Job) -> dict[str, Any]:
    """重启恢复：按已落库的供应商 taskId 续跑轮询，不重复提交任务"""
    if not job.provider_task_id:
        raise ProviderError("缺少供应商任务ID，无法恢复")
    if job.kind == "image":
        base, headers = _image_config()
        url, timeout = f"{base}/image/generation/tasks/{job.provider_task_id}", IMAGE_POLL_TIMEOUT_SECONDS
    elif job.kind == "video":
        base, headers = _video_config()
        url, timeout = f"{base}/video/generation/tasks/{job.provider_task_id}", VIDEO_POLL_TIMEOUT_SECONDS
    else:
        raise ProviderError(f"不支持恢复的任务类型：{job.kind}")
    async with httpx.AsyncClient(timeout=60) as client:
        data = await _poll(client, url, headers, job, timeout_seconds=timeout)
    return await store_provider_result(job, data)


async def query_provider_task(kind: str, task_id: str) -> dict[str, Any]:
    """单次查询供应商任务状态（管理后台对账用）"""
    if kind == "image":
        base, headers = _image_config()
        url = f"{base}/image/generation/tasks/{task_id}"
    elif kind == "video":
        base, headers = _video_config()
        url = f"{base}/video/generation/tasks/{task_id}"
    else:
        raise ProviderError(f"不支持的任务类型：{kind}")
    async with httpx.AsyncClient(timeout=60) as client:
        return await _query_task(client, url, headers)


async def store_provider_result(job: Job, data: dict[str, Any]) -> dict[str, Any]:
    """供应商成功结果下载落库（重启恢复与对账同步共用）"""
    task_id = job.provider_task_id or ""
    if job.kind == "image":
        return await _store_image_result(job, task_id, data, {})
    if job.kind == "video":
        return await _store_video_result(job, task_id, data, {})
    raise ProviderError(f"不支持的任务类型：{job.kind}")


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
            get_ffmpeg_exe(),
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            "0",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(cover_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode or not cover_path.is_file():
            raise ProviderError(f"提取视频首帧失败：{stderr.decode(errors='replace')[:300]}")
        return await put_image_with_thumbnail(safe_key(f"users/{user_id}/generated/covers", f"{task_id}.jpg"), cover_path.read_bytes(), "image/jpeg")
