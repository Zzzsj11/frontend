from __future__ import annotations

import asyncio
import re
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
POLL_INTERVAL_SECONDS = 30
POLL_MAX_CONSECUTIVE_ERRORS = 5

ASSET_POLL_TIMEOUT_SECONDS = 180
ASSET_POLL_INTERVAL_SECONDS = 3.0


async def create_real_face_asset(public_url: str, *, name: str) -> str:
    """把公开图片注册为 AIGC 平台虚拟资产，轮询至 Active，返回 asset://{id} 链接。

    视频生成传 asset:// 引用的是平台内部已托管素材，可绕过上游对真实人物的直接检测。
    """
    base, headers = _video_config()
    headers["group_id"] = settings.aigc_asset_group_id
    payload = {
        "url": public_url,
        "name": name,
        "assetType": "Image",
        "Moderation": {"Strategy": "Skip"},
    }
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(f"{base}/virtual/assets/create", headers=headers, json=payload)
        # CN region 不支持 Moderation 参数（直接 400）：去掉后降级重试一次，其他区域保持原行为
        if response.status_code == 400 and "Moderation" in response.text and "not supported" in response.text:
            payload.pop("Moderation")
            response = await client.post(f"{base}/virtual/assets/create", headers=headers, json=payload)
        _raise_for_status(response)
        created = _unwrap(response.json())
        asset_id = created.get("id")
        if not asset_id:
            raise ProviderError("虚拟资产接口未返回 asset id")
        deadline = time.monotonic() + ASSET_POLL_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(ASSET_POLL_INTERVAL_SECONDS)
            detail_response = await client.post(f"{base}/virtual/assets/detail", headers=headers, json={"assetId": asset_id})
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
        if status == "SUCCESS":
            return data
        if status in {"FAILED", "CANCELLED"} or "FAIL" in status:
            raise ProviderError(translate_provider_error(data.get("failReason") or f"生成任务状态：{status}"))
    raise ProviderError("生成任务超时，请稍后查询")


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
