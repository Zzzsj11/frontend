from __future__ import annotations

import asyncio
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

from .config import settings
from .jobs import Job, jobs
from .runninghub import RunningHubError
from .runninghub import query_task as runninghub_query_task
from .runninghub import submit_first_frame_task as runninghub_submit_first_frame_task
from .runninghub import submit_first_last_frame_task as runninghub_submit_first_last_frame_task
from .runninghub import submit_reference_task as runninghub_submit_reference_task
from .runninghub import submit_text_task as runninghub_submit_text_task
from .runninghub import upload_media as runninghub_upload_media
from .schemas import ImageGenerationCreate, VideoGenerationCreate
from .storage import download_public_url_to_path, import_remote, import_remote_image, put_image_with_thumbnail, safe_key


class ProviderError(RuntimeError):
    pass


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
        re.compile(r"content polic|sensitive content|unsafe content|violat", re.IGNORECASE),
        "内容未通过平台安全合规校验，请调整画面内容或提示词后重试",
    ),
    (
        re.compile(r"invalid (api.?key|token)|unauthorized|permission denied|api key not (found|valid)", re.IGNORECASE),
        "接口密钥无效或未授权，请联系管理员检查 API Key 配置",
    ),
]

_REQUEST_ID_RE = re.compile(r"request\s*id[:\s]*([a-zA-Z0-9\-]+)", re.IGNORECASE)


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
            code = (body.get("data") or {}).get("code", "")
            msg = body.get("msg", "")
        except Exception:
            raise ProviderError(str(exc)) from exc
        friendly = _AIGC_FRIENDLY_ERRORS.get(code)
        if friendly:
            raise ProviderError(friendly) from exc
        if msg:
            raise ProviderError(translate_provider_error(msg)) from exc
        raise ProviderError(str(exc)) from exc


def _headers(api_key: str, *, x_api_key: bool = False) -> dict[str, str]:
    auth = {"x-api-key": api_key} if x_api_key else {"Authorization": f"Bearer {api_key}"}
    return {**auth, "Content-Type": "application/json", "Idempotency-Key": str(uuid.uuid4())}


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    # V3 Seedance 视频任务报文无 code/data 包装（官方格式），原样返回；
    # 素材接口与旧版任务接口均为 code/data 包装，且部分 V3 路由层错误也走包装（HTTP 200 + code=500）
    if "code" not in body:
        return body
    if body.get("code") != 200:
        raise ProviderError(translate_provider_error(body.get("msg") or f"上游接口返回错误：{body.get('code')}"))
    return body.get("data") or {}


def _usage(data: dict[str, Any]) -> dict[str, Any]:
    if isinstance(data.get("usage"), dict):
        return data["usage"]
    keys = ("input_tokens", "inputTokens", "prompt_tokens", "promptTokens", "output_tokens", "outputTokens", "completion_tokens", "completionTokens", "total_tokens", "totalTokens")
    return {key: data[key] for key in keys if key in data}


IMAGE_POLL_TIMEOUT_SECONDS = 360
VIDEO_POLL_TIMEOUT_SECONDS = 900
H3_POLL_INTERVAL_SECONDS = 15
H3_POLL_TIMEOUT_SECONDS = 2400
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

    async def watch(self, url: str, headers: dict[str, str], job: Job, *, timeout_seconds: int) -> dict[str, Any]:
        if job.id in self._entries:
            raise ProviderError(f"生成任务已在轮询：{job.id}")
        future = asyncio.get_running_loop().create_future()
        self._entries[job.id] = _ScheduledPoll(job, url, headers, time.monotonic() + timeout_seconds, future)
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
                        self._finish_error(job_id, ProviderError("生成任务超时，请稍后查询"))
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


async def _poll_scheduled(url: str, headers: dict[str, str], job: Job, *, timeout_seconds: int) -> dict[str, Any]:
    return await _poll_scheduler().watch(url, headers, job, timeout_seconds=timeout_seconds)


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
    data = await _poll_scheduled(f"{base}/image/generation/tasks/{task_id}", headers, job, timeout_seconds=IMAGE_POLL_TIMEOUT_SECONDS)
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


async def generate_video(request: VideoGenerationCreate, job: Job) -> dict[str, Any]:
    if (job.request or {}).get("_provider") == "runninghub":
        return await generate_h3_video(request, job)
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
        # 让上游返回尾帧图做封面，免去本地 ffmpeg 抽帧
        "return_last_frame": True,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/v3/video/tasks", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap(response.json())
        # V3 Seedance 官方报文：任务 ID 字段为 id（旧版为 taskId）
        task_id = created.get("id")
        if not task_id:
            raise ProviderError("视频接口未返回任务 id")
        await jobs.set_provider_task(job, "yinghe", task_id, idempotency_key=headers.get("Idempotency-Key"))
    data = await _poll_scheduled(f"{base}/v3/video/tasks/{task_id}", headers, job, timeout_seconds=VIDEO_POLL_TIMEOUT_SECONDS)
    return await _store_video_result(job, task_id, data, created)


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


def _h3_megapixels(resolution: str) -> tuple[float, float]:
    return {
        "480p": (0.2, 0.4),
        "720p": (0.4, 0.9),
        "1080p": (0.9, 1.8),
    }.get(resolution, (0.4, 0.9))


async def _poll_runninghub(job: Job) -> dict[str, Any]:
    deadline = time.monotonic() + H3_POLL_TIMEOUT_SECONDS
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
    raise ProviderError("H3 生成任务超时，请稍后查询")


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
        mode = "reference" if videos or audios or len(images) > 1 else ("first_frame" if images else "text")
    stage1, stage2 = _h3_megapixels(request.resolution)
    try:
        if mode == "text":
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
    stored_url = await import_remote(source_url, f"{owner_prefix}/videos", f"h3-{task_id}.mp4")
    stored_cover, stored_cover_thumbnail = await _video_first_frame(source_url, f"h3-{task_id}", job.user_id)
    request = job.request or {}
    generation_mode = request.get("_h3Mode")
    if not generation_mode:
        generation_mode = (
            "reference"
            if request.get("video_urls") or request.get("audio_urls") or len(request.get("image_urls") or []) > 1
            else ("first_frame" if request.get("image_urls") else "text")
        )
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
    if (job.request or {}).get("_provider") == "runninghub":
        return await _store_h3_video_result(job, await _poll_runninghub(job))
    if job.kind == "image":
        base, headers = _image_config()
        url, timeout = f"{base}/image/generation/tasks/{job.provider_task_id}", IMAGE_POLL_TIMEOUT_SECONDS
    elif job.kind == "video":
        base, headers = _video_config()
        url, timeout = f"{base}/v3/video/tasks/{job.provider_task_id}", VIDEO_POLL_TIMEOUT_SECONDS
    else:
        raise ProviderError(f"不支持恢复的任务类型：{job.kind}")
    data = await _poll_scheduled(url, headers, job, timeout_seconds=timeout)
    return await store_provider_result(job, data)


async def query_provider_task(kind: str, task_id: str, provider: str | None = None) -> dict[str, Any]:
    """单次查询供应商任务状态（管理后台对账用）"""
    if provider == "runninghub":
        try:
            return await runninghub_query_task(task_id)
        except RunningHubError as exc:
            raise ProviderError(f"RunningHub 状态查询失败：{exc}") from exc
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
    if (job.request or {}).get("_provider") == "runninghub":
        return await _store_h3_video_result(job, data)
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
