"""ALL IN ONE's documented personal/system key and durable media protocol."""

from __future__ import annotations

import uuid
from typing import Any

import httpx
from openai import AsyncOpenAI

from .agent_attribution import current_agent_attribution
from .config import settings

PROVIDER = "all-in-one"
SUFFIX = "-all-in-one"


def upstream_model(model: str) -> str:
    return model.removesuffix(SUFFIX)


def headers(*, user_id: str | None = None, idempotency_key: str | None = None) -> dict[str, str]:
    if not settings.all_in_one_api_key:
        raise RuntimeError("all in one 渠道未配置 API Key")
    result = {"Authorization": f"Bearer {settings.all_in_one_api_key}"}
    if settings.all_in_one_system_key:
        if not user_id:
            raise RuntimeError("all in one 系统 Key 缺少用户归因")
        result["X-User-Id"] = user_id
    if idempotency_key:
        result["Idempotency-Key"] = idempotency_key
    from .model_gateway import current_agent

    _, name, run = current_agent_attribution()
    if current_agent() is not None:
        name, run = current_agent() or ("", "")
    if run:
        result.update({"X-Agent-Name": name or "code-agent", "X-Agent-Run-Id": run, "X-Test-Run-Id": run})
    return result


def chat_client(*, user_id: str | None = None, timeout: float = 600) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.all_in_one_base_url.rstrip("/") + "/v1",
        api_key=settings.all_in_one_api_key,
        default_headers=headers(user_id=user_id, idempotency_key="aio-chat-" + uuid.uuid4().hex),
        timeout=timeout,
        max_retries=0,
    )


def normalized_task(body: dict[str, Any]) -> dict[str, Any]:
    result = body.get("result") or {}
    media = result.get("media") or []
    return {
        **body,
        "status": str(body.get("status") or "").upper(),
        "resultUrls": [item["url"] for item in media if isinstance(item, dict) and item.get("url")],
        "failReason": body.get("error") or "",
        # Billing can be pending after delivery. Preserve it without claiming zero cost.
        "usage": {**(body.get("usage") or {}), "platformBilling": body.get("billing")},
    }


async def query_task(kind: str, task_id: str, *, user_id: str | None = None) -> dict[str, Any]:
    from .providers import _raise_for_status

    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(settings.all_in_one_base_url.rstrip("/") + f"/v1/jobs/{task_id}", headers=headers(user_id=user_id))
        _raise_for_status(response)
        return normalized_task(response.json())


