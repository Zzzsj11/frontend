from __future__ import annotations

import asyncio
import base64
import io
import json
import math
import re
import tempfile
import time
import uuid
import weakref
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from PIL import Image, UnidentifiedImageError

from . import model_gateway
from .config import settings
from .error_logging import _redact
from .jobs import Job, jobs
from .models import GenerationJobModel
from .runninghub import RunningHubError
from .runninghub import query_task as runninghub_query_task
from .runninghub import submit_first_frame_task as runninghub_submit_first_frame_task
from .runninghub import submit_first_last_frame_task as runninghub_submit_first_last_frame_task
from .runninghub import submit_reference_task as runninghub_submit_reference_task
from .runninghub import submit_text_task as runninghub_submit_text_task
from .runninghub import upload_media as runninghub_upload_media
from .schemas import ImageGenerationCreate, VideoGenerationCreate
from .storage import download_public_url, download_public_url_to_path, import_remote, import_remote_image, put_image_with_thumbnail, safe_key
from .video_prompt_policy import compile_content_safety_retry_prompt


class ProviderError(RuntimeError):
    pass


SUPPORTED_MEDIA_PROVIDERS = frozenset(
    {"yinghe", "yinghe-h3", "yinghe-wan", "yinghe-kling", "yinghe-happyhorse", "runninghub", "yseeai", "yseeai-omni", "yseeai-unified", "toapis", "toapis-grok", "toapis-viduq3"}
)
SUPPORTED_VIDEO_PROTOCOLS = frozenset({"wan-native", "kling-native", "happyhorse-native", "veo-unified", "gemini-omni-unified", "grok-toapis", "viduq3-toapis"})


def validate_media_provider(provider: str | None) -> None:
    if provider and provider not in SUPPORTED_MEDIA_PROVIDERS:
        raise ProviderError("该工单的供应商已不受支持，历史记录仅供查看，不能恢复或重新提交")


def validate_media_job_source(job: Job | GenerationJobModel) -> None:
    request = job.request or {}
    capabilities = request.get("_capabilities") or {}
    for provider in (job.provider, request.get("_provider"), capabilities.get("providerCode")):
        validate_media_provider(provider)
    protocol = capabilities.get("providerProtocol")
    if protocol and protocol not in SUPPORTED_VIDEO_PROTOCOLS:
        raise ProviderError("该工单的供应商协议已不受支持，历史记录仅供查看，不能恢复或重新提交")


class ProviderRejectedError(ProviderError):
    """The provider returned a definite rejection before creating a task."""

    submission_certain = True


class ProviderSubmissionUncertainError(ProviderError):
    """Both idempotent creation attempts ended before a definitive response arrived."""

    submission_certain = False


# AIGC 供应商错误码 → 用户友好提示
_AIGC_FRIENDLY_ERRORS: dict[str, str] = {
    "VID-4030": "视频生成额度已用尽，请联系管理员充值或更换 API Key",
    "IMG-4030": "图片生成额度已用尽，请联系管理员充值或更换 API Key",
}

# AIGC 供应商英文错误关键词 → 中文友好提示（按顺序匹配，首个命中的生效）
_PROVIDER_ERROR_TRANSLATIONS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"may contain real person", re.IGNORECASE),
        "输入参考图疑似包含真实人物，受平台合规限制无法生成。请更换为系统角色或 AI 生成的人物素材",
    ),
    (
        re.compile(r"content polic|sensitive (?:content|information)|unsafe content|violat", re.IGNORECASE),
        "内容未通过平台安全合规校验，请调整画面内容或提示词后重试",
    ),
    (
        re.compile(r"invalid (api.?key|token)|unauthorized|permission denied|api key not (found|valid)", re.IGNORECASE),
        "接口密钥无效或未授权，请联系管理员检查 API Key 配置",
    ),
]

_REQUEST_ID_RE = re.compile(r"request\s*id[:\s]*([a-zA-Z0-9\-]+)", re.IGNORECASE)
_PROVIDER_ERROR_BODY_MAX_CHARS = 4000


def _provider_error_body(body: Any) -> str:
    """保留供应商原始错误正文，同时避免密钥等敏感字段进入工单错误。"""
    try:
        text = json.dumps(_redact(body), ensure_ascii=False, separators=(",", ":"))
    except Exception:
        text = str(body)
    if len(text) > _PROVIDER_ERROR_BODY_MAX_CHARS:
        return f"{text[:_PROVIDER_ERROR_BODY_MAX_CHARS]}…（响应正文已截断）"
    return text


