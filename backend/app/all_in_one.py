"""ALL IN ONE's documented personal/system key and durable media protocol."""

from __future__ import annotations

import asyncio
import logging
import random
import time
import uuid
from contextlib import asynccontextmanager, nullcontext
from contextvars import ContextVar
from typing import Any

import httpx
from openai import AsyncOpenAI

from .agent_attribution import current_agent_attribution, current_test_run_id
from .config import settings

PROVIDER = "all-in-one"
SUFFIX = "-all-in-one"
logger = logging.getLogger(__name__)


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
    from .generation_context import current_agent

    _, name, run = current_agent_attribution()
    if current_agent() is not None:
        name, run = current_agent() or ("", "")
    if run:
        result.update({"X-Agent-Name": name or "code-agent", "X-Agent-Run-Id": run, "X-Test-Run-Id": current_test_run_id() or run})
    return result


def chat_client(*, user_id: str | None = None, timeout: float = 600, idempotency_key: str | None = None) -> AsyncOpenAI:
    return AsyncOpenAI(
        base_url=settings.all_in_one_base_url.rstrip("/") + "/v1",
        api_key=settings.all_in_one_api_key,
        default_headers=headers(user_id=user_id, idempotency_key=idempotency_key or "aio-chat-" + uuid.uuid4().hex),
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


_poll_client: ContextVar[httpx.AsyncClient | None] = ContextVar("platform_poll_client", default=None)


class PlatformPolling:
    """Accepted jobs keep their database reservation while submit slots become available."""

    def __init__(self, on_accepted, query_budget):
        self.on_accepted = on_accepted
        self.query_budget = query_budget
        self.requests = asyncio.Semaphore(32)
        self.waiting = 0

    def delay(self):
        return max(8, self.waiting / self.query_budget) * random.uniform(0.9, 1.1)


_worker_polling: ContextVar[PlatformPolling | None] = ContextVar("worker_platform_polling", default=None)


class VideoTraffic:
    def __init__(self):
        self.submit_lock = asyncio.Lock()
        self.next_submit = 0.0
        self.submitting = asyncio.Semaphore(16)
        self.archiving = asyncio.Semaphore(8)

    @asynccontextmanager
    async def submit(self):
        async with self.submitting:
            async with self.submit_lock:
                loop = asyncio.get_running_loop()
                await asyncio.sleep(max(0, self.next_submit - loop.time()))
                self.next_submit = loop.time() + 1 / settings.video_create_qps
            yield


_video_traffic: ContextVar[VideoTraffic | None] = ContextVar("video_traffic", default=None)


async def submit_media(client: httpx.AsyncClient, endpoint: str, payload: dict, request_headers: dict, *, before_send=None):
    url = settings.all_in_one_base_url.rstrip("/") + "/v1/" + endpoint
    traffic = _video_traffic.get()
    if traffic and endpoint == "videos":
        for attempt in range(3):
            async with traffic.submit():
                if before_send:
                    await before_send()
                try:
                    response = await client.post(url, headers=request_headers, json=payload)
                except httpx.RequestError:
                    found = await _lookup_submission(client, request_headers, payload["model"])
                    if found is not None:
                        return found
                    raise
            safe_rejection = response.headers.get("x-platform-job-created") == "false" and response.headers.get("x-generation-submitted") == "false"
            full = response.status_code == 429 and "Shared generation pool is full" in response.text
            if not (safe_rejection or full):
                if response.status_code >= 500 and not response.headers.get("x-job-id"):
                    found = await _lookup_submission(client, request_headers, payload["model"])
                    if found is not None:
                        return found
                return response
            if attempt == 2:
                return response
            try:
                delay = float(response.headers.get("retry-after", 2**attempt))
            except ValueError:
                return response
            if not 0 <= delay <= 60:
                return response
            await asyncio.sleep(delay + random.uniform(0, 0.25))
    if before_send:
        await before_send()
    try:
        response = await client.post(url, headers=request_headers, json=payload)
    except httpx.RequestError:
        if endpoint == "images":
            found = await _lookup_submission(client, request_headers, payload["model"])
            if found is not None:
                return found
        raise
    if endpoint == "images" and response.status_code >= 500 and not response.headers.get("x-job-id"):
        safe_rejection = response.headers.get("x-platform-job-created") == "false" and response.headers.get("x-generation-submitted") == "false"
        if not safe_rejection:
            found = await _lookup_submission(client, request_headers, payload["model"])
            if found is not None:
                return found
    return response


async def _lookup_submission(client, request_headers, model):
    try:
        found = await client.get(settings.all_in_one_base_url + "/v1/jobs/lookup", params={"idempotency_key": request_headers["Idempotency-Key"]}, headers=request_headers)
        if found.status_code == 200 and found.json().get("model") == model and found.json().get("id"):
            return found
    except (httpx.HTTPError, ValueError):
        pass
    return None


async def query_task(kind: str, task_id: str, *, user_id: str | None = None) -> dict[str, Any]:
    from .providers import _raise_for_status

    url = settings.all_in_one_base_url.rstrip("/") + f"/v1/jobs/{task_id}"
    client = _poll_client.get()
    if client is None:
        async with httpx.AsyncClient(timeout=60) as temporary:
            response = await temporary.get(url, headers=headers(user_id=user_id))
    else:
        response = await client.get(url, headers=headers(user_id=user_id))
    _raise_for_status(response)
    return normalized_task(response.json())


async def store_result(job: Any, body: dict[str, Any]) -> dict[str, Any]:
    from .providers import ProviderError
    from .storage import import_remote_image

    data = normalized_task(body)
    urls = data["resultUrls"]
    if not urls:
        raise ProviderError("all in one 任务成功但未返回 result.media[].url")
    owner = f"users/{job.user_id}/generated"
    common = {"provider": PROVIDER, "providerTaskId": job.provider_task_id, "model": (job.request or {}).get("model"), "usage": data["usage"]}
    from .platform_archive import copy_platform_archive

    started = time.monotonic()
    copied = await copy_platform_archive(job, body, owner)
    if copied:
        archived_result = {**common, **copied, "archiveMethod": "oss_copy", "archiveMs": round((time.monotonic() - started) * 1000)}
        if job.kind == "video":
            archived_result.update(duration=(job.request or {}).get("duration"), ratio=(job.request or {}).get("ratio"))
        return archived_result
    if job.kind == "image":
        stored = [await import_remote_image(url, owner + "/images") for url in urls]
        return {
            **common,
            "urls": [p[0] for p in stored],
            "thumbnailUrls": [p[1] for p in stored],
            "sourceUrls": urls,
            "archiveMethod": "import",
            "archiveMs": round((time.monotonic() - started) * 1000),
        }
    raise ProviderError("all in one 视频归档未通过校验或 OSS 复制失败，请核查原工单归档")


async def generate(request: Any, job: Any) -> dict[str, Any]:
    from .jobs import jobs
    from .providers import ProviderError, ProviderRejectedError, ProviderSubmissionUncertainError, _raise_for_status

    snapshot = job.request or {}
    model = snapshot.get("_providerModelId") or upstream_model(request.model)
    payload: dict[str, Any] = {"model": model, "prompt": request.prompt}
    if snapshot.get("channel"):
        payload["channel"] = snapshot["channel"]
    if job.kind == "image":
        if request.quality != "auto":
            raise ProviderError("all in one 图片模型仅支持 quality=auto")
        if request.n != 1:
            raise ProviderError("all in one 每次生成一张图片")
        if request.images:
            payload["images"] = request.images
        from .image_model_policy import image_ratio

        payload.update(size=image_ratio(request.size, model), resolution=request.resolution, quality="auto", n=request.n)
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
    if job.kind == "video" and request.person_asset_mode:
        if model != "seedance-2.0":
            raise ProviderError("人物资产模式仅支持 SD2.0")
        payload["person_asset_mode"] = True
        payload["person_reference_indices"] = request.person_reference_indices
    recover_image = job.kind == "image" and bool(job.idempotency_key)
    job.idempotency_key = f"{job.id}:{job.kind}"
    request_headers = headers(user_id=job.user_id, idempotency_key=job.idempotency_key)
    await jobs.record_provider_request(job, payload)
    try:
        endpoint = "images" if job.kind == "image" else "videos"
        shared = _poll_client.get()
        async with nullcontext(shared) if shared is not None else httpx.AsyncClient(timeout=60) as client:
            response = await _lookup_submission(client, request_headers, model) if recover_image else None
            if response is None:
                response = await submit_media(client, endpoint, payload, request_headers, before_send=lambda: jobs.mark_provider_submitting(job))
            # Do not resubmit a potentially accepted request on a 5xx or transport failure.
            if response.status_code >= 500:
                try:
                    error_body = response.json()
                except ValueError:
                    error_body = {}
                if not isinstance(error_body, dict):
                    error_body = {}
                detail = error_body.get("error") or error_body.get("detail") or {}
                task_id = response.headers.get("x-job-id") or (detail.get("job_id") if isinstance(detail, dict) else None)
                if task_id:
                    await jobs.set_provider_task(job, PROVIDER, task_id, idempotency_key=job.idempotency_key)
                    return await resume(job)
                if response.headers.get("x-platform-job-created") == "false" and response.headers.get("x-generation-submitted") == "false":
                    await jobs.record_provider_response(job, "rejected_before_acceptance", {"httpStatus": response.status_code, "body": error_body, "generationSubmitted": False})
                    media_name = "图片" if job.kind == "image" else "视频"
                    raise ProviderRejectedError(f"平台当前无可用渠道，本次未创建平台任务、未提交{media_name}生成；请稍后重试")
                error = ProviderSubmissionUncertainError("all in one 服务异常，提交结果不确定；请核查原任务")
                error.provider = PROVIDER
                error.request_id = response.headers.get("x-request-id")
                raise error
            _raise_for_status(response)
            body = response.json()
            task_id = body.get("id") if isinstance(body, dict) else None
            if not task_id:
                raise ProviderSubmissionUncertainError("all in one 受理响应缺少平台任务 ID，请核查原请求")
            await jobs.set_provider_task(job, PROVIDER, task_id, idempotency_key=job.idempotency_key)
            await jobs.record_provider_response(job, "submission", body)
    except ProviderError as exc:
        exc.provider = PROVIDER
        raise
    except (httpx.RequestError, ValueError) as exc:
        error = ProviderSubmissionUncertainError("all in one 提交结果不确定，请核查原任务")
        error.provider = PROVIDER
        raise error from exc
    return await resume(job)


async def resume(job: Any) -> dict[str, Any]:
    scheduler = _worker_polling.get()
    if scheduler is None or not job.worker_id or not job.provider_task_id:
        return await _poll_until_complete(job, None)
    scheduler.on_accepted()
    scheduler.waiting += 1
    try:
        return await _poll_until_complete(job, scheduler)
    finally:
        scheduler.waiting -= 1


async def _poll_until_complete(job: Any, scheduler: PlatformPolling | None) -> dict[str, Any]:
    import asyncio
    import time

    from .jobs import jobs
    from .providers import IMAGE_POLL_TIMEOUT_SECONDS, POLL_INTERVAL_SECONDS, POLL_MAX_CONSECUTIVE_ERRORS, ProviderError, _remaining_provider_timeout, _remaining_video_job_timeout

    remaining = _remaining_provider_timeout(job, IMAGE_POLL_TIMEOUT_SECONDS) if job.kind == "image" else _remaining_video_job_timeout(job)
    deadline = time.monotonic() + remaining
    consecutive_errors = 0
    while time.monotonic() < deadline:
        try:
            async with scheduler.requests if scheduler else nullcontext():
                data = await query_task(job.kind, job.provider_task_id, user_id=job.user_id)
            consecutive_errors = 0
        except Exception as exc:
            if scheduler is None or job.phase != "reconciling":
                job.phase = "reconciling"
                await jobs.update_progress(job, job.progress)
            consecutive_errors += 1
            if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS and job.kind != "video":
                error = ProviderError("平台状态暂不可查，请核查原任务")
                error.requires_reconciliation = True
                raise error from exc
            await asyncio.sleep(scheduler.delay() if scheduler else POLL_INTERVAL_SECONDS * random.uniform(0.9, 1.1))
            continue
        new_phase = {
            "QUEUED": "platform_queued",
            "PENDING": "platform_queued",
            "RUNNING": "provider_running",
            "PROCESSING": "provider_running",
            "ARCHIVING": "archiving",
            "SUCCEEDED": "archiving",
        }.get(data["status"], "reconciling")
        review = data.get("asset_review") or {}
        if review.get("status") == "reviewing":
            new_phase = "reviewing_assets"
        if scheduler is None or job.phase != new_phase:
            job.phase = new_phase
            await jobs.update_progress(job, job.progress)
        if data["status"] == "SUCCEEDED":
            await jobs.record_provider_response(job, "terminal", data)
            try:
                traffic = _video_traffic.get()
                if traffic and job.kind == "video":
                    job.phase = "storing_media"
                    await jobs.update_progress(job, job.progress)
                    async with traffic.archiving:
                        return await store_result(job, data)
                return await store_result(job, data)
            except Exception as exc:
                # 上游已交付并可能扣费，归档失败不能抹掉供应商用量。
                exc.requires_reconciliation = True
                exc.usage = data.get("usage") or {}
                exc.provider = PROVIDER
                exc.request_id = job.provider_task_id
                raise
        if data["status"] in {"FAILED", "CANCELLED"}:
            await jobs.record_provider_response(job, "terminal", data)
            error = ProviderError(data["failReason"] or "all in one 生成失败")
            error.requires_reconciliation = not confirmed_failure(job.provider_task_id, data)
            error.usage = data.get("usage") or {}
            error.provider = PROVIDER
            error.request_id = job.provider_task_id
            raise error
        await asyncio.sleep(scheduler.delay() if scheduler else POLL_INTERVAL_SECONDS * random.uniform(0.9, 1.1))
    duration = "10分钟" if job.kind == "image" else "2小时"
    error = ProviderError(f"all in one 生成等待超过{duration}，请核查原任务；未重新提交")
    error.requires_reconciliation = True
    raise error


def confirmed_failure(task_id, data):
    """Only release retries on evidence for the same job and final accounting."""
    from .image_billing import settled

    return (
        bool(task_id)
        and data.get("id") == task_id
        and str(data.get("status") or "").upper() in {"FAILED", "CANCELLED", "CANCELED", "ERROR"}
        and not data.get("requires_reconciliation")
        and settled(data.get("billing") or (data.get("usage") or {}).get("platformBilling"), allow_refund=True)
    )