async def store_result(job: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .providers import ProviderError, _video_first_frame
    from .storage import import_remote, import_remote_image

    data = normalized_task(body)
    urls = data["resultUrls"]
    if not urls:
        raise ProviderError("all in one 任务成功但未返回 result.media[].url")
    owner = f"users/{job.user_id}/generated"
    common = {"provider": PROVIDER, "providerTaskId": job.provider_task_id, "model": (job.request or {}).get("model"), "usage": data["usage"]}
    if job.kind == "image":
        stored = [await import_remote_image(url, owner + "/images") for url in urls]
        return {**common, "urls": [p[0] for p in stored], "thumbnailUrls": [p[1] for p in stored], "sourceUrls": urls}
    url = await import_remote(urls[0], owner + "/videos", filename=f"{job.id}.mp4")
    cover, thumbnail = await _video_first_frame(url, job.id, job.user_id)
    return {
        **common,
        "videoUrl": url,
        "coverUrl": cover,
        "coverThumbnailUrl": thumbnail,
        "sourceUrl": urls[0],
        "duration": (job.request or {}).get("duration"),
        "ratio": (job.request or {}).get("ratio"),
    }


async def generate(request: Any, job: Any) -> dict[str, Any]:
    from .jobs import jobs
    from .providers import ProviderError, ProviderSubmissionUncertainError, _raise_for_status, _toapis_image_ratio

    snapshot = job.request or {}
    model = snapshot.get("_providerModelId") or upstream_model(request.model)
    payload: dict[str, Any] = {"model": model, "prompt": request.prompt}
    if job.kind == "image":
        if request.quality != "auto":
            raise ProviderError("all in one 图片模型仅支持 quality=auto")
        payload.update(images=request.images, size=_toapis_image_ratio(request.size), resolution=request.resolution, quality="auto", n=request.n)
    else:
        mode = snapshot.get("_h3Mode") or request.h3_mode
        modes = {"first_last": "first_last", "first_frame": "first_frame", "reference": "reference", "text": "text"}
        resolution_map = (snapshot.get("_capabilities") or {}).get("providerResolutionMap") or {}
        if model == "seedance-2.0" and request.image_urls:
            if any(url.startswith("asset://") for url in request.image_urls):
                raise ProviderError("all in one 须使用原始 TOS 参考图，不能复用英和账户的 asset://")
        payload.update(
            duration=int(request.duration),
            aspect_ratio=request.ratio,
            resolution=resolution_map.get(request.resolution, request.resolution),
            images=request.image_urls,
            videos=request.video_urls,
            audios=request.audio_urls,
            reference_mode=modes.get(mode, "auto"),
            generate_audio=request.generate_audio,
            watermark=request.watermark,
        )
    job.idempotency_key = f"{job.id}:{job.kind}"
    request_headers = headers(user_id=job.user_id, idempotency_key=job.idempotency_key)
    await jobs.record_provider_request(job, payload)
    await jobs.mark_provider_submitting(job)
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(settings.all_in_one_base_url.rstrip("/") + f"/v1/{'images' if job.kind == 'image' else 'videos'}", headers=request_headers, json=payload)
            # Do not resubmit a potentially accepted request on a 5xx or transport failure.
            if response.status_code >= 500:
                error_body = response.json()
                detail = error_body.get("error") or error_body.get("detail") or {}
                task_id = response.headers.get("x-job-id") or (detail.get("job_id") if isinstance(detail, dict) else None)
                if task_id:
                    await jobs.set_provider_task(job, PROVIDER, task_id, idempotency_key=job.idempotency_key)
                    return await resume(job)
                error = ProviderSubmissionUncertainError("all in one 服务异常，提交结果不确定；请核查原任务")
                error.provider = PROVIDER
                error.request_id = response.headers.get("x-request-id")
                raise error
            _raise_for_status(response)
            body = response.json()
            await jobs.record_provider_response(job, "submission", body)
    except ProviderError as exc:
        if getattr(exc, "submission_certain", False):
            from .image_failover import record_outcome

            await record_outcome(job, succeeded=False)
        exc.provider = PROVIDER
        raise
    except (httpx.RequestError, ValueError) as exc:
        error = ProviderSubmissionUncertainError("all in one 提交结果不确定，请核查原任务")
        error.provider = PROVIDER
        raise error from exc
    task_id = body.get("id")
    if not task_id:
        raise ProviderSubmissionUncertainError("all in one 受理响应缺少平台任务 ID，请核查原请求")
    await jobs.set_provider_task(job, PROVIDER, task_id, idempotency_key=job.idempotency_key)
    return await resume(job)


async def resume(job: Any) -> dict[str, Any]:
    import asyncio
    import time

    from .jobs import jobs
    from .providers import IMAGE_POLL_TIMEOUT_SECONDS, POLL_INTERVAL_SECONDS, POLL_MAX_CONSECUTIVE_ERRORS, ProviderError, _remaining_provider_timeout, _remaining_video_job_timeout

    remaining = _remaining_provider_timeout(job, IMAGE_POLL_TIMEOUT_SECONDS) if job.kind == "image" else _remaining_video_job_timeout(job)
    deadline = time.monotonic() + remaining
    consecutive_errors = 0
    while time.monotonic() < deadline:
        try:
            data = await query_task(job.kind, job.provider_task_id, user_id=job.user_id)
            consecutive_errors = 0
        except Exception:
            consecutive_errors += 1
            if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                raise
            await asyncio.sleep(POLL_INTERVAL_SECONDS)
            continue
        if data["status"] == "SUCCEEDED":
            await jobs.record_provider_response(job, "terminal", data)
            from .image_failover import record_outcome

            await record_outcome(job, succeeded=True)
            return await store_result(job, data)
        if data["status"] in {"FAILED", "CANCELLED"}:
            await jobs.record_provider_response(job, "terminal", data)
            from .image_failover import record_outcome

            await record_outcome(job, succeeded=False)
            raise ProviderError(data["failReason"] or "all in one 生成失败")
        await jobs.update_progress(job, min(90, job.progress + 2))
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
    raise ProviderError("all in one 生成等待超过2小时，请核查原任务；未重新提交")
