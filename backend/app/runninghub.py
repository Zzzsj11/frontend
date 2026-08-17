"""RunningHub 云端 ComfyUI 工作流客户端（管理后台测试页用）。

接入的是「YZ金鱼-MiniMax H3超级多合一」工作流：一采 ref2va（多图参考生成低清视频+音频），
二采 fl2va（放大后首帧精修出高清成片）。通过 nodeInfoList 动态覆盖节点参数，
节点 ID 映射来自工作流 JSON，正式接入新工作流时需同步更新 NODE_IDS。
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import httpx

from .config import settings

# 工作流节点 ID 映射（来源：YZ金鱼-MiniMax H3超级多合一工作流-官方版_api.json）
NODE_PROMPT = "83"  # Text 节点：结构化提示词
NODE_DURATION = "84"  # PrimitiveFloat：视频时长（秒）
NODE_STAGE1_RESOLUTION = "105"  # 一采（ref2va 低清）ResolutionSelector
NODE_STAGE2_RESOLUTION = "297"  # 二采（fl2va 放大精修）ResolutionSelector
NODE_REF_IMAGES = ("97", "101", "132")  # 3 个 LoadImage 参考图槽位（Subject 1/2/3）
NODE_SEEDS = ("243", "300")  # 一采/二采 RandomNoise 种子

# 纯文生视频工作流（用户提供的 111.json）。该工作流没有图片输入，直接提交完整
# workflow JSON，避免依赖另一个需要人工发布和维护的 workflowId。
TEXT_WORKFLOW_PATH = Path(__file__).parent / "workflows" / "minimax_h3_text_to_video.json"
TEXT_NODE_PROMPT = "25"
TEXT_NODE_DURATION = "27"
TEXT_NODE_RESOLUTION = "23"
TEXT_NODE_SEED = "228"
TEXT_ASPECT_RATIOS: tuple[str, ...] = (
    "16:9 (Widescreen)",
    "9:16 (Portrait Widescreen)",
    "1:1 (Square)",
    "4:3 (Classic)",
    "3:4 (Portrait)",
)
DEFAULT_TEXT_MEGAPIXELS = 0.9

# ResolutionSelector（LayerUtility）的合法宽高比字符串；"16:9 (Widescreen)" 已经工作流默认验证
ASPECT_RATIOS: tuple[str, ...] = (
    "16:9 (Widescreen)",
    "9:16 (Portrait)",
    "1:1 (Square)",
    "4:3 (Classic)",
    "3:4 (Portrait)",
)

MIN_DURATION = 4.0
MAX_DURATION = 15.0

# megapixels 档位 → 16:9 输出分辨率（ResolutionSelector multiple=32，一/二阶段同表）
MEGAPIXELS_MIN = 0.2
MEGAPIXELS_MAX = 2.0
MEGAPIXELS_PRESETS_16X9: tuple[tuple[float, str], ...] = (
    (0.2, "608×352"),
    (0.3, "736×416"),
    (0.4, "864×480"),
    (0.5, "960×544"),
    (0.6, "1056×608"),
    (0.7, "1152×640"),
    (0.8, "1216×672"),
    (0.9, "1280×736"),
    (0.98, "1344×768"),
    (1.0, "1376×768"),
    (1.2, "1504×832"),
    (1.5, "1664×928"),
    (1.8, "1824×1024"),
    (2.0, "1920×1088"),
)
# 工作流默认值：一采低清 0.4MP，二采放大精修 0.9MP
DEFAULT_STAGE1_MEGAPIXELS = 0.4
DEFAULT_STAGE2_MEGAPIXELS = 0.9


class RunningHubError(RuntimeError):
    pass


def _headers() -> dict[str, str]:
    if not settings.runninghub_api_key:
        raise RunningHubError("RunningHub API Key 未配置，请在 backend/.env 设置 RUNNINGHUB_API_KEY")
    return {"Content-Type": "application/json", "Authorization": f"Bearer {settings.runninghub_api_key}"}


def _check_megapixels(value: float, stage: str) -> None:
    if not MEGAPIXELS_MIN <= value <= MEGAPIXELS_MAX:
        raise RunningHubError(f"{stage}分辨率需在 {MEGAPIXELS_MIN:g}~{MEGAPIXELS_MAX:g} MP 之间")


def build_node_info_list(
    *,
    prompt: str,
    duration: float,
    aspect_ratio: str,
    images: list[str],
    seed: int | None = None,
    stage1_megapixels: float = DEFAULT_STAGE1_MEGAPIXELS,
    stage2_megapixels: float = DEFAULT_STAGE2_MEGAPIXELS,
) -> list[dict[str, Any]]:
    """组装 nodeInfoList：提示词/时长/宽高比/参考图/种子。

    参考图不足 3 张时用最后一张补齐剩余槽位（工作流默认图是作者示例，留着会污染主体一致性）。
    值为 RunningHub 上传接口返回的 fileName 或可公开访问的图片 URL。
    """
    prompt = prompt.strip()
    if not prompt:
        raise RunningHubError("提示词不能为空")
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise RunningHubError(f"视频时长需在 {MIN_DURATION:g}~{MAX_DURATION:g} 秒之间")
    if aspect_ratio not in ASPECT_RATIOS:
        raise RunningHubError(f"不支持的宽高比：{aspect_ratio}")
    _check_megapixels(stage1_megapixels, "一阶段")
    _check_megapixels(stage2_megapixels, "二阶段")
    images = [item.strip() for item in images if item and item.strip()]
    if not images:
        raise RunningHubError("至少需要 1 张参考图")
    while len(images) < len(NODE_REF_IMAGES):
        images.append(images[-1])

    node_info: list[dict[str, Any]] = [{"nodeId": NODE_PROMPT, "fieldName": "text", "fieldValue": prompt}]
    node_info.append({"nodeId": NODE_DURATION, "fieldName": "value", "fieldValue": duration})
    for node_id, megapixels in ((NODE_STAGE1_RESOLUTION, stage1_megapixels), (NODE_STAGE2_RESOLUTION, stage2_megapixels)):
        node_info.append({"nodeId": node_id, "fieldName": "aspect_ratio", "fieldValue": aspect_ratio})
        node_info.append({"nodeId": node_id, "fieldName": "megapixels", "fieldValue": megapixels})
    for node_id, image in zip(NODE_REF_IMAGES, images, strict=True):
        node_info.append({"nodeId": node_id, "fieldName": "image", "fieldValue": image})
    if seed is not None:
        for offset, node_id in enumerate(NODE_SEEDS):
            node_info.append({"nodeId": node_id, "fieldName": "noise_seed", "fieldValue": seed + offset})
    return node_info


def build_text_node_info_list(
    *,
    prompt: str,
    duration: float,
    aspect_ratio: str,
    seed: int | None = None,
    megapixels: float = DEFAULT_TEXT_MEGAPIXELS,
) -> list[dict[str, Any]]:
    """组装纯文生视频工作流的动态节点参数。"""
    prompt = prompt.strip()
    if not prompt:
        raise RunningHubError("提示词不能为空")
    if not MIN_DURATION <= duration <= MAX_DURATION:
        raise RunningHubError(f"视频时长需在 {MIN_DURATION:g}~{MAX_DURATION:g} 秒之间")
    if aspect_ratio not in TEXT_ASPECT_RATIOS:
        raise RunningHubError(f"纯文生视频不支持的宽高比：{aspect_ratio}")
    _check_megapixels(megapixels, "输出")
    nodes: list[dict[str, Any]] = [
        {"nodeId": TEXT_NODE_PROMPT, "fieldName": "text", "fieldValue": prompt},
        {"nodeId": TEXT_NODE_DURATION, "fieldName": "value", "fieldValue": duration},
        {"nodeId": TEXT_NODE_RESOLUTION, "fieldName": "aspect_ratio", "fieldValue": aspect_ratio},
        {"nodeId": TEXT_NODE_RESOLUTION, "fieldName": "megapixels", "fieldValue": megapixels},
    ]
    if seed is not None:
        nodes.append({"nodeId": TEXT_NODE_SEED, "fieldName": "noise_seed", "fieldValue": seed})
    return nodes


async def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = f"{settings.runninghub_base_url}{path}"
    try:
        async with httpx.AsyncClient(timeout=settings.runninghub_timeout) as client:
            response = await client.post(url, headers=_headers(), json=payload)
    except RunningHubError:
        raise
    except httpx.HTTPError as exc:
        raise RunningHubError(f"RunningHub 请求失败：{exc}") from exc
    if response.status_code == 401:
        raise RunningHubError("RunningHub API Key 校验失败，请检查 RUNNINGHUB_API_KEY")
    if response.status_code != 200:
        raise RunningHubError(f"RunningHub 返回 HTTP {response.status_code}：{response.text[:300]}")
    try:
        return response.json()
    except ValueError as exc:
        raise RunningHubError(f"RunningHub 响应解析失败：{response.text[:300]}") from exc


async def submit_task(
    *,
    prompt: str,
    duration: float,
    aspect_ratio: str,
    images: list[str],
    seed: int | None = None,
    stage1_megapixels: float = DEFAULT_STAGE1_MEGAPIXELS,
    stage2_megapixels: float = DEFAULT_STAGE2_MEGAPIXELS,
) -> dict[str, Any]:
    """提交工作流任务，返回 RunningHub 原始响应（含 taskId）。"""
    node_info = build_node_info_list(
        prompt=prompt,
        duration=duration,
        aspect_ratio=aspect_ratio,
        images=images,
        seed=seed,
        stage1_megapixels=stage1_megapixels,
        stage2_megapixels=stage2_megapixels,
    )
    payload = {"addMetadata": True, "nodeInfoList": node_info, "instanceType": "default", "usePersonalQueue": "false"}
    result = await _post(f"/run/workflow/{settings.runninghub_workflow_id}", payload)
    if not result.get("taskId"):
        raise RunningHubError(f"RunningHub 未返回 taskId：{result}")
    return result


async def submit_text_task(
    *,
    prompt: str,
    duration: float,
    aspect_ratio: str,
    seed: int | None = None,
    megapixels: float = DEFAULT_TEXT_MEGAPIXELS,
) -> dict[str, Any]:
    """使用完整 workflow JSON 提交 H3 纯文生视频任务。"""
    node_info = build_text_node_info_list(
        prompt=prompt,
        duration=duration,
        aspect_ratio=aspect_ratio,
        seed=seed,
        megapixels=megapixels,
    )
    try:
        workflow = TEXT_WORKFLOW_PATH.read_text(encoding="utf-8")
        json.loads(workflow)
    except (OSError, ValueError) as exc:
        raise RunningHubError(f"H3 纯文生视频工作流读取失败：{exc}") from exc

    # RunningHub 的高级 ComfyUI 接口允许直接提交完整工作流；返回结构为
    # {code, msg, data:{taskId, taskStatus}}，与 /openapi/v2/run/workflow 不同。
    origin = settings.runninghub_base_url.removesuffix("/openapi/v2")
    url = f"{origin}/task/openapi/create"
    payload = {
        "apiKey": settings.runninghub_api_key,
        # 高级接口的校验仍要求 workflowId 非空；传入 workflow 时完整 JSON 优先。
        "workflowId": settings.runninghub_workflow_id,
        "workflow": workflow,
        "nodeInfoList": node_info,
        "addMetadata": True,
        "instanceType": "default",
        "usePersonalQueue": False,
    }
    try:
        async with httpx.AsyncClient(timeout=settings.runninghub_timeout) as client:
            response = await client.post(url, headers=_headers(), json=payload)
    except httpx.HTTPError as exc:
        raise RunningHubError(f"RunningHub 纯文生视频请求失败：{exc}") from exc
    if response.status_code == 401:
        raise RunningHubError("RunningHub API Key 校验失败，请检查 RUNNINGHUB_API_KEY")
    if response.status_code != 200:
        raise RunningHubError(f"RunningHub 纯文生视频返回 HTTP {response.status_code}：{response.text[:300]}")
    try:
        body = response.json()
    except ValueError as exc:
        raise RunningHubError(f"RunningHub 纯文生视频响应解析失败：{response.text[:300]}") from exc
    if body.get("code") != 0 or not isinstance(body.get("data"), dict):
        raise RunningHubError(f"RunningHub 纯文生视频提交失败：{body.get('msg') or body.get('message') or body}")
    data = body["data"]
    task_id = data.get("taskId")
    if not task_id:
        raise RunningHubError(f"RunningHub 纯文生视频未返回 taskId：{data}")
    return {"taskId": str(task_id), "status": data.get("taskStatus", "")}


async def query_task(task_id: str) -> dict[str, Any]:
    """查询任务状态，透传 RunningHub 原始响应。"""
    task_id = task_id.strip()
    if not task_id:
        raise RunningHubError("taskId 不能为空")
    return await _post("/query", {"taskId": task_id})


async def upload_media(content: bytes, filename: str) -> dict[str, Any]:
    """上传参考图，返回 {fileName, downloadUrl, size}；fileName 用于 LoadImage 节点。"""
    if not content:
        raise RunningHubError("上传文件为空")
    safe_name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1] or f"{uuid.uuid4().hex}.png"
    url = f"{settings.runninghub_base_url}/media/upload/binary"
    try:
        async with httpx.AsyncClient(timeout=settings.runninghub_timeout) as client:
            response = await client.post(url, headers={"Authorization": _headers()["Authorization"]}, files={"file": (safe_name, content)})
    except RunningHubError:
        raise
    except httpx.HTTPError as exc:
        raise RunningHubError(f"RunningHub 上传失败：{exc}") from exc
    if response.status_code != 200:
        raise RunningHubError(f"RunningHub 上传返回 HTTP {response.status_code}：{response.text[:300]}")
    body = response.json()
    if body.get("code") != 0 or not isinstance(body.get("data"), dict):
        raise RunningHubError(f"RunningHub 上传失败：{body.get('message') or body}")
    data = body["data"]
    return {"fileName": data.get("fileName", ""), "downloadUrl": data.get("download_url", ""), "size": data.get("size", "")}
