"""Kling V3 Omni 视频生成客户端（管理后台测试页用）。

异步任务模式：POST /video/generation/tasks 创建 → GET /video/generation/tasks/{id} 轮询。
默认走英和 AIGC 网关（settings.video_api_*），可用 KLING_API_BASE_URL/KLING_API_KEY 覆盖。
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import settings

MODES: tuple[str, ...] = ("std", "pro", "4k")  # 720P / 1080P / 4K
ASPECT_RATIOS: tuple[str, ...] = ("16:9", "9:16", "1:1")
IMAGE_TYPES: tuple[str, ...] = ("first_frame", "end_frame", "reference")
MIN_DURATION = 3.0
MAX_DURATION = 15.0


class KlingError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not settings.kling_api_key:
        raise KlingError("Kling API Key 未配置，请设置 KLING_API_KEY 或 VIDEO_API_KEY/共享 AIGC_TOKEN")
    return {"Content-Type": "application/json", "Authorization": f"Bearer {settings.kling_api_key}"}


def build_task_payload(
    *,
    prompt: str = "",
    negative_prompt: str = "",
    images: list[dict[str, str]] | None = None,
    videos: list[dict[str, str]] | None = None,
    element_ids: list[str] | None = None,
    duration: float = 5,
    mode: str = "pro",
    aspect_ratio: str = "16:9",
    sound: str = "off",
    cfg_scale: float = 0.5,
) -> dict[str, Any]:
    """组装创建任务请求体。

    images 项：{"imageUrl": URL 或 Base64, "type": first_frame/end_frame/reference}
    videos 项：{"videoUrl": URL 或 Base64, "referType": 可选, "keepOriginalSound": yes/no}
    约束：prompt/images/videos 至少一项；使用参考视频时 sound 必须为 off。
    """
    prompt = prompt.strip()
    image_list = [{"image_url": item["imageUrl"].strip(), "type": item.get("type") or "reference"} for item in (images or []) if item.get("imageUrl", "").strip()]
    video_list = []
    for item in videos or []:
        if not item.get("videoUrl", "").strip():
            continue
        entry: dict[str, str] = {"video_url": item["videoUrl"].strip()}
        if item.get("referType"):
            entry["refer_type"] = item["referType"]
        if item.get("keepOriginalSound"):
            entry["keep_original_sound"] = item["keepOriginalSound"]
        video_list.append(entry)

    if not prompt and not image_list and not video_list:
        raise KlingError("提示词、图片、视频至少提供一项")
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise KlingError(f"生成时长需在 {MIN_DURATION:g}~{MAX_DURATION:g} 秒之间")
    if mode not in MODES:
        raise KlingError(f"不支持的生成模式：{mode}")
    if aspect_ratio not in ASPECT_RATIOS:
        raise KlingError(f"不支持的画面比例：{aspect_ratio}")
    if sound not in ("on", "off"):
        raise KlingError("sound 仅支持 on/off")
    if video_list and sound != "off":
        raise KlingError("使用参考视频时 sound 必须设置为 off")
    if not 0 <= cfg_scale <= 1:
        raise KlingError("cfg_scale 需在 0~1 之间")
    for image in image_list:
        if image["type"] not in IMAGE_TYPES:
            raise KlingError(f"不支持的图片用途：{image['type']}")

    payload: dict[str, Any] = {
        "model_name": settings.kling_model,
        "duration": duration,
        "mode": mode,
        "aspect_ratio": aspect_ratio,
        "sound": sound,
        "cfg_scale": cfg_scale,
    }
    if prompt:
        payload["prompt"] = prompt
    if negative_prompt.strip():
        payload["negative_prompt"] = negative_prompt.strip()
    if image_list:
        payload["image_list"] = image_list
    if video_list:
        payload["video_list"] = video_list
    if element_ids:
        payload["element_list"] = [{"element_id": element_id} for element_id in element_ids if str(element_id).strip()]
    return payload


def _unwrap(body: dict[str, Any]) -> dict[str, Any]:
    """Kling 响应统一 {code, message, data} 包装；code 非 0 视为业务错误。"""
    if body.get("code") != 0 or not isinstance(body.get("data"), dict):
        raise KlingError(f"Kling 返回错误：{body.get('message') or body}")
    return body["data"]


async def create_task(**kwargs: Any) -> dict[str, Any]:
    """创建生成任务，返回 {taskId, status}。"""
    payload = build_task_payload(**kwargs)
    url = f"{settings.kling_api_base_url}/video/generation/tasks"
    try:
        async with httpx.AsyncClient(timeout=settings.kling_timeout) as client:
            response = await client.post(url, headers=_headers(), json=payload)
    except KlingError:
        raise
    except httpx.HTTPError as exc:
        raise KlingError(f"Kling 请求失败：{exc}") from exc
    if response.status_code != 200:
        raise KlingError(f"Kling 返回 HTTP {response.status_code}：{response.text[:300]}")
    data = _unwrap(response.json())
    task_id = data.get("task_id")
    if not task_id:
        raise KlingError(f"Kling 未返回 task_id：{data}")
    return {"taskId": str(task_id), "status": data.get("task_status", "")}


async def query_task(task_id: str) -> dict[str, Any]:
    """查询任务，透传 data（task_status/task_result/task_status_msg 等）。"""
    task_id = task_id.strip()
    if not task_id:
        raise KlingError("taskId 不能为空")
    url = f"{settings.kling_api_base_url}/video/generation/tasks/{task_id}"
    try:
        async with httpx.AsyncClient(timeout=settings.kling_timeout) as client:
            response = await client.get(url, headers=_headers())
    except KlingError:
        raise
    except httpx.HTTPError as exc:
        raise KlingError(f"Kling 查询失败：{exc}") from exc
    if response.status_code != 200:
        raise KlingError(f"Kling 查询返回 HTTP {response.status_code}：{response.text[:300]}")
    return _unwrap(response.json())