def _provider_error_message(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    for value in (body.get("msg"), body.get("message"), body.get("detail")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    error = body.get("error")
    if isinstance(error, str):
        return error.strip()
    if isinstance(error, dict):
        for value in (error.get("message"), error.get("msg"), error.get("detail"), error.get("code")):
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def translate_provider_error(msg: str) -> str:
    """把上游返回的英文错误翻译为中文友好提示；request id 单独保留，便于排查问题。"""
    if not msg:
        return msg
    request_id = ""
    match = _REQUEST_ID_RE.search(msg)
    if match:
        request_id = match.group(1)
    clean = _REQUEST_ID_RE.sub("", msg)
    translated = msg
    for pattern, friendly in _PROVIDER_ERROR_TRANSLATIONS:
        if pattern.search(clean):
            translated = friendly
            break
    if request_id:
        translated = f"{translated}（请求ID：{request_id}）"
    return translated


def _raise_for_status(response: httpx.Response) -> None:
    """对 AIGC 返回的 HTTP 错误，尝试解析 body 中的业务错误码并翻译为友好提示。"""
    try:
        response.raise_for_status()
        return
    except httpx.HTTPStatusError as exc:
        try:
            body = response.json()
            data = body.get("data") if isinstance(body, dict) else None
            code = (data or {}).get("code", "") if isinstance(data, dict) else ""
            msg = _provider_error_message(body)
        except Exception:
            raw_body = str(_redact(response.text.strip()))
            suffix = f"；供应商响应：{raw_body[:_PROVIDER_ERROR_BODY_MAX_CHARS]}" if raw_body else ""
            raise ProviderRejectedError(f"{exc}{suffix}") from exc
        body_text = _provider_error_body(body)
        body_suffix = f"；供应商响应：{body_text}"
        friendly = _AIGC_FRIENDLY_ERRORS.get(code)
        if friendly:
            raise ProviderRejectedError(f"{friendly}{body_suffix}") from exc
        if msg:
            raise ProviderRejectedError(f"{translate_provider_error(msg)}{body_suffix}") from exc
        raise ProviderRejectedError(f"{exc}{body_suffix}") from exc


def _headers(api_key: str, *, x_api_key: bool = False) -> dict[str, str]:
    auth = {"x-api-key": api_key} if x_api_key else {"Authorization": f"Bearer {api_key}"}
    return {**auth, "Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    # V3 Seedance 视频任务报文无 code/data 包装（官方格式），原样返回；
    # 素材接口与旧版任务接口均为 code/data 包装，且部分 V3 路由层错误也走包装（HTTP 200 + code=500）
    if "code" not in body:
        return body
    if body.get("code") != 200:
        raise ProviderRejectedError(translate_provider_error(body.get("msg") or f"上游接口返回错误：{body.get('code')}"))
    return body.get("data") or {}


def _usage(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("usage"), dict):
        return data["usage"]
    keys = ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "output_tokens", "outputTokens", "completion_tokens", "completionTokens", "total_tokens", "totalTokens")
    return {key: data[key] for key in keys if key in data}


# gpt-image-2 的业务终止线：供应商受理后 10 分钟仍未进入终态即失败。
IMAGE_POLL_TIMEOUT_SECONDS = 10 * 60
VIDEO_POLL_TIMEOUT_SECONDS = 20 * 60
H3_POLL_INTERVAL_SECONDS = 15
H3_REFERENCE_FILE_MAX_BYTES = 100 * 1024 * 1024
POLL_INTERVAL_SECONDS = 30
POLL_MAX_CONSECUTIVE_ERRORS = 5
POLL_SCHEDULER_TICK_SECONDS = 1.0

ASSET_POLL_TIMEOUT_SECONDS = 180
ASSET_POLL_INTERVAL_SECONDS = 3.0


async def create_real_face_asset(public_url: str, *, name: str) -> str:
    """把公开图片注册为 AIGC 平台虚拟资产，轮询至 Active，返回 asset://{id} 链接。

    视频生成传 asset:// 引用的是平台内部已托管素材，可绕过上游对真实人物的直接检测。
    """
    base, headers = _video_config()
    headers["group_id"] = settings.aigc_asset_group_id
    # V3 素材接口无 Moderation 参数（仅支持虚拟人像素材）
    payload = {
        "url": public_url,
        "name": name,
        "assetType": "Image",
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/v3/assets", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap(response.json())
        asset_id = created.get("id")
        if not asset_id:
            raise ProviderError("虚拟资产接口未返回 asset id")
        deadline = time.monotonic() + ASSET_POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(ASSET_POLL_INTERVAL_SECONDS)
            detail_response = await client.post(f"{base}/v3/assets/detail", headers=headers, json={"assetId": asset_id})
            _raise_for_status(detail_response)
            detail = _unwrap(detail_response.json())
            status = str(detail.get("status") or "")
            if status == "Active":
                return f"asset://{asset_id}"
            if status in {"Rejected", "Failed"}:
                raise ProviderError(f"虚拟资产审核未通过：{detail.get('errorMessage') or detail.get('errorCode') or status}")
        raise ProviderError(f"虚拟资产创建超时：{asset_id}")


def _image_config() -> tuple[str, dict[str, str]]:
    if model_gateway.routed("yinghe"):
        return model_gateway.route("yinghe")
    if not settings.image_api_key:
        raise ProviderError("IMAGE_API_KEY 未配置")
    return settings.image_api_base_url.rstrip("/"), _headers(settings.image_api_key, x_api_key=True)


def _video_config() -> tuple[str, dict[str, str]]:
    if model_gateway.routed("yinghe"):
        return model_gateway.route("yinghe")
    if not settings.video_api_key:
        raise ProviderError("VIDEO_API_KEY 未配置")
    return settings.video_api_base_url.rstrip("/"), _headers(settings.video_api_key)


def _yseeai_config() -> tuple[str, dict[str, str]]:
    if model_gateway.routed("yseeai"):
        return model_gateway.route("yseeai")
    if not settings.yseeai_api_key:
        raise ProviderError("YSEEAI_API_KEY 未配置")
    return settings.yseeai_api_base_url, _headers(settings.yseeai_api_key)


def _toapis_config() -> tuple[str, dict[str, str]]:
    if model_gateway.routed("toapis"):
        return model_gateway.route("toapis")
    if not settings.toapis_api_key:
        raise ProviderError("TOAPIS_API_KEY 未配置")
    return settings.toapis_api_base_url, _headers(settings.toapis_api_key)


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
        # 旧版任务报文成功为 SUCCESS，V3 Seedance 报文为 succeeded；失败原因分别在 failReason / error.message
        if status in {"SUCCESS", "SUCCEEDED"}:
            return data
        if status in {"FAILED", "CANCELLED"} or "FAIL" in status:
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            reason = data.get("failReason") or error.get("message") or f"生成任务状态：{status}"
            raise ProviderError(translate_provider_error(reason))
    raise ProviderError("生成任务超时，请稍后查询")


def _poll_batch_size(active_count: int, coverage_seconds: int = POLL_INTERVAL_SECONDS) -> int:
    """将活跃任务均匀分散到一个轮询周期内。

    例如 200 个任务、30 秒一轮，每秒查 ceil(200 / 30) = 7 个。
    """
    if active_count <= 0:
        return 0
    return max(1, math.ceil(active_count / max(1, coverage_seconds)))


@dataclass
class _ScheduledPoll:
    job: Job
    url: str
    headers: dict[str, str]
    deadline: float
    future: asyncio.Future[dict[str, Any]]
    consecutive_errors: int = 0
    timeout_error: str = "生成任务超时，请稍后查询"


class ProviderPollScheduler:
    """进程内全局时间轮：单客户端、小批次、公平轮询所有上游任务。"""

    def __init__(self, *, tick_seconds: float = POLL_SCHEDULER_TICK_SECONDS, coverage_seconds: int = POLL_INTERVAL_SECONDS) -> None:
        self.tick_seconds = tick_seconds
        self.coverage_seconds = coverage_seconds
        self._entries: dict[str, _ScheduledPoll] = {}
        self._queue: deque[str] = deque()
        self._runner: asyncio.Task[None] | None = None
        self._round_remaining = 0
        self._round_batch_size = 0

    @property
    def active_count(self) -> int:
        return len(self._entries)

    def batch_size(self) -> int:
        return _poll_batch_size(self.active_count, self.coverage_seconds)

    async def watch(
        self,
        url: str,
        headers: dict[str, str],
        job: Job,
        *,
        timeout_seconds: float,
        timeout_error: str = "生成任务超时，请稍后查询",
    ) -> dict[str, Any]:
        if job.id in self._entries:
            raise ProviderError(f"生成任务已在轮询：{job.id}")
        future = asyncio.get_running_loop().create_future()
        self._entries[job.id] = _ScheduledPoll(
            job,
            url,
            headers,
            time.monotonic() + max(0, timeout_seconds),
            future,
            timeout_error=timeout_error,
        )
        self._queue.append(job.id)
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._run())
        try:
            return await future
        finally:
            self._remove(job.id)

    def _remove(self, job_id: str) -> None:
        self._entries.pop(job_id, None)

    def _take_batch(self) -> list[_ScheduledPoll]:
        if self._round_remaining <= 0:
            self._round_remaining = len(self._queue)
            self._round_batch_size = _poll_batch_size(self._round_remaining, self.coverage_seconds)
        batch: list[_ScheduledPoll] = []
        take_count = min(self._round_batch_size, self._round_remaining, len(self._queue))
        for _ in range(take_count):
            job_id = self._queue.popleft()
            self._round_remaining -= 1
            entry = self._entries.get(job_id)
            if entry is not None:
                batch.append(entry)
        return batch

    async def _run(self) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            while self._entries:
                await asyncio.sleep(self.tick_seconds)
                now = time.monotonic()
                for job_id, entry in list(self._entries.items()):
                    if now >= entry.deadline:
                        self._finish_error(job_id, ProviderError(entry.timeout_error))
                batch = self._take_batch()
                if batch:
                    await asyncio.gather(*(self._query_one(client, entry) for entry in batch))

    async def _query_one(self, client: httpx.AsyncClient, entry: _ScheduledPoll) -> None:
        job_id = entry.job.id
        if job_id not in self._entries:
            return
        try:
            data = await _query_task(client, entry.url, entry.headers)
        except Exception as exc:
            entry.consecutive_errors += 1
            if entry.consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                self._finish_error(job_id, ProviderError(f"查询生成状态连续失败：{str(exc)[:500]}"))
            else:
                self._queue.append(job_id)
            return

        entry.consecutive_errors = 0
        status = str(data.get("status", "")).upper()
        await jobs.update_progress(entry.job, int(data.get("progress") or entry.job.progress + 2))
        if status in {"SUCCESS", "SUCCEEDED"}:
            self._finish_result(job_id, data)
            return
        if status in {"FAILED", "CANCELLED"} or "FAIL" in status:
            error = data.get("error") if isinstance(data.get("error"), dict) else {}
            reason = data.get("failReason") or error.get("message") or f"生成任务状态：{status}"
            self._finish_error(job_id, ProviderError(translate_provider_error(reason)))
            return
        self._queue.append(job_id)

    def _finish_result(self, job_id: str, data: dict[str, Any]) -> None:
        entry = self._entries.pop(job_id, None)
        if entry and not entry.future.done():
            entry.future.set_result(data)

    def _finish_error(self, job_id: str, error: Exception) -> None:
        entry = self._entries.pop(job_id, None)
        if entry and not entry.future.done():
            entry.future.set_exception(error)


_poll_schedulers: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, ProviderPollScheduler] = weakref.WeakKeyDictionary()
_result_semaphores: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[str, asyncio.Semaphore]] = weakref.WeakKeyDictionary()


def _poll_scheduler() -> ProviderPollScheduler:
    # pytest 会创建多个 event loop；按 loop 隔离，也避免 future 跨 loop 绑定。
    loop = asyncio.get_running_loop()
    scheduler = _poll_schedulers.get(loop)
    if scheduler is None:
        scheduler = ProviderPollScheduler()
        _poll_schedulers[loop] = scheduler
    return scheduler


async def _poll_scheduled(
    url: str,
    headers: dict[str, str],
    job: Job,
    *,
    timeout_seconds: float,
    timeout_error: str = "生成任务超时，请稍后查询",
) -> dict[str, Any]:
    return await _poll_scheduler().watch(url, headers, job, timeout_seconds=timeout_seconds, timeout_error=timeout_error)


def _remaining_provider_timeout(job: Job, timeout_seconds: int) -> float:
    """恢复轮询时仍以首次供应商受理时间计时，重启不能刷新超时预算。"""
    if job.provider_submitted_at is None:
        return float(timeout_seconds)
    return max(0.0, timeout_seconds - (time.time() - job.provider_submitted_at))


def _remaining_video_job_timeout(job: Job) -> float:
    """Video SLA is end-to-end from local job creation, not provider acceptance."""
    if job.created_at <= 0:
        return float(VIDEO_POLL_TIMEOUT_SECONDS)
    return max(0.0, VIDEO_POLL_TIMEOUT_SECONDS - (time.time() - job.created_at))


def _result_semaphore(kind: str) -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    slots = _result_semaphores.get(loop)
    if slots is None:
        slots = {
            "image": asyncio.Semaphore(settings.image_result_processing_concurrency),
            "video": asyncio.Semaphore(settings.video_result_processing_concurrency),
        }
        _result_semaphores[loop] = slots
    return slots[kind]


async def list_video_models() -> list[dict[str, Any]]:
    """查询 AIGC 平台当前账号可见的模型列表（OpenAI 风格 /v1/models）。

    key 从环境变量读取：VIDEO_API_KEY 优先，缺省回退 AIGC_TOKEN（与生成链路同一账号），
    保证列表展示的模型就是实际可用于生成（视频/图像/文本）的模型。
    """
    base, headers = _video_config()
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{base}/v1/models", headers=headers)
        _raise_for_status(response)
        body = response.json()
    if not isinstance(body, dict):
        raise ProviderError("模型列表接口返回格式异常")
    data = body.get("data")
    if not isinstance(data, list):
        raise ProviderError("模型列表接口未返回 data 数组")
    return [item for item in data if isinstance(item, dict)]


