"""子项目视频模型统一修改；预览与保存共用能力校验，不调用供应商。"""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentUser
from .database import database_session
from .domain import owned_task, task_json
from .models import AiModelModel, AiProviderModel, GenerationJobModel, ProjectTaskModel, StoryboardLineModel

router = APIRouter(prefix="/api")
SUPPORTED_VIDEO_MODELS = frozenset(
    {
        "doubao-seedance-2.0",
        "doubao-seedance-2.0-mini",
        "doubao-seedance-2.0-fast",
        "wan3.0-video",
        "wan3.0-video-prime",
        "minimax-h3",
        "minimax-h3-runninghub",
    }
)


class TaskVideoModelChange(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    apply: bool = False
    preview_token: str | None = None


async def lock_video_task(db: AsyncSession, task_id: str) -> None:
    # NO KEY UPDATE 与生成工单插入时的外键锁兼容，同时串行化配置修改和生成提交。
    await db.execute(select(ProjectTaskModel.id).where(ProjectTaskModel.id == task_id).with_for_update(key_share=True))


def _token(task: ProjectTaskModel, lines: list[StoryboardLineModel], model: AiModelModel) -> str:
    snapshot = [task.storyboard_config, model.code, model.capabilities, [(line.id, line.shot_options) for line in lines]]
    return hashlib.sha256(json.dumps(snapshot, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def plan_line(options: dict, model: AiModelModel, number: int) -> tuple[dict, list[str], list[str]]:
    updated = {"resolution": "480p", "ratio": "16:9", "duration": 5, **options}
    changes, errors = [], []
    capabilities = model.capabilities or {}
    updated["videoModel"] = model.code
    resolution = options.get("resolution") or "480p"
    resolutions = capabilities.get("resolutions") or ["480p", "720p", "1080p"]
    if resolution not in resolutions:
        updated["resolution"] = resolutions[0]
        labels = capabilities.get("resolutionLabels") or {}
        target_label = labels.get(resolutions[0]) or str(resolutions[0]).upper()
        changes.append(f"第 {number} 镜：清晰度 {resolution.upper()} → {target_label}")
    ratio = options.get("ratio") or "16:9"
    if ratio not in (capabilities.get("ratios") or ["16:9", "9:16", "4:3", "1:1"]):
        errors.append(f"第 {number} 镜：目标模型不支持画幅 {ratio}，请先调整该镜头")
    duration = float(options.get("duration") or 5)
    limits = capabilities.get("durations") or {"min": 4, "max": 15}
    durations = capabilities.get("durationOptions") or list(range(int(limits.get("min") or 4), int(limits.get("max") or 15) + 1))
    if duration not in durations:
        candidates = [item for item in durations if item >= duration]
        if candidates:
            updated["duration"] = min(candidates)
            changes.append(f"第 {number} 镜：生成时长 {duration:g} 秒 → {updated['duration']} 秒（时间轴保持原安排）")
        else:
            errors.append(f"第 {number} 镜：{duration:g} 秒超过目标模型可支持的时长，请先调整该镜头")
    if options.get("videoModel") != model.code:
        # 避免将上一模型的首尾帧模式直接带到新模型；自动模式仍使用已有场景与人物参考。
        updated["h3Mode"] = "auto"
        if options.get("h3Mode") not in (None, "auto"):
            changes.append(f"第 {number} 镜：生成模式调整为自动")
        for key in ("h3FirstFrameUrl", "h3LastFrameUrl"):
            if options.get(key):
                errors.append(f"第 {number} 镜：存在专用首尾帧，请先在单镜设置中处理后再切换模型")
    for field, key, label in (("referenceVideoUrls", "referenceVideo", "视频"), ("referenceAudioUrls", "referenceAudio", "音频")):
        refs = options.get(field) or []
        rule = capabilities.get(key) or {"max": 0}
        if len(refs) > int(rule.get("max") or 0):
            errors.append(f"第 {number} 镜：目标模型不支持当前参考{label}数量，请先处理该镜头")
    if options.get("referenceImageUrls") and not capabilities.get("h3Modes"):
        errors.append(f"第 {number} 镜：存在 H3 专用多图参考，请先处理该镜头")
    return updated, changes, errors


@router.post("/tasks/{task_id}/video-model")
async def change_task_video_model(task_id: str, payload: TaskVideoModelChange, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    task = await owned_task(db, user.id, task_id)
    await lock_video_task(db, task_id)
    await db.refresh(task)
    if task.storyboard_type not in {"ass", "general", "general_random"}:
        raise HTTPException(422, "仅支持 ASS、定制通用和随机通用分镜")
    active = (
        await db.execute(
            select(GenerationJobModel.id)
            .where(
                GenerationJobModel.project_task_id == task_id,
                GenerationJobModel.user_id == user.id,
                GenerationJobModel.kind.in_(["video", "ass_outline", "general_outline", "ass_segment_retry", "storyboard_line"]),
                GenerationJobModel.status.in_(["queued", "running"]),
                GenerationJobModel.deleted_at.is_(None),
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if active or task.status == "outlining":
        raise HTTPException(409, "当前子项目有排队或生成中的任务，请等待完成后修改视频模型")
    if payload.model not in SUPPORTED_VIDEO_MODELS:
        raise HTTPException(422, "批量修改仅支持 Seedance、Wan3.0 和 H3 系列")
    model = (
        await db.execute(
            select(AiModelModel)
            .join(AiProviderModel)
            .where(
                AiModelModel.code == payload.model,
                AiModelModel.modality == "video",
                AiModelModel.status == "active",
                AiModelModel.user_visible.is_(True),
                AiModelModel.deleted_at.is_(None),
                AiProviderModel.status == "active",
                AiProviderModel.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not model:
        raise HTTPException(422, "目标视频模型已停用或不可用，请重新选择")
    lines = list(
        (
            await db.execute(
                select(StoryboardLineModel)
                .where(
                    StoryboardLineModel.project_task_id == task_id,
                    StoryboardLineModel.deleted_at.is_(None),
                )
                .order_by(StoryboardLineModel.sort_order, StoryboardLineModel.id)
                .with_for_update()
            )
        ).scalars()
    )
    if not lines:
        raise HTTPException(422, "请先生成分镜，再修改视频模型")
    token = _token(task, lines, model)
    plans, adjustments, blockers = [], [], []
    for number, line in enumerate(lines, 1):
        if line.source == "creative":
            blockers.append(f"第 {number} 镜：创意分镜使用独立参考素材，请单独设置模型")
        plan, changes, errors = plan_line(line.shot_options or {}, model, number)
        plans.append({"id": line.id, "shotOptions": plan})
        adjustments.extend(changes)
        blockers.extend(errors)
    result = {
        "taskId": task_id,
        "model": model.code,
        "modelName": model.name,
        "count": len(lines),
        "adjustments": adjustments,
        "blockers": blockers,
        "previewToken": token,
        "lines": plans,
        "applied": False,
    }
    if not payload.apply:
        return result
    if payload.preview_token != token:
        raise HTTPException(409, "分镜或模型配置已变化，请重新预览后保存")
    if blockers:
        raise HTTPException(422, "；".join(blockers))
    for line, plan in zip(lines, plans, strict=True):
        line.shot_options = plan["shotOptions"]
    previous_config = task.storyboard_config or {}
    resolutions = (model.capabilities or {}).get("resolutions") or ["480p", "720p", "1080p"]
    default_resolution = previous_config.get("resolution") or "480p"
    if default_resolution not in resolutions:
        default_resolution = resolutions[0]
    task.storyboard_config = {
        **(task.storyboard_config or {}),
        "video_model": model.code,
        "videoModel": model.code,
        "videoModelDefaults": {"videoModel": model.code, "resolution": default_resolution, "h3Mode": "auto"},
        "resolution": default_resolution,
        "videoModelRevision": token,
    }
    await db.commit()
    result.update(applied=True, task=task_json(task))
    return result