async def generate_image(request: ImageGenerationCreate, job: Job) -> dict[str, Any]:
    validate_media_job_source(job)
    base, headers = _image_config()
    # 供应商以 Header 中的 Idempotency-Key 去重创建。键必须在发请求前由
    # 本地持久化工单 ID 确定，不能使用 _headers() 的随机默认值，否则进程
    # 在“供应商已受理、taskId 尚未落库”的窗口恢复时仍可能重复生图。
    job.idempotency_key = f"{job.id}:image"
    headers["Idempotency-Key"] = job.idempotency_key
    payload: dict[str, Any] = {
        "model": request.model or settings.image_model,
        "prompt": request.prompt,
        "size": request.size,
        "quality": request.quality,
        "n": request.n,
    }
    if request.images:
        payload["image"] = request.images if len(request.images) > 1 else request.images[0]
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/image/generation/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap(response.json())
        task_id = created.get("taskId")
        if not task_id:
            raise ProviderError("生图接口未返回 taskId")
        await jobs.set_provider_task(job, "yinghe", task_id, idempotency_key=headers.get("Idempotency-Key"))
    data = await _poll_scheduled(
        f"{base}/image/generation/tasks/{task_id}",
        headers,
        job,
        timeout_seconds=_remaining_provider_timeout(job, IMAGE_POLL_TIMEOUT_SECONDS),
        timeout_error="gpt-image-2 生成超过10分钟，已判定失败",
    )
    return await _store_image_result(job, task_id, data, created)


async def _store_image_result(job: Job, task_id: str, data: dict[str, Any], created: dict[str, Any]) -> dict[str, Any]:
    async with _result_semaphore("image"):
        return await _store_image_result_inner(job, task_id, data, created)


async def _store_image_result_inner(job: Job, task_id: str, data: dict[str, Any], created: dict[str, Any]) -> dict[str, Any]:
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


async def _submit_seedance_video(request: VideoGenerationCreate, job: Job, image_urls: list[str]) -> tuple[str, dict[str, Any], str, dict[str, str]]:
    base, headers = _video_config()
    # 同一逻辑创建在网络重试时始终使用相同键；文本降级是另一份请求体，必须使用独立键。
    variant = "reference" if image_urls else "text"
    if (job.request or {}).get("_contentSafetyRetry"):
        variant += ":content-safety"
    job.idempotency_key = f"{job.id}:{variant}"
    headers["Idempotency-Key"] = job.idempotency_key
    content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
    content.extend({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"} for url in image_urls)
    resolution_map = ((job.request or {}).get("_capabilities") or {}).get("providerResolutionMap") or {}
    payload = {
        "model": request.model or settings.video_model,
        "content": content,
        "generate_audio": request.generate_audio,
        "ratio": request.ratio,
        "resolution": str(resolution_map.get(request.resolution) or request.resolution),
        "duration": request.duration,
        "watermark": request.watermark,
        # 让上游返回尾帧图做封面，免去本地 ffmpeg 抽帧
        "return_last_frame": True,
    }
    for field in ((job.request or {}).get("_capabilities") or {}).get("providerOmitFields") or []:
        payload.pop(str(field), None)
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await _post_idempotent_video_create(
            client,
            f"{base}/v3/video/tasks",
            headers=headers,
            payload=payload,
            job=job,
            provider="yinghe",
        )
        _raise_for_status(response)
        created = _unwrap(response.json())
        # V3 Seedance 官方报文：任务 ID 字段为 id（旧版为 taskId）
        task_id = created.get("id")
        if not task_id:
            raise ProviderError("视频接口未返回任务 id")
        await jobs.set_provider_task(job, "yinghe", task_id, idempotency_key=headers.get("Idempotency-Key"))
    return task_id, created, base, headers


def _unwrap_kling(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ProviderRejectedError("Kling 返回了无法解析的响应")
    if body.get("code") != 0 or not isinstance(body.get("data"), dict):
        message = str(body.get("message") or body.get("msg") or "Kling 返回错误")
        request_id = str(body.get("request_id") or "")
        suffix = f"（请求ID：{request_id}）" if request_id else ""
        raise ProviderRejectedError(f"{translate_provider_error(message)}{suffix}；供应商响应：{_provider_error_body(body)}")
    return body["data"]


async def _query_kling_task(base: str, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{base}/video/generation/tasks/{task_id}", headers=headers)
        _raise_for_status(response)
        return _unwrap_kling(response.json())


async def _poll_kling(base: str, headers: dict[str, str], job: Job) -> dict[str, Any]:
    deadline = time.monotonic() + _remaining_video_job_timeout(job)
    consecutive_errors = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(H3_POLL_INTERVAL_SECONDS)
        try:
            task = await _query_kling_task(base, headers, job.provider_task_id or "")
        except (httpx.HTTPError, ValueError, ProviderError) as exc:
            consecutive_errors += 1
            if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                raise ProviderError(f"Kling 状态查询连续失败：{exc}") from exc
            continue
        consecutive_errors = 0
        status = str(task.get("task_status") or task.get("status") or "").lower()
        await jobs.update_progress(job, job.progress + 3)
        if status in {"succeed", "succeeded", "success"}:
            return task
        if status in {"failed", "fail", "cancelled", "canceled"}:
            reason = task.get("task_status_msg") or task.get("message") or f"Kling 生成任务状态：{status}"
            raise ProviderError(f"Kling 生成失败：{reason}")
    raise ProviderError("视频生成超过20分钟，已判定失败，请重新生成")


async def _store_kling_result(job: Job, task: dict[str, Any]) -> dict[str, Any]:
    task_result = task.get("task_result") if isinstance(task.get("task_result"), dict) else {}
    videos = task_result.get("videos") if isinstance(task_result.get("videos"), list) else []
    output = next((item for item in videos if isinstance(item, dict) and item.get("url")), None)
    if not output:
        raise ProviderError("Kling 生成成功但未返回视频地址")
    task_id = job.provider_task_id or str(task.get("task_id") or "")
    source_url = str(output["url"])
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"kling-{task_id}.mp4")
    stored_cover, stored_cover_thumbnail = await _video_first_frame(source_url, f"kling-{task_id}", job.user_id)
    request = job.request or {}
    return {
        "provider": "yinghe",
        "providerTaskId": task_id,
        "model": request.get("model") or "kling-v3",
        "usage": task.get("usage") or {},
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": output.get("duration") or request.get("duration"),
        "ratio": request.get("ratio"),
    }


def kling_image_inputs(request: VideoGenerationCreate, *, identity_reference: bool = False) -> dict[str, str]:
    images = [url.strip() for url in request.image_urls if url.strip()]
    if not images:
        return {}
    if request.h3_mode == "reference" or (identity_reference and request.h3_mode == "auto"):
        raise ProviderError("Kling 人物参考需要主体 element_list；当前渠道尚未配置主体创建协议，不能将人物参考卡当作视频首帧。请先补齐渠道主体接口。")
    if len(images) > 2 or (len(images) == 2 and request.h3_mode != "first_last"):
        raise ProviderError("Kling V3 多图参考不能作为首尾帧自动提交；首尾帧生成需明确选择 first_last 模式。")
    if request.h3_mode == "first_last" and len(images) != 2:
        raise ProviderError("Kling 首尾帧生成需要两张图片。")
    return {"image": images[0], **({"image_tail": images[1]} if len(images) == 2 else {})}


async def generate_kling_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _video_config()
    job.idempotency_key = f"{job.id}:kling-native"
    headers["Idempotency-Key"] = job.idempotency_key
    mode = "pro" if request.resolution == "1080p" else "std"
    image_inputs = kling_image_inputs(request, identity_reference=bool((job.request or {}).get("_identityReferenceIndices")))
    payload: dict[str, Any] = {
        "model_name": str((job.request or {}).get("_providerModelId") or "kling-v3"),
        "prompt": request.prompt,
        "duration": request.duration,
        "mode": mode,
        "aspect_ratio": request.ratio,
        "sound": "on" if request.generate_audio else "off",
        "cfg_scale": 0.5,
    }
    if image_inputs:
        payload.update(image_inputs)
        payload.pop("aspect_ratio")
    await jobs.record_provider_request(job, payload)
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap_kling(response.json())
    task_id = str(created.get("task_id") or "")
    if not task_id:
        raise ProviderError("Kling 提交成功但未返回 task_id")
    await jobs.set_provider_task(job, "yinghe-kling", task_id, idempotency_key=job.idempotency_key)
    return await _store_kling_result(job, await _poll_kling(base, headers, job))


def _wan_media(request: VideoGenerationCreate) -> list[dict[str, str]]:
    images = [url.strip() for url in request.image_urls if url.strip()]
    videos = [url.strip() for url in request.video_urls if url.strip()]
    audios = [url.strip() for url in request.audio_urls if url.strip()]
    if request.h3_mode == "first_frame":
        return [{"type": "first_frame", "url": images[0]}] if images else []
    if request.h3_mode == "first_last":
        return [{"type": "first_frame" if index == 0 else "last_frame", "url": url} for index, url in enumerate(images[:2])]
    return [
        *({"type": "reference_image", "url": url} for url in images),
        *({"type": "reference_video", "url": url} for url in videos),
        *({"type": "reference_audio", "url": url} for url in audios),
    ]


async def _query_wan_task(base: str, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{base}/video/generation/tasks/{task_id}", headers=headers)
        _raise_for_status(response)
        return _unwrap(response.json())


async def _poll_wan(base: str, headers: dict[str, str], job: Job) -> dict[str, Any]:
    return await _poll_scheduled(
        f"{base}/video/generation/tasks/{job.provider_task_id}",
        headers,
        job,
        timeout_seconds=_remaining_video_job_timeout(job),
        timeout_error="视频生成超过20分钟，已判定失败，请重新生成",
    )


async def _store_wan_result(job: Job, task: dict[str, Any]) -> dict[str, Any]:
    source_url = str(task.get("resultUrl") or "")
    if not source_url:
        raise ProviderError("Wan 生成成功但未返回视频地址")
    task_id = job.provider_task_id or str(task.get("taskId") or "")
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"wan-{task_id}.mp4")
    thumbnail_url = str(task.get("thumbnailUrl") or "")
    stored_cover, stored_cover_thumbnail = (
        await import_remote_image(thumbnail_url, f"{owner_prefix}/covers") if thumbnail_url else await _video_first_frame(source_url, f"wan-{task_id}", job.user_id)
    )
    request = job.request or {}
    usage = dict(task.get("tokenUsage") or {})
    usage["output_seconds"] = request.get("duration") or 0
    return {
        "provider": "yinghe",
        "providerTaskId": task_id,
        "model": request.get("model") or "wan3.0-video",
        "usage": usage,
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": request.get("duration"),
        "ratio": request.get("ratio"),
    }


async def generate_wan_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _video_config()
    job.idempotency_key = f"{job.id}:wan-native"
    headers["Idempotency-Key"] = job.idempotency_key
    resolution_map = ((job.request or {}).get("_capabilities") or {}).get("providerResolutionMap") or {}
    media = _wan_media(request)
    input_data: dict[str, Any] = {"prompt": request.prompt}
    if media:
        input_data["media"] = media
    payload = {
        "model": str((job.request or {}).get("_providerModelId") or request.model or "wan3.0-video"),
        "input": input_data,
        "parameters": {
            "resolution": str(resolution_map.get(request.resolution) or request.resolution.upper()),
            "ratio": request.ratio,
            "duration": request.duration,
            "audio": request.generate_audio,
            "watermark": request.watermark,
        },
    }
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap(response.json())
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise ProviderError("Wan 提交成功但未返回 taskId")
    await jobs.set_provider_task(job, "yinghe-wan", task_id, idempotency_key=job.idempotency_key)
    return await _store_wan_result(job, await _poll_wan(base, headers, job))


async def _query_happyhorse_task(base: str, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{base}/video/generation/tasks/{task_id}", headers=headers)
        _raise_for_status(response)
        return _unwrap(response.json())


async def _poll_happyhorse(base: str, headers: dict[str, str], job: Job) -> dict[str, Any]:
    return await _poll_scheduled(
        f"{base}/video/generation/tasks/{job.provider_task_id}",
        headers,
        job,
        timeout_seconds=_remaining_video_job_timeout(job),
        timeout_error="HappyHorse 视频生成超过20分钟，已判定失败，请重新生成",
    )


async def _store_happyhorse_result(job: Job, task: dict[str, Any]) -> dict[str, Any]:
    source_url = str(task.get("resultUrl") or "")
    if not source_url:
        raise ProviderError("HappyHorse 生成成功但未返回视频地址")
    task_id = job.provider_task_id or str(task.get("taskId") or "")
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"happyhorse-{task_id}.mp4")
    thumbnail_url = str(task.get("thumbnailUrl") or "")
    stored_cover, stored_cover_thumbnail = (
        await import_remote_image(thumbnail_url, f"{owner_prefix}/covers") if thumbnail_url else await _video_first_frame(source_url, f"happyhorse-{task_id}", job.user_id)
    )
    request = job.request or {}
    usage = dict(task.get("tokenUsage") or {})
    return {
        "provider": "yinghe",
        "providerTaskId": task_id,
        "model": request.get("model") or request.get("_providerModelId") or "happyhorse-1.1-t2v",
        "usage": usage,
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": request.get("duration"),
        "ratio": request.get("ratio"),
        "generationMode": str(request.get("_providerModelId") or "").rsplit("-", 1)[-1],
    }


async def generate_happyhorse_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _video_config()
    model = str((job.request or {}).get("_providerModelId") or request.model or "")
    images = [url.strip() for url in request.image_urls if url.strip()]
    input_data: dict[str, Any] = {"prompt": request.prompt}
    if model.endswith("-t2v"):
        if images:
            raise ProviderRejectedError("HappyHorse 文生视频不支持参考图片")
    elif model.endswith("-i2v"):
        if len(images) != 1:
            raise ProviderRejectedError("HappyHorse 图生视频必须且只能提供 1 张首帧图片")
        input_data["media"] = [{"type": "first_frame", "url": images[0]}]
    elif model.endswith("-r2v"):
        if not 1 <= len(images) <= 9:
            raise ProviderRejectedError("HappyHorse 参考生视频必须提供 1–9 张参考图片")
        input_data["media"] = [{"type": "reference_image", "url": url} for url in images]
    else:
        raise ProviderRejectedError(f"不支持的 HappyHorse 模型：{model}")

    resolution_map = ((job.request or {}).get("_capabilities") or {}).get("providerResolutionMap") or {}
    parameters: dict[str, Any] = {
        "resolution": str(resolution_map.get(request.resolution) or request.resolution.upper()),
        "duration": int(request.duration),
        "watermark": request.watermark,
    }
    # 首帧图生的画幅由输入图片决定，供应商明确不接受 ratio。
    if not model.endswith("-i2v"):
        parameters["ratio"] = request.ratio
    payload = {"model": model, "input": input_data, "parameters": parameters}
    job.idempotency_key = f"{job.id}:happyhorse:{model.rsplit('-', 1)[-1]}"
    headers.update({"Idempotency-Key": job.idempotency_key, "X-DashScope-Async": "enable"})
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap(response.json())
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise ProviderError("HappyHorse 提交成功但未返回 taskId")
    await jobs.set_provider_task(job, "yinghe-happyhorse", task_id, idempotency_key=job.idempotency_key)
    return await _store_happyhorse_result(job, await _poll_happyhorse(base, headers, job))


async def _post_idempotent_video_create(
    client: httpx.AsyncClient,
    url: str,
    *,
    headers: dict[str, str],
    payload: dict[str, Any],
    job: Job,
    provider: str,
) -> httpx.Response:
    """Retry one uncertain Seedance create with the exact same idempotency key and body."""
    for submit_index in range(2):
        try:
            response = await client.post(url, headers=headers, json=payload)
            if submit_index:
                await jobs.record_provider_attempt(
                    job,
                    stage="create",
                    outcome="idempotent_recovered",
                    detail=f"{provider} 创建接口第二次返回确定结果",
                )
            return response
        except httpx.RequestError as exc:
            final = submit_index == 1
            await jobs.record_provider_attempt(
                job,
                stage="create",
                outcome="uncertain_failed" if final else "uncertain_retrying",
                detail=f"{type(exc).__name__}: {exc}",
                increment=not final,
            )
            if final:
                raise ProviderSubmissionUncertainError(f"{provider} 创建接口连续两次未返回确定结果（{type(exc).__name__}）") from exc
            await asyncio.sleep(1)
    raise AssertionError("unreachable")


def _direct_h3_content(request: VideoGenerationCreate, mode: str) -> list[dict[str, Any]]:
    content: list[dict[str, Any]] = [{"type": "text", "text": request.prompt}]
    for index, url in enumerate(request.image_urls):
        role = "reference_image"
        if mode == "first_frame":
            role = "first_frame"
        elif mode == "first_last":
            role = "first_frame" if index == 0 else "last_frame"
        content.append({"type": "image_url", "role": role, "image_url": {"url": url}})
    content.extend({"type": "video_url", "role": "reference_video", "video_url": {"url": url}} for url in request.video_urls)
    content.extend({"type": "audio_url", "role": "reference_audio", "audio_url": {"url": url}} for url in request.audio_urls)
    return content


async def _poll_direct_h3(base: str, headers: dict[str, str], job: Job) -> dict[str, Any]:
    deadline = time.monotonic() + _remaining_video_job_timeout(job)
    consecutive_errors = 0
    async with httpx.AsyncClient(timeout=60) as client:
        while time.monotonic() < deadline:
            await asyncio.sleep(H3_POLL_INTERVAL_SECONDS)
            try:
                response = await client.get(f"{base}/video/generation/tasks/{job.provider_task_id}", headers=headers)
                _raise_for_status(response)
                body = _unwrap(response.json())
                task = body.get("task") if isinstance(body.get("task"), dict) else body
            except (httpx.HTTPError, ValueError, ProviderError) as exc:
                consecutive_errors += 1
                if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                    raise ProviderError(f"H3 状态查询连续失败：{exc}") from exc
                continue
            consecutive_errors = 0
            status = str(task.get("status") or "").lower()
            await jobs.update_progress(job, job.progress + 3)
            if status == "succeeded":
                return task
            if status in {"failed", "cancelled"}:
                reason = task.get("error") or task.get("message") or f"H3 生成任务状态：{status}"
                raise ProviderError(f"H3 生成失败：{reason}")
    raise ProviderError("视频生成超过20分钟，已判定失败，请重新生成")


async def generate_direct_h3_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _video_config()
    mode = str((job.request or {}).get("_h3Mode") or request.h3_mode)
    if mode == "auto":
        mode = "reference" if request.image_urls or request.video_urls or request.audio_urls else "text"
    job.idempotency_key = f"{job.id}:h3:{mode}"
    headers["Idempotency-Key"] = job.idempotency_key
    resolution_map = ((job.request or {}).get("_capabilities") or {}).get("providerResolutionMap") or {}
    provider_resolution = str(resolution_map.get(request.resolution) or ("2K" if request.resolution == "1080p" else "768P"))
    payload = {
        "model": str((job.request or {}).get("_providerModelId") or "MiniMax-H3"),
        "content": _direct_h3_content(request, mode),
        "resolution": provider_resolution,
        "duration": request.duration,
        "ratio": request.ratio,
        "aigc_watermark": request.watermark,
    }
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap(response.json())
    task_id = str(created.get("task_id") or "")
    if not task_id:
        raise ProviderError("H3 提交成功但未返回 task_id")
    await jobs.set_provider_task(job, "yinghe-h3", task_id, idempotency_key=job.idempotency_key)
    return await _store_direct_h3_result(job, await _poll_direct_h3(base, headers, job))


async def _store_direct_h3_result(job: Job, task: dict[str, Any]) -> dict[str, Any]:
    content = task.get("content") if isinstance(task.get("content"), dict) else {}
    source_url = str(content.get("url") or "")
    if not source_url:
        raise ProviderError("H3 生成成功但未返回视频地址")
    task_id = job.provider_task_id or str(task.get("id") or "")
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await _archive_h3_video_to_tos(source_url, f"{owner_prefix}/videos", f"h3-{task_id}.mp4")
    stored_cover, stored_cover_thumbnail = await _video_first_frame(source_url, f"h3-{task_id}", job.user_id)
    request = job.request or {}
    return {
        "provider": "yinghe-h3",
        "providerTaskId": task_id,
        "model": request.get("model") or "minimax-h3",
        "usage": task.get("usage") or {},
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": task.get("duration") or request.get("duration"),
        "ratio": task.get("ratio") or request.get("ratio"),
    }


async def _archive_h3_video_to_tos(source_url: str, owner_prefix: str, filename: str) -> str:
    """Archive a completed H3 result while preserving the failing pipeline stage in user-facing errors."""
    try:
        return await import_remote(source_url, owner_prefix, filename)
    except ValueError as exc:
        raise ProviderError(f"H3 已生成成功，但归档到 TOS 失败：供应商视频地址未通过下载安全校验（{exc}）") from exc


async def generate_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    validate_media_job_source(job)
    if (job.request or {}).get("_provider") == "runninghub":
        return await generate_h3_video(request, job)
    if (job.request or {}).get("_providerModelId") == "MiniMax-H3":
        return await generate_direct_h3_video(request, job)
    if ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "wan-native":
        return await generate_wan_video(request, job)
    if ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "kling-native":
        return await generate_kling_video(request, job)
    if ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "happyhorse-native":
        return await generate_happyhorse_video(request, job)
    if ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "veo-unified":
        return await generate_veo_video(request, job)
    if ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "gemini-omni-unified":
        return await generate_gemini_omni_video(request, job)
    if ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "grok-toapis":
        return await generate_toapis_grok_video(request, job)
    if ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "viduq3-toapis":
        return await generate_toapis_viduq3_video(request, job)
    task_id, created, base, headers = await _submit_seedance_video(request, job, request.image_urls)
    try:
        data = await _poll_scheduled(
            f"{base}/v3/video/tasks/{task_id}",
            headers,
            job,
            timeout_seconds=_remaining_video_job_timeout(job),
            timeout_error="视频生成超过20分钟，已判定失败，请重新生成",
        )
    except ProviderError as exc:
        message = str(exc)
        output_sensitive = bool(
            re.search(
                r"output video may contain sensitive information|内容未通过平台安全合规校验",
                message,
                re.IGNORECASE,
            )
        )
        allow_safety_retry = bool((job.request or {}).get("_allowContentSafetyRetry"))
        safety_retry_attempted = bool((job.request or {}).get("_contentSafetyRetry"))
        if allow_safety_retry and not safety_retry_attempted and output_sensitive:
            retry_prompt = compile_content_safety_retry_prompt(
                request.prompt,
                shot_type=str((job.request or {}).get("_shotType") or "character"),
                shot_index=int((job.request or {}).get("_shotIndex") or 0),
            )
            job.request = {
                **(job.request or {}),
                "_contentSafetyRetry": True,
                "_contentSafetyRetryPrompt": retry_prompt,
            }
            await jobs.record_provider_attempt(
                job,
                stage="result_moderation",
                outcome="content_safety_retrying",
                detail=message,
                provider_task_id=task_id,
                increment=True,
            )
            retry_request = request.model_copy(update={"prompt": retry_prompt})
            task_id, created, base, headers = await _submit_seedance_video(retry_request, job, retry_request.image_urls)
            try:
                data = await _poll_scheduled(
                    f"{base}/v3/video/tasks/{task_id}",
                    headers,
                    job,
                    timeout_seconds=_remaining_video_job_timeout(job),
                    timeout_error="视频生成超过20分钟，已判定失败，请重新生成",
                )
                result = await _store_video_result(job, task_id, data, created)
            except Exception as retry_exc:
                await jobs.record_provider_attempt(
                    job,
                    stage="result_moderation",
                    outcome="content_safety_retry_failed",
                    detail=str(retry_exc),
                    provider_task_id=task_id,
                )
                raise
            await jobs.record_provider_attempt(
                job,
                stage="result_moderation",
                outcome="content_safety_recovered",
                provider_task_id=task_id,
            )
            result["contentSafetyRetry"] = True
            result["contentSafetyRetryReason"] = "provider-output-moderation"
            return result
        allow_fallback = bool((job.request or {}).get("_generalCharacterTextFallback"))
        real_person_blocked = "疑似包含真实人物" in message or bool(re.search(r"may contain real person", message, re.IGNORECASE))
        if not (allow_fallback and request.image_urls and real_person_blocked):
            raise
        # 通用人物镜不要求跨镜身份一致。若 AI 场景首帧被上游误判为
        # 真人参考，安全降级为纯文本视频，避免整条全量任务被阻断。
        task_id, created, base, headers = await _submit_seedance_video(request, job, [])
        data = await _poll_scheduled(
            f"{base}/v3/video/tasks/{task_id}",
            headers,
            job,
            timeout_seconds=_remaining_video_job_timeout(job),
            timeout_error="视频生成超过20分钟，已判定失败，请重新生成",
        )
        result = await _store_video_result(job, task_id, data, created)
        result["referenceFallback"] = "text-to-video-real-person-policy"
        return result
    return await _store_video_result(job, task_id, data, created)


def _unwrap_yseeai_unified(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ProviderRejectedError("英和海外返回了无法解析的响应")
    code = body.get("code")
    if code not in (None, 0, 200, "0", "200"):
        message = _provider_error_message(body) or "英和海外返回错误"
        raise ProviderRejectedError(f"{translate_provider_error(message)}；供应商响应：{_provider_error_body(body)}")
    data = body.get("data")
    return data if isinstance(data, dict) else body


async def _query_gemini_omni_task(base: str, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{base}/video/generation/tasks/{task_id}", headers=headers)
        _raise_for_status(response)
        data = _unwrap_yseeai_unified(response.json())
        return data.get("task") if isinstance(data.get("task"), dict) else data


async def _poll_gemini_omni(base: str, headers: dict[str, str], job: Job) -> dict[str, Any]:
    deadline = time.monotonic() + _remaining_video_job_timeout(job)
    consecutive_errors = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(H3_POLL_INTERVAL_SECONDS)
        try:
            task = await _query_gemini_omni_task(base, headers, job.provider_task_id or "")
        except (httpx.HTTPError, ValueError, ProviderError) as exc:
            consecutive_errors += 1
            if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                raise ProviderError(f"英和海外视频状态查询连续失败：{exc}") from exc
            continue
        consecutive_errors = 0
        status = str(task.get("status") or task.get("task_status") or task.get("state") or "").lower()
        await jobs.update_progress(job, int(task.get("progress") or job.progress + 3))
        if status in {"succeed", "succeeded", "success", "completed", "done"}:
            return task
        if status in {"failed", "fail", "cancelled", "canceled", "error"}:
            error = task.get("error") if isinstance(task.get("error"), dict) else {}
            reason = task.get("failReason") or task.get("message") or error.get("message") or f"任务状态：{status}"
            raise ProviderError(f"英和海外视频生成失败：{translate_provider_error(str(reason))}")
    raise ProviderError("视频生成超过20分钟，已判定失败，请重新生成")


def _gemini_omni_video_url(task: dict[str, Any]) -> str:
    candidates: list[Any] = [
        task.get("video_url"),
        task.get("videoUrl"),
        task.get("result_url"),
        task.get("resultUrl"),
    ]
    for key in ("content", "result", "output", "task_result"):
        value = task.get(key)
        if isinstance(value, dict):
            candidates.extend((value.get("video_url"), value.get("videoUrl"), value.get("url")))
            videos = value.get("videos")
            if isinstance(videos, list):
                candidates.extend(item.get("url") for item in videos if isinstance(item, dict))
    for key in ("results", "videos", "resultUrls"):
        value = task.get(key)
        if isinstance(value, list):
            candidates.extend(item.get("url") if isinstance(item, dict) else item for item in value)
    return next((str(value) for value in candidates if isinstance(value, str) and value.strip()), "")


async def _store_gemini_omni_result(job: Job, task: dict[str, Any]) -> dict[str, Any]:
    source_url = _gemini_omni_video_url(task)
    if not source_url:
        raise ProviderError("英和海外视频生成成功但未返回视频地址")
    task_id = job.provider_task_id or str(task.get("task_id") or task.get("taskId") or task.get("id") or "")
    owner_prefix = f"users/{job.user_id}/generated"
    model = str((job.request or {}).get("model") or "gemini-omni-flash-preview")
    safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "-", model).strip("-")
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"{safe_model}-{task_id}.mp4")
    stored_cover, stored_cover_thumbnail = await _video_first_frame(source_url, f"{safe_model}-{task_id}", job.user_id)
    request = job.request or {}
    usage = dict(task.get("usage") or {})
    usage.setdefault("output_seconds", request.get("duration") or 0)
    return {
        "provider": "yseeai",
        "providerTaskId": task_id,
        "model": model,
        "usage": usage,
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": task.get("duration") or request.get("duration"),
        "ratio": request.get("ratio"),
    }


async def _gemini_omni_image_data_url(url: str) -> str:
    if url.startswith("data:image/"):
        return url
    # Use the shared downloader's public-IP and redirect checks, with a bounded image size.
    _resolved_url, content, _content_type = await download_public_url(url, max_bytes=20 * 1024 * 1024)
    try:
        with Image.open(io.BytesIO(content)) as image:
            mime = Image.MIME.get(image.format or "")
            image.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ProviderError("Gemini Omni 参考图片无法解析，请检查原图") from exc
    if not mime or not mime.startswith("image/"):
        raise ProviderError("Gemini Omni 参考素材必须是图片")
    return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


async def generate_gemini_omni_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _yseeai_config()
    images = [url.strip() for url in request.image_urls if url.strip()]
    identity_reference = bool((job.request or {}).get("_identityReferenceIndices"))
    task = "text_to_video" if not images else "image_to_video" if len(images) == 1 and not identity_reference else "reference_to_video"
    job.idempotency_key = f"{job.id}:gemini-omni:{task}"
    headers["Idempotency-Key"] = job.idempotency_key
    payload: dict[str, Any] = {
        "model": str((job.request or {}).get("_providerModelId") or "gemini-omni-flash-preview"),
        "prompt": request.prompt,
        "duration": request.duration,
        "metadata": {"aspect_ratio": request.ratio, "task": task},
    }
    if images:
        payload["images"] = images if model_gateway.routed("yseeai") else [await _gemini_omni_image_data_url(url) for url in images]
    await jobs.record_provider_request(job, payload)
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap_yseeai_unified(response.json())
    task_id = str(created.get("task_id") or created.get("taskId") or created.get("id") or created.get("interaction_id") or "")
    if not task_id:
        raise ProviderError("Gemini Omni 提交成功但未返回任务 ID")
    await jobs.set_provider_task(job, "yseeai-omni", task_id, idempotency_key=job.idempotency_key)
    return await _store_gemini_omni_result(job, await _poll_gemini_omni(base, headers, job))


def _veo_size(ratio: str, resolution: str) -> str:
    sizes = {
        ("16:9", "720p"): "1280x720",
        ("9:16", "720p"): "720x1280",
        ("16:9", "1080p"): "1920x1080",
        ("9:16", "1080p"): "1080x1920",
        ("16:9", "4k"): "3840x2160",
        ("9:16", "4k"): "2160x3840",
    }
    return sizes.get((ratio, resolution), sizes[("16:9", "720p")])


async def generate_veo_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _yseeai_config()
    images = [url.strip() for url in request.image_urls if url.strip()]
    variant = "image" if images else "text"
    job.idempotency_key = f"{job.id}:veo-unified:{variant}"
    headers["Idempotency-Key"] = job.idempotency_key
    payload: dict[str, Any] = {
        "model": str((job.request or {}).get("_providerModelId") or request.model),
        "prompt": request.prompt,
        "duration": request.duration,
        "size": _veo_size(request.ratio, request.resolution),
        "resolution": request.resolution,
        "metadata": {"aspectRatio": request.ratio, "resolution": request.resolution},
    }
    if images:
        payload["images"] = images
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/video/generation/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap_yseeai_unified(response.json())
    task_id = str(created.get("task_id") or created.get("taskId") or created.get("id") or created.get("interaction_id") or "")
    if not task_id:
        raise ProviderError("Veo 提交成功但未返回任务 ID")
    await jobs.set_provider_task(job, "yseeai-unified", task_id, idempotency_key=job.idempotency_key)
    return await _store_gemini_omni_result(job, await _poll_gemini_omni(base, headers, job))


async def _query_toapis_video_task(base: str, headers: dict[str, str], task_id: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(f"{base}/v1/videos/generations/{task_id}", headers=headers)
        _raise_for_status(response)
        body = response.json()
    if not isinstance(body, dict):
        raise ProviderError("ToAPIs 返回了无法解析的任务状态")
    return body


async def _poll_toapis_video(base: str, headers: dict[str, str], job: Job) -> dict[str, Any]:
    deadline = time.monotonic() + _remaining_video_job_timeout(job)
    consecutive_errors = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(H3_POLL_INTERVAL_SECONDS)
        try:
            task = await _query_toapis_video_task(base, headers, job.provider_task_id or "")
        except (httpx.HTTPError, ValueError, ProviderError) as exc:
            consecutive_errors += 1
            if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                raise ProviderError(f"ToAPIs 状态查询连续失败：{exc}") from exc
            continue
        consecutive_errors = 0
        status = str(task.get("status") or "").lower()
        await jobs.update_progress(job, int(task.get("progress") or job.progress + 3))
        if status == "completed":
            # ToAPIs 的成片与费用结算可能相差数秒；短暂补查，确保对账保留已确认费用。
            for _ in range(3):
                billing = task.get("billing") if isinstance(task.get("billing"), dict) else {}
                if billing.get("status") in {"settled", "refunded"}:
                    break
                await asyncio.sleep(2)
                task = await _query_toapis_video_task(base, headers, job.provider_task_id or "")
            return task
        if status == "failed":
            error = task.get("error") if isinstance(task.get("error"), dict) else {}
            reason = error.get("message") or task.get("message") or "供应商未返回失败原因"
            model = str((job.request or {}).get("model") or "ToAPIs 视频")
            raise ProviderError(f"{model} 生成失败：{translate_provider_error(str(reason))}；供应商响应：{_provider_error_body(task)}")
    raise ProviderError("视频生成超过20分钟，已判定失败，请重新生成")


async def _store_toapis_video_result(job: Job, task: dict[str, Any]) -> dict[str, Any]:
    result = task.get("result") if isinstance(task.get("result"), dict) else {}
    data = result.get("data") if isinstance(result.get("data"), list) else []
    output = next((item for item in data if isinstance(item, dict) and item.get("url")), None)
    if not output:
        model = str((job.request or {}).get("model") or "ToAPIs 视频")
        raise ProviderError(f"{model} 生成成功但未返回视频地址")
    task_id = job.provider_task_id or str(task.get("id") or "")
    source_url = str(output["url"])
    owner_prefix = f"users/{job.user_id}/generated"
    request = job.request or {}
    model = str(request.get("model") or "toapis-video")
    safe_model = re.sub(r"[^a-zA-Z0-9._-]+", "-", model)
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"{safe_model}-{task_id}.mp4")
    stored_cover, stored_cover_thumbnail = await _video_first_frame(source_url, f"{safe_model}-{task_id}", job.user_id)
    billing = task.get("billing") if isinstance(task.get("billing"), dict) else {}
    usage = dict(task.get("usage") or {})
    usage.setdefault("output_seconds", request.get("duration") or 0)
    if billing:
        usage["billing"] = billing
    return {
        "provider": "toapis",
        "providerTaskId": task_id,
        "model": request.get("model") or "grok-video-1.5",
        "usage": usage,
        "billing": billing,
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": request.get("duration"),
        "ratio": request.get("ratio"),
    }


async def generate_toapis_grok_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _toapis_config()
    images = [url.strip() for url in request.image_urls if url.strip()]
    mode = "text_to_video" if not images else "first_frame_image_to_video" if len(images) == 1 else "reference_images_to_video"
    job.idempotency_key = f"{job.id}:grok-video-1.5:{mode}"
    headers["Idempotency-Key"] = job.idempotency_key
    payload: dict[str, Any] = {
        "model": "grok-video-1.5",
        "prompt": request.prompt,
        "video_generation_mode": mode,
        "duration": request.duration,
        "resolution": request.resolution,
        "aspect_ratio": request.ratio,
        "client_business_id": job.id,
    }
    if len(images) == 1:
        payload["image"] = images[0]
    elif images:
        payload["reference_images"] = images
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/v1/videos/generations", headers=headers, json=payload)
        _raise_for_status(response)
        created = response.json()
    task_id = str(created.get("id") or "") if isinstance(created, dict) else ""
    if not task_id:
        raise ProviderError(f"Grok Video 1.5 提交成功但未返回任务 ID；供应商响应：{_provider_error_body(created)}")
    await jobs.set_provider_task(job, "toapis-grok", task_id, idempotency_key=job.idempotency_key)
    return await _store_toapis_video_result(job, await _poll_toapis_video(base, headers, job))


async def generate_toapis_viduq3_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    base, headers = _toapis_config()
    model = str((job.request or {}).get("_providerModelId") or request.model)
    if model not in {"viduq3-pro", "viduq3-turbo", "viduq3"}:
        raise ProviderError(f"不支持的 Vidu Q3 模型：{model}")
    images = [url.strip() for url in request.image_urls if url.strip()]
    max_images = 7 if model == "viduq3" else 2
    if model == "viduq3" and not images:
        raise ProviderError("Vidu Q3 参考生视频至少需要 1 张参考图")
    if len(images) > max_images:
        raise ProviderError(f"{model} 最多支持 {max_images} 张参考图")
    if model == "viduq3" and request.resolution == "540p":
        raise ProviderError("Vidu Q3 参考生视频仅支持 720p 或 1080p")
    job.idempotency_key = f"{job.id}:viduq3:{model}"
    headers["Idempotency-Key"] = job.idempotency_key
    payload: dict[str, Any] = {
        "model": model,
        "prompt": request.prompt,
        "duration": request.duration,
        "resolution": request.resolution,
        "audio": request.generate_audio,
        "client_business_id": job.id,
    }
    if images:
        payload["image_urls"] = images
    else:
        payload["aspect_ratio"] = request.ratio
    await jobs.mark_provider_submitting(job)
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/v1/videos/generations", headers=headers, json=payload)
        _raise_for_status(response)
        created = response.json()
    task_id = str(created.get("id") or created.get("task_id") or "") if isinstance(created, dict) else ""
    if not task_id:
        raise ProviderError(f"{model} 提交成功但未返回任务 ID；供应商响应：{_provider_error_body(created)}")
    await jobs.set_provider_task(job, "toapis-viduq3", task_id, idempotency_key=job.idempotency_key)
    return await _store_toapis_video_result(job, await _poll_toapis_video(base, headers, job))


def _h3_aspect_ratio(ratio: str) -> str:
    return {
        "16:9": "16:9 (Widescreen)",
        "9:16": "9:16 (Portrait)",
        "1:1": "1:1 (Square)",
        "4:3": "4:3 (Classic)",
    }.get(ratio, "16:9 (Widescreen)")


def _h3_first_frame_aspect_ratio(ratio: str) -> str:
    return {
        "16:9": "16:9 (Widescreen)",
        "9:16": "9:16 (Portrait Widescreen)",
        "1:1": "1:1 (Square)",
        "4:3": "4:3 (Classic)",
    }.get(ratio, "16:9 (Widescreen)")


def _h3_megapixels(resolution: str, capabilities: dict[str, Any] | None = None) -> tuple[float, float]:
    configured = (capabilities or {}).get("providerResolutionMap") or {}
    item = configured.get(resolution)
    if isinstance(item, dict) and item.get("stage1") is not None and item.get("stage2") is not None:
        return float(item["stage1"]), float(item["stage2"])
    return {
        "480p": (0.2, 0.4),
        "720p": (0.4, 0.9),
        "1080p": (0.9, 1.8),
    }.get(resolution, (0.4, 0.9))


async def _poll_runninghub(job: Job) -> dict[str, Any]:
    deadline = time.monotonic() + _remaining_video_job_timeout(job)
    consecutive_errors = 0
    while time.monotonic() < deadline:
        await asyncio.sleep(H3_POLL_INTERVAL_SECONDS)
        try:
            data = await runninghub_query_task(job.provider_task_id or "")
        except RunningHubError as exc:
            consecutive_errors += 1
            if consecutive_errors >= POLL_MAX_CONSECUTIVE_ERRORS:
                raise ProviderError(f"RunningHub 状态查询连续失败：{exc}") from exc
            continue
        consecutive_errors = 0
        status = str(data.get("status") or "").upper()
        await jobs.update_progress(job, job.progress + 3)
        if status == "SUCCESS":
            return data
        if status in {"FAILED", "CANCELLED"} or "FAIL" in status:
            reason = data.get("errorMessage") or data.get("failedReason") or f"H3 生成任务状态：{status}"
            raise ProviderError(f"H3 生成失败：{reason}")
    raise ProviderError("视频生成超过20分钟，已判定失败，请重新生成")


async def _h3_media_duration(content: bytes, suffix: str) -> float:
    with tempfile.NamedTemporaryFile(suffix=suffix or ".bin") as handle:
        handle.write(content)
        handle.flush()
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            handle.name,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
    if process.returncode != 0:
        raise ProviderError(f"H3 参考媒体无法读取时长：{stderr.decode(errors='ignore')[:200]}")
    try:
        return float(stdout.decode().strip())
    except ValueError as exc:
        raise ProviderError("H3 参考媒体未返回有效时长") from exc


async def _upload_h3_reference(url: str, kind: str, index: int) -> tuple[str, float | None]:
    try:
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ProviderError(f"H3 参考{kind}下载失败：{exc}") from exc
    content = response.content
    if len(content) > H3_REFERENCE_FILE_MAX_BYTES:
        raise ProviderError(f"H3 单个参考{kind}不能超过 100MB")
    suffix = Path(urlparse(url).path).suffix.lower() or {"图片": ".png", "视频": ".mp4", "音频": ".wav"}[kind]
    media_duration = await _h3_media_duration(content, suffix) if kind in {"视频", "音频"} else None
    uploaded = await runninghub_upload_media(content, f"h3-{kind}-{index}{suffix}")
    file_name = str(uploaded.get("fileName") or "")
    if not file_name:
        raise ProviderError(f"H3 参考{kind}上传成功但未返回文件名")
    return file_name, media_duration


def _validate_h3_reference_durations(kind: str, durations: list[float]) -> None:
    for value in durations:
        if not 2 <= value <= 15:
            raise ProviderError(f"H3 每段参考{kind}时长必须为 2–15 秒，检测到 {value:.2f} 秒")
    if sum(durations) > 15.05:
        raise ProviderError(f"H3 参考{kind}总时长不能超过 15 秒，当前为 {sum(durations):.2f} 秒")


async def generate_h3_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    images = [url.strip() for url in request.image_urls if url.strip()]
    videos = [url.strip() for url in request.video_urls if url.strip()]
    audios = [url.strip() for url in request.audio_urls if url.strip()]
    mode = str((job.request or {}).get("_h3Mode") or request.h3_mode)
    if mode == "auto":
        mode = "reference" if images or videos or audios else "text"
    stage1, stage2 = _h3_megapixels(request.resolution, ((job.request or {}).get("_capabilities") or {}))
    try:
        if mode == "text":
            await jobs.mark_provider_submitting(job)
            created = await runninghub_submit_text_task(
                prompt=request.prompt,
                duration=float(request.duration),
                aspect_ratio=_h3_first_frame_aspect_ratio(request.ratio),
                megapixels=stage2,
                generate_audio=request.generate_audio,
            )
        elif mode == "first_frame":
            if len(images) != 1 or videos or audios:
                raise ProviderError("H3 首帧模式必须且只能提供 1 张图片")
            image_name, _ = await _upload_h3_reference(images[0], "图片", 1)
            await jobs.mark_provider_submitting(job)
            created = await runninghub_submit_first_frame_task(
                prompt=request.prompt,
                duration=float(request.duration),
                aspect_ratio=_h3_first_frame_aspect_ratio(request.ratio),
                image=image_name,
                megapixels=stage2,
                generate_audio=request.generate_audio,
            )
        elif mode == "first_last":
            if len(images) != 2 or videos or audios:
                raise ProviderError("H3 首尾帧模式必须且只能提供首帧、尾帧两张图片")
            uploaded = [await _upload_h3_reference(url, "图片", index) for index, url in enumerate(images, 1)]
            await jobs.mark_provider_submitting(job)
            created = await runninghub_submit_first_last_frame_task(
                prompt=request.prompt,
                duration=float(request.duration),
                aspect_ratio=_h3_first_frame_aspect_ratio(request.ratio),
                first_image=uploaded[0][0],
                last_image=uploaded[1][0],
                megapixels=stage2,
                generate_audio=request.generate_audio,
            )
        else:
            if audios and not (images or videos):
                raise ProviderError("H3 Ref2VA 音频不能作为唯一输入，必须同时提供图片或视频")
            image_uploads = [await _upload_h3_reference(url, "图片", index) for index, url in enumerate(images, 1)]
            video_uploads = [await _upload_h3_reference(url, "视频", index) for index, url in enumerate(videos, 1)]
            audio_uploads = [await _upload_h3_reference(url, "音频", index) for index, url in enumerate(audios, 1)]
            _validate_h3_reference_durations("视频", [duration for _, duration in video_uploads if duration is not None])
            _validate_h3_reference_durations("音频", [duration for _, duration in audio_uploads if duration is not None])
            await jobs.mark_provider_submitting(job)
            created = await runninghub_submit_reference_task(
                prompt=request.prompt,
                duration=float(request.duration),
                aspect_ratio=_h3_aspect_ratio(request.ratio),
                images=[name for name, _ in image_uploads],
                videos=[name for name, _ in video_uploads],
                audios=[name for name, _ in audio_uploads],
                stage1_megapixels=stage1,
                stage2_megapixels=stage2,
                generate_audio=request.generate_audio,
            )
    except RunningHubError as exc:
        raise ProviderError(f"H3 提交失败：{exc}") from exc
    task_id = str(created.get("taskId") or "")
    if not task_id:
        raise ProviderError("H3 提交成功但未返回 taskId")
    await jobs.set_provider_task(job, "runninghub", task_id)
    return await _store_h3_video_result(job, await _poll_runninghub(job))


async def _store_h3_video_result(job: Job, data: dict[str, Any]) -> dict[str, Any]:
    outputs = [item for item in (data.get("results") or []) if item.get("url")]
    output = next((item for item in outputs if str(item.get("outputType") or "").lower() == "mp4"), outputs[0] if outputs else None)
    if not output:
        raise ProviderError("H3 生成成功但未返回视频地址")
    task_id = job.provider_task_id or str(data.get("taskId") or "")
    source_url = str(output["url"])
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await _archive_h3_video_to_tos(source_url, f"{owner_prefix}/videos", f"h3-{task_id}.mp4")
    stored_cover, stored_cover_thumbnail = await _video_first_frame(source_url, f"h3-{task_id}", job.user_id)
    request = job.request or {}
    generation_mode = request.get("_h3Mode")
    if not generation_mode:
        generation_mode = "reference" if request.get("image_urls") or request.get("video_urls") or request.get("audio_urls") else "text"
    return {
        "provider": "runninghub",
        "providerTaskId": task_id,
        "model": request.get("model") or "minimax-h3-runninghub",
        "usage": data.get("usage") or {},
        "videoUrl": stored_url,
        "coverUrl": stored_cover,
        "coverThumbnailUrl": stored_cover_thumbnail,
        "sourceUrl": source_url,
        "duration": request.get("duration"),
        "ratio": request.get("ratio"),
        "generationMode": generation_mode,
        "promptCompiler": request.get("_promptCompiler"),
        "promptCompilerVersion": request.get("_promptCompilerVersion"),
    }


async def _store_video_result(job: Job, task_id: str, data: dict[str, Any], created: dict[str, Any]) -> dict[str, Any]:
    async with _result_semaphore("video"):
        return await _store_video_result_inner(job, task_id, data, created)


async def _store_video_result_inner(job: Job, task_id: str, data: dict[str, Any], created: dict[str, Any]) -> dict[str, Any]:
    request = job.request or {}
    # V3 Seedance 报文：结果在 content.video_url / content.last_frame_url
    content = data.get("content") if isinstance(data.get("content"), dict) else {}
    source_url = content.get("video_url")
    if not source_url:
        raise ProviderError("视频生成成功但未返回地址")
    owner_prefix = f"users/{job.user_id}/generated"
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"{task_id}.mp4")
    cover_url = content.get("last_frame_url")
    stored_cover, stored_cover_thumbnail = (
        await import_remote_image(cover_url, f"{owner_prefix}/covers") if cover_url else await _video_first_frame(source_url, task_id, job.user_id)
    )
    return {
        "provider": str(request.get("_provider") or "yinghe"),
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
    validate_media_job_source(job)
    if not job.provider_task_id:
        raise ProviderError("缺少供应商任务ID，无法恢复")
    if (job.request or {}).get("_provider") == "runninghub":
        return await _store_h3_video_result(job, await _poll_runninghub(job))
    if job.provider == "yinghe-h3" or (job.request or {}).get("_providerModelId") == "MiniMax-H3":
        base, headers = _video_config()
        return await _store_direct_h3_result(job, await _poll_direct_h3(base, headers, job))
    if job.provider == "yinghe-wan" or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "wan-native":
        base, headers = _video_config()
        return await _store_wan_result(job, await _poll_wan(base, headers, job))
    if job.provider == "yinghe-kling" or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "kling-native":
        base, headers = _video_config()
        return await _store_kling_result(job, await _poll_kling(base, headers, job))
    if job.provider == "yinghe-happyhorse" or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "happyhorse-native":
        base, headers = _video_config()
        return await _store_happyhorse_result(job, await _poll_happyhorse(base, headers, job))
    if job.provider in {"yseeai-omni", "yseeai-unified"} or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") in {"gemini-omni-unified", "veo-unified"}:
        base, headers = _yseeai_config()
        return await _store_gemini_omni_result(job, await _poll_gemini_omni(base, headers, job))
    if job.provider in {"toapis-grok", "toapis-viduq3"} or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") in {"grok-toapis", "viduq3-toapis"}:
        base, headers = _toapis_config()
        return await _store_toapis_video_result(job, await _poll_toapis_video(base, headers, job))
    if job.kind == "image":
        base, headers = _image_config()
        url, timeout = f"{base}/image/generation/tasks/{job.provider_task_id}", IMAGE_POLL_TIMEOUT_SECONDS
        timeout = _remaining_provider_timeout(job, timeout)
        timeout_error = "gpt-image-2 生成超过10分钟，已判定失败"
    elif job.kind == "video":
        base, headers = _video_config()
        url, timeout = f"{base}/v3/video/tasks/{job.provider_task_id}", _remaining_video_job_timeout(job)
        timeout_error = "视频生成超过20分钟，已判定失败，请重新生成"
    else:
        raise ProviderError(f"不支持恢复的任务类型：{job.kind}")
    data = await _poll_scheduled(url, headers, job, timeout_seconds=timeout, timeout_error=timeout_error)
    return await store_provider_result(job, data)


async def query_provider_task(kind: str, task_id: str, provider: str | None = None) -> dict[str, Any]:
    """单次查询供应商任务状态（管理后台对账用）"""
    validate_media_provider(provider)
    if provider == "runninghub":
        try:
            return await runninghub_query_task(task_id)
        except RunningHubError as exc:
            raise ProviderError(f"RunningHub 状态查询失败：{exc}") from exc
    if provider == "yinghe-h3":
        base, headers = _video_config()
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(f"{base}/video/generation/tasks/{task_id}", headers=headers)
            _raise_for_status(response)
            body = _unwrap(response.json())
        return body.get("task") if isinstance(body.get("task"), dict) else body
    if provider == "yinghe-wan":
        base, headers = _video_config()
        return await _query_wan_task(base, headers, task_id)
    if provider == "yinghe-kling":
        base, headers = _video_config()
        return await _query_kling_task(base, headers, task_id)
    if provider == "yinghe-happyhorse":
        base, headers = _video_config()
        return await _query_happyhorse_task(base, headers, task_id)
    if provider in {"yseeai-omni", "yseeai-unified"}:
        base, headers = _yseeai_config()
        return await _query_gemini_omni_task(base, headers, task_id)
    if provider in {"toapis-grok", "toapis-viduq3"}:
        base, headers = _toapis_config()
        return await _query_toapis_video_task(base, headers, task_id)
    if kind == "image":
        base, headers = _image_config()
        url = f"{base}/image/generation/tasks/{task_id}"
    elif kind == "video":
        base, headers = _video_config()
        url = f"{base}/v3/video/tasks/{task_id}"
    else:
        raise ProviderError(f"不支持的任务类型：{kind}")
    async with httpx.AsyncClient(timeout=60) as client:
        return await _query_task(client, url, headers)


async def store_provider_result(job: Job, data: dict[str, Any]) -> dict[str, Any]:
    """供应商成功结果下载落库（重启恢复与对账同步共用）"""
    validate_media_job_source(job)
    if (job.request or {}).get("_provider") == "runninghub":
        return await _store_h3_video_result(job, data)
    if job.provider == "yinghe-h3" or (job.request or {}).get("_providerModelId") == "MiniMax-H3":
        return await _store_direct_h3_result(job, data)
    if job.provider == "yinghe-wan" or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "wan-native":
        return await _store_wan_result(job, data)
    if job.provider == "yinghe-kling" or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "kling-native":
        return await _store_kling_result(job, data)
    if job.provider == "yinghe-happyhorse" or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") == "happyhorse-native":
        return await _store_happyhorse_result(job, data)
    if job.provider in {"yseeai-omni", "yseeai-unified"} or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") in {"gemini-omni-unified", "veo-unified"}:
        return await _store_gemini_omni_result(job, data)
    if job.provider in {"toapis-grok", "toapis-viduq3"} or ((job.request or {}).get("_capabilities") or {}).get("providerProtocol") in {"grok-toapis", "viduq3-toapis"}:
        return await _store_toapis_video_result(job, data)
    task_id = job.provider_task_id or ""
    if job.kind == "image":
        return await _store_image_result(job, task_id, data, {})
    if job.kind == "video":
        return await _store_video_result(job, task_id, data, {})
    raise ProviderError(f"不支持的任务类型：{job.kind}")


async def _video_first_frame(video_url: str, task_id: str, user_id: str | None) -> tuple[str, str]:
    """Extract the default shot cover from the generated video's first frame."""
    with tempfile.TemporaryDirectory(prefix="mvagent-cover-") as temp_dir:
        video_path = Path(temp_dir) / "source.mp4"
        cover_path = Path(temp_dir) / "cover.jpg"
        try:
            await download_public_url_to_path(video_url, video_path)
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"下载视频以提取首帧失败：{exc}") from exc
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
