from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import uuid
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Coroutine
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentUser, hash_password, user_public
from .config import settings
from .database import database_session, session_factory
from .jobs import Job, jobs
from .media_constraints import normalize_video_duration
from .models import (
    AdminOperationLogModel,
    AdminRoleModel,
    AiModelModel,
    ApiErrorLogModel,
    ChatMessageModel,
    ChatSessionModel,
    DigitalHumanModel,
    DigitalHumanStyleModel,
    GenerationJobModel,
    MaterialExportModel,
    ProjectCastModel,
    ProjectModel,
    ProjectTaskModel,
    RefreshTokenModel,
    SceneAssetModel,
    ShotAssetModel,
    StoryboardLineCastModel,
    StoryboardLineModel,
    TokenUsageModel,
    UserAdminRoleModel,
    UserModel,
    VoiceAssetModel,
    utcnow,
)
from .rbac import attach_admin_access
from .schemas import (
    CastUpdate,
    DigitalHumanCreate,
    DigitalHumanUpdate,
    GeneralStoryboardCreate,
    ProjectCreate,
    ProjectUpdate,
    ReorderLines,
    StoryboardLineCreate,
    StoryboardLineGenerate,
    StoryboardLineUpdate,
    StyleCreate,
    TaskCreate,
    TaskUpdate,
    UserAdminRoleUpdate,
    UserCreate,
    UserUpdate,
)
from .storage import download_public_url_to_path, get_storage, is_tos_url, safe_key
from .story_bible import STORY_BIBLE_VERSION, build_ass_story_bible, build_general_story_bible, exact_durations
from .storyboard_options import load_general_storyboard_options
from .storyboard_prompt import (
    PROMPT_VERSION,
    SCHEMA_VERSION,
    finalize_shot_durations,
    generate_ass_story_outline,
    generate_general_story_outline,
    generate_storyboard_line,
    regenerate_ass_scene_segment,
)
from .token_usage import add_llm_call_log, add_token_usage, normalize_usage
from .usage_quota import consume_daily_quota

router = APIRouter(prefix="/api")
Db = Depends(database_session)
storyboard_generation_slots = asyncio.Semaphore(settings.storyboard_generation_concurrency)
export_slots = asyncio.Semaphore(settings.export_concurrency)
export_progress_locks: dict[str, asyncio.Lock] = {}


@router.get("/admin/api-errors")
async def list_api_errors(
    user: CurrentUser,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Db,
) -> dict:
    require_admin(user)
    limit = min(500, max(1, limit))
    offset = max(0, offset)
    conditions = [ApiErrorLogModel.deleted_at.is_(None)]
    total = (await db.execute(select(func.count()).select_from(ApiErrorLogModel).where(*conditions))).scalar_one()
    items = list((await db.execute(select(ApiErrorLogModel).where(*conditions).order_by(ApiErrorLogModel.created_at.desc()).limit(limit).offset(offset))).scalars().all())
    return {
        "total": total,
        "items": [
            {
                "id": item.id,
                "errorCode": item.error_code,
                "userId": item.user_id,
                "method": item.method,
                "path": item.path,
                "queryString": item.query_string,
                "statusCode": item.status_code,
                "errorType": item.error_type,
                "message": item.message,
                "requestPayload": item.request_payload,
                "traceback": item.traceback,
                "clientIp": item.client_ip,
                "userAgent": item.user_agent,
                "createdAt": item.created_at.isoformat(),
            }
            for item in items
        ],
    }


@router.delete("/admin/api-errors/{error_id}")
async def delete_api_error(error_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    require_admin(user)
    item = await db.get(ApiErrorLogModel, error_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(404, "错误日志不存在")
    item.deleted_at = utcnow()
    await db.commit()
    return {"ok": True}


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def require_admin(user) -> None:
    from .rbac import require_super_admin

    require_super_admin(user)


@router.get("/admin/users")
async def list_users(user: CurrentUser, limit: int = 100, db: AsyncSession = Db) -> list[dict]:
    """用户列表：强制 limit 上限，防止全量拉取拖垮数据库。"""
    require_admin(user)
    limit = min(500, max(1, limit))
    items = (await db.execute(select(UserModel).where(UserModel.deleted_at.is_(None)).order_by(UserModel.created_at).limit(limit))).scalars().all()
    result = []
    for item in items:
        await attach_admin_access(db, item)
        result.append({**user_public(item), "status": item.status, "createdAt": item.created_at.isoformat()})
    return result


@router.post("/admin/users", status_code=201)
async def create_user(payload: UserCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    require_admin(user)
    username = payload.username.strip().lower()
    exists = (await db.execute(select(UserModel).where(UserModel.username == username, UserModel.deleted_at.is_(None)))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "用户名已存在")
    item = UserModel(
        id=uid("user"),
        username=username,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        role=payload.role,
        must_change_password=True,
        daily_chat_limit=payload.daily_chat_limit or settings.daily_chat_limit,
        daily_image_limit=payload.daily_image_limit or settings.daily_image_limit,
        daily_video_limit=payload.daily_video_limit or settings.daily_video_limit,
    )
    db.add(item)
    await db.commit()
    return user_public(item)


@router.patch("/admin/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    require_admin(user)
    item = await db.get(UserModel, user_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(404, "用户不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    return user_public(item)


@router.put("/admin/users/{user_id}/admin-role")
async def update_user_admin_role(
    user_id: str,
    payload: UserAdminRoleUpdate,
    request: Request,
    user: CurrentUser,
    db: AsyncSession = Db,
) -> dict:
    require_admin(user)
    item = await db.get(UserModel, user_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(404, "用户不存在")
    if user_id == user.id and payload.admin_role_code != "super_admin":
        raise HTTPException(422, "不能移除当前超级管理员自己的权限")
    before_roles = list(
        (
            await db.execute(
                select(AdminRoleModel.code)
                .join(UserAdminRoleModel, UserAdminRoleModel.role_id == AdminRoleModel.id)
                .where(UserAdminRoleModel.user_id == user_id, UserAdminRoleModel.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    now = utcnow()
    links = list(
        (
            await db.execute(
                select(UserAdminRoleModel).where(
                    UserAdminRoleModel.user_id == user_id,
                    UserAdminRoleModel.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    for link in links:
        link.deleted_at = now
    if payload.admin_role_code == "none":
        item.role = "user"
    else:
        role = (
            await db.execute(
                select(AdminRoleModel).where(
                    AdminRoleModel.code == payload.admin_role_code,
                    AdminRoleModel.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not role:
            raise HTTPException(500, "后台角色尚未初始化")
        item.role = "admin"
        reusable = next((link for link in links if link.role_id == role.id), None)
        if reusable:
            reusable.deleted_at = None
        else:
            db.add(UserAdminRoleModel(id=uid("uar"), user_id=user_id, role_id=role.id))
    db.add(
        AdminOperationLogModel(
            id=uid("audit"),
            admin_user_id=user.id,
            action="user.admin_role.update",
            target_type="user",
            target_id=user_id,
            before_data={"roles": before_roles},
            after_data={"role": payload.admin_role_code},
            client_ip=request.client.host if request.client else None,
        )
    )
    await db.commit()
    await attach_admin_access(db, item)
    return user_public(item)


@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    require_admin(user)
    if user_id == user.id:
        raise HTTPException(422, "不能删除当前登录用户")
    item = await db.get(UserModel, user_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(404, "用户不存在")
    now = utcnow()
    item.deleted_at = now
    item.status = "disabled"
    projects = list((await db.execute(select(ProjectModel).where(ProjectModel.user_id == user_id, ProjectModel.deleted_at.is_(None)))).scalars().all())
    task_ids = list(
        (
            await db.execute(
                select(ProjectTaskModel.id).where(ProjectTaskModel.project_id.in_([p.id for p in projects]) if projects else False, ProjectTaskModel.deleted_at.is_(None))
            )
        )
        .scalars()
        .all()
    )
    for project in projects:
        project.deleted_at = now
    await soft_delete_task_tree(db, task_ids, now)
    for model in (RefreshTokenModel, DigitalHumanStyleModel, DigitalHumanModel, ChatSessionModel, GenerationJobModel, MaterialExportModel):
        await db.execute(update(model).where(model.user_id == user_id, model.deleted_at.is_(None)).values(deleted_at=now))
    session_ids = list((await db.execute(select(ChatSessionModel.id).where(ChatSessionModel.user_id == user_id))).scalars().all())
    if session_ids:
        await db.execute(update(ChatMessageModel).where(ChatMessageModel.session_id.in_(session_ids), ChatMessageModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.commit()
    return {"ok": True}


async def owned_project(db: AsyncSession, user_id: str, project_id: str) -> ProjectModel:
    result = await db.execute(select(ProjectModel).where(ProjectModel.id == project_id, ProjectModel.user_id == user_id, ProjectModel.deleted_at.is_(None)))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "项目不存在")
    return item


async def owned_task(db: AsyncSession, user_id: str, task_id: str) -> ProjectTaskModel:
    result = await db.execute(
        select(ProjectTaskModel)
        .join(ProjectModel, ProjectModel.id == ProjectTaskModel.project_id)
        .where(
            ProjectTaskModel.id == task_id,
            ProjectTaskModel.deleted_at.is_(None),
            ProjectModel.user_id == user_id,
            ProjectModel.deleted_at.is_(None),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "子项目不存在")
    return item


async def owned_line(db: AsyncSession, user_id: str, line_id: str) -> StoryboardLineModel:
    result = await db.execute(
        select(StoryboardLineModel)
        .join(ProjectTaskModel, ProjectTaskModel.id == StoryboardLineModel.project_task_id)
        .join(ProjectModel, ProjectModel.id == ProjectTaskModel.project_id)
        .where(
            StoryboardLineModel.id == line_id,
            StoryboardLineModel.deleted_at.is_(None),
            ProjectTaskModel.deleted_at.is_(None),
            ProjectModel.user_id == user_id,
            ProjectModel.deleted_at.is_(None),
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "分镜不存在")
    return item


async def visible_humans(db: AsyncSession, user_id: str, ids: list[str] | None = None) -> list[DigitalHumanModel]:
    query = (
        select(DigitalHumanModel)
        .where(
            DigitalHumanModel.deleted_at.is_(None),
            DigitalHumanModel.status == "active",
            or_(DigitalHumanModel.scope == "system", DigitalHumanModel.user_id == user_id),
        )
        .order_by(
            case((DigitalHumanModel.scope == "private", 0), else_=1),
            DigitalHumanModel.created_at.desc(),
        )
    )
    if ids is not None:
        query = query.where(DigitalHumanModel.id.in_(ids))
    return list((await db.execute(query)).scalars().all())


async def soft_delete_task_tree(db: AsyncSession, task_ids: list[str], now) -> None:
    if not task_ids:
        return
    line_ids = list(
        (await db.execute(select(StoryboardLineModel.id).where(StoryboardLineModel.project_task_id.in_(task_ids), StoryboardLineModel.deleted_at.is_(None)))).scalars().all()
    )
    await db.execute(update(ProjectTaskModel).where(ProjectTaskModel.id.in_(task_ids), ProjectTaskModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.execute(update(ProjectCastModel).where(ProjectCastModel.project_task_id.in_(task_ids), ProjectCastModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.execute(update(MaterialExportModel).where(MaterialExportModel.project_task_id.in_(task_ids), MaterialExportModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.execute(update(GenerationJobModel).where(GenerationJobModel.project_task_id.in_(task_ids), GenerationJobModel.deleted_at.is_(None)).values(deleted_at=now))
    if line_ids:
        await db.execute(update(StoryboardLineModel).where(StoryboardLineModel.id.in_(line_ids), StoryboardLineModel.deleted_at.is_(None)).values(deleted_at=now))
        for model in (StoryboardLineCastModel, SceneAssetModel, ShotAssetModel, VoiceAssetModel):
            column = model.storyboard_line_id
            await db.execute(update(model).where(column.in_(line_ids), model.deleted_at.is_(None)).values(deleted_at=now))


def project_json(item: ProjectModel, tasks: list[ProjectTaskModel] = []) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "artist": item.artist,
        "songCode": item.song_code,
        "description": item.description,
        "status": item.status,
        "coverUrl": item.cover_url,
        "updatedAt": item.updated_at.isoformat(),
        "tasks": [task_json(task) for task in tasks],
    }


def task_json(item: ProjectTaskModel) -> dict:
    return {
        "id": item.id,
        "projectId": item.project_id,
        "title": item.title,
        "storyboardType": item.storyboard_type,
        "status": item.status,
        "sourceAssUrl": item.source_ass_url,
        "extraRequirement": item.extra_requirement,
        "overallPrompt": item.overall_prompt,
        "storyboardConfig": item.storyboard_config,
        "updatedAt": item.updated_at.isoformat(),
    }


@router.get("/projects")
async def list_projects(user: CurrentUser, db: AsyncSession = Db) -> list[dict]:
    projects = list(
        (
            await db.execute(
                select(ProjectModel).where(ProjectModel.user_id == user.id, ProjectModel.deleted_at.is_(None)).order_by(ProjectModel.sort_order, ProjectModel.updated_at.desc())
            )
        )
        .scalars()
        .all()
    )
    if not projects:
        return []
    tasks = list(
        (
            await db.execute(
                select(ProjectTaskModel)
                .where(ProjectTaskModel.project_id.in_([p.id for p in projects]), ProjectTaskModel.deleted_at.is_(None))
                .order_by(ProjectTaskModel.sort_order, ProjectTaskModel.created_at)
            )
        )
        .scalars()
        .all()
    )
    by_project: dict[str, list[ProjectTaskModel]] = {}
    for task in tasks:
        by_project.setdefault(task.project_id, []).append(task)
    return [project_json(project, by_project.get(project.id, [])) for project in projects]


class ReorderRequest(BaseModel):
    order: list[str]


@router.patch("/projects/reorder")
async def reorder_projects(payload: ReorderRequest, user: CurrentUser, db: AsyncSession = Db) -> dict:
    """批量更新歌曲项目的排序。{order: ["id1","id2",...]}"""
    for index, project_id in enumerate(payload.order):
        await db.execute(update(ProjectModel).where(ProjectModel.id == project_id, ProjectModel.user_id == user.id, ProjectModel.deleted_at.is_(None)).values(sort_order=index))
    await db.commit()
    return {"ok": True}


@router.patch("/projects/{project_id}/tasks/reorder")
async def reorder_tasks(project_id: str, payload: ReorderRequest, user: CurrentUser, db: AsyncSession = Db) -> dict:
    """批量更新子项目的排序。{order: ["id1","id2",...]}"""
    await owned_project(db, user.id, project_id)
    for index, task_id in enumerate(payload.order):
        await db.execute(
            update(ProjectTaskModel)
            .where(ProjectTaskModel.id == task_id, ProjectTaskModel.project_id == project_id, ProjectTaskModel.deleted_at.is_(None))
            .values(sort_order=index)
        )
    await db.commit()
    return {"ok": True}


@router.post("/projects", status_code=201)
async def create_project(payload: ProjectCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = ProjectModel(id=uid("project"), user_id=user.id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return project_json(item)


@router.patch("/projects/{project_id}")
async def update_project(project_id: str, payload: ProjectUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = await owned_project(db, user.id, project_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return project_json(item)


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = await owned_project(db, user.id, project_id)
    now = utcnow()
    item.deleted_at = now
    task_ids = list((await db.execute(select(ProjectTaskModel.id).where(ProjectTaskModel.project_id == item.id, ProjectTaskModel.deleted_at.is_(None)))).scalars().all())
    await soft_delete_task_tree(db, task_ids, now)
    await db.commit()
    return {"ok": True}


@router.post("/projects/{project_id}/tasks", status_code=201)
async def create_task(project_id: str, payload: TaskCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    await owned_project(db, user.id, project_id)
    item = ProjectTaskModel(id=uid("task"), project_id=project_id, **payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return task_json(item)


@router.get("/storyboards/general/options")
async def general_storyboard_options(user: CurrentUser, db: AsyncSession = Db) -> dict:
    """通用分镜生成弹窗选项：曲风三级树 + 季节/年龄段/画面风格/画幅（管理后台可配，软删生效）。"""
    return await load_general_storyboard_options(db)


@router.post("/projects/{project_id}/storyboards/general", status_code=201)
async def create_general_storyboard(project_id: str, payload: GeneralStoryboardCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    await owned_project(db, user.id, project_id)
    for code, modality in [(payload.image_model, "image"), (payload.video_model, "video")]:
        model = (
            await db.execute(
                select(AiModelModel).where(AiModelModel.code == code, AiModelModel.modality == modality, AiModelModel.status == "active", AiModelModel.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if not model:
            label = {"chat": "文本", "image": "图片", "video": "视频", "audio": "音频"}.get(modality, "生成")
            raise HTTPException(422, f"不支持或已停用的{label}模型：{code}")
    total = payload.empty_shot_count + payload.character_shot_count
    if total < 1:
        raise HTTPException(422, "至少需要一个分镜")
    if payload.character_shot_count and not payload.digital_human_ids:
        raise HTTPException(422, "人物镜数量大于 0 时至少需要选择一个角色")
    visible = await visible_humans(db, user.id, payload.digital_human_ids)
    if len({item.id for item in visible}) != len(set(payload.digital_human_ids)):
        raise HTTPException(422, "包含不可用角色")
    config = payload.model_dump(mode="json")
    title = f"通用分镜-{utcnow().astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d-%H-%M-%S')}"
    try:
        durations = exact_durations(payload.total_duration, total)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    task = ProjectTaskModel(
        id=uid("task"),
        project_id=project_id,
        title=title,
        storyboard_type="general",
        status="parsed",
        extra_requirement=payload.extra_requirement,
        overall_prompt=payload.overall_prompt,
        storyboard_config=config,
    )
    db.add(task)
    await db.flush()
    for index, human_id in enumerate(payload.digital_human_ids):
        db.add(ProjectCastModel(id=uid("cast"), project_task_id=task.id, digital_human_id=human_id, sort_order=index))
    # 占位 lines：大纲生成前只确定数量与时长，shotType 与大纲字段由后台任务回填
    output = []
    for index in range(total):
        duration = durations[index]
        line = StoryboardLineModel(
            id=uid("line"),
            project_task_id=task.id,
            sort_order=index,
            source="general",
            shot_type="empty",
            planned_duration=duration,
            scene_prompt="",
            shot_prompt="",
            shot_options={
                "ratio": payload.ratio,
                "resolution": payload.resolution,
                "imageModel": payload.image_model,
                "videoModel": payload.video_model,
                "duration": normalize_video_duration(duration),
                "outlineStatus": "pending",
            },
            generation_status="pending",
        )
        db.add(line)
        await db.flush()
        output.append(
            {
                "id": line.id,
                "shotType": "empty",
                "plannedDuration": duration,
                "scenePrompt": "",
                "shotPrompt": "",
                "digitalHumanIds": [],
                "shotOptions": line.shot_options,
                "generationStatus": "pending",
            }
        )
    await db.commit()
    return {
        "taskId": task.id,
        "projectId": project_id,
        "title": title,
        "status": "parsed",
        "cast": payload.digital_human_ids,
        "totalDuration": payload.total_duration,
        "storyboardConfig": config,
        "lines": output,
    }


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: CurrentUser, db: AsyncSession = Db, history: bool = True) -> dict:
    task = await owned_task(db, user.id, task_id)
    lines = list(
        (
            await db.execute(
                select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    cast = list(
        (await db.execute(select(ProjectCastModel).where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None)).order_by(ProjectCastModel.sort_order)))
        .scalars()
        .all()
    )
    line_cast = list(
        (
            await db.execute(
                select(StoryboardLineCastModel).where(
                    StoryboardLineCastModel.storyboard_line_id.in_([line.id for line in lines]) if lines else False, StoryboardLineCastModel.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    casts: dict[str, list[str]] = {}
    for link in line_cast:
        casts.setdefault(link.storyboard_line_id, []).append(link.digital_human_id)
    # P2 切换路径瘦身：批量预取全部行的媒体资产（3 条 IN 查询 + 按行分组），
    # 替代逐行各查 3 条的 N+1；history=false 时每行只回传当前选用资产 + 历史版本计数
    line_ids = [line.id for line in lines]
    scenes_by_line: dict[str, list[SceneAssetModel]] = {}
    for asset in (
        (
            await db.execute(
                select(SceneAssetModel)
                .where(SceneAssetModel.storyboard_line_id.in_(line_ids) if line_ids else False, SceneAssetModel.deleted_at.is_(None))
                .order_by(SceneAssetModel.created_at)
            )
        )
        .scalars()
        .all()
    ):
        scenes_by_line.setdefault(asset.storyboard_line_id, []).append(asset)
    shots_by_line: dict[str, list[ShotAssetModel]] = {}
    for asset in (
        (
            await db.execute(
                select(ShotAssetModel)
                .where(ShotAssetModel.storyboard_line_id.in_(line_ids) if line_ids else False, ShotAssetModel.deleted_at.is_(None))
                .order_by(ShotAssetModel.created_at)
            )
        )
        .scalars()
        .all()
    ):
        shots_by_line.setdefault(asset.storyboard_line_id, []).append(asset)
    voices_by_line: dict[str, list[VoiceAssetModel]] = {}
    for asset in (
        (
            await db.execute(
                select(VoiceAssetModel)
                .where(VoiceAssetModel.storyboard_line_id.in_(line_ids) if line_ids else False, VoiceAssetModel.deleted_at.is_(None))
                .order_by(VoiceAssetModel.created_at)
            )
        )
        .scalars()
        .all()
    ):
        voices_by_line.setdefault(asset.storyboard_line_id, []).append(asset)
    return {
        **task_json(task),
        "cast": [item.digital_human_id for item in cast],
        "lines": [
            _line_json_from_assets(
                line,
                casts.get(line.id, []),
                scenes_by_line.get(line.id, []),
                shots_by_line.get(line.id, []),
                voices_by_line.get(line.id, []),
                include_history=history,
            )
            for line in lines
        ],
    }


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, payload: TaskUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = await owned_task(db, user.id, task_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return task_json(item)


async def _apply_story_bible_to_lines(db: AsyncSession, lines: list[StoryboardLineModel], plans: list[dict], *, now) -> None:
    line_ids = [line.id for line in lines]
    await db.execute(
        update(StoryboardLineCastModel).where(StoryboardLineCastModel.storyboard_line_id.in_(line_ids), StoryboardLineCastModel.deleted_at.is_(None)).values(deleted_at=now)
    )
    for line, plan in zip(lines, plans, strict=True):
        line.shot_type = plan["shotType"]
        line.planned_duration = float(plan["generationDuration"])
        line.shot_options = {
            **(line.shot_options or {}),
            "duration": normalize_video_duration(line.planned_duration),
            "sourceDuration": plan["sourceDuration"],
            "gapBefore": plan["gapBefore"],
            "gapAfter": plan["gapAfter"],
            "gapAfterAllocation": plan["gapAfterAllocation"],
            "materialDuration": plan["materialDuration"],
            "outlineIntent": plan["intent"],
            "locationId": plan["locationId"],
            "locationChange": plan["locationChange"],
            "characterAction": plan["characterAction"],
            "emotionalFocus": plan["emotionalFocus"],
            "cameraPurpose": plan["cameraPurpose"],
            "motifIds": plan["motifIds"],
            "outlineStatus": plan.get("outlineStatus", "ready"),
            "sceneIndex": plan.get("sceneIndex"),
        }
        line.scene_prompt = ""
        line.shot_prompt = ""
        line.generation_status = "pending"
        line.generation_error = None
        line.prompt_context_hash = None
        for index, human_id in enumerate(plan["requiredCharacterIds"]):
            db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=index))


def _persist_llm_calls(
    db: AsyncSession,
    calls: list[dict] | None,
    *,
    default_operation: str,
    user_id: str,
    project_id: str | None,
    project_task_id: str | None,
    storyboard_line_id: str | None = None,
    generation_job_id: str | None = None,
    operation_suffix: str = "",
) -> None:
    """把一次 LLM 编排的调用记录同时落 token 账本与 llm_call_logs 全量留痕（请求快照、返回原文、耗时）。"""
    for call in calls or []:
        operation = f"{call.get('operation') or default_operation}{operation_suffix}"
        add_token_usage(
            db,
            operation=operation,
            provider="openai-compatible",
            model=settings.llm_model,
            usage=call.get("usage"),
            user_id=user_id,
            project_id=project_id,
            project_task_id=project_task_id,
            storyboard_line_id=storyboard_line_id,
            generation_job_id=generation_job_id,
            request_id=call.get("requestId"),
        )
        add_llm_call_log(
            db,
            operation=operation,
            provider="openai-compatible",
            model=settings.llm_model,
            usage=call.get("usage"),
            user_id=user_id,
            project_id=project_id,
            project_task_id=project_task_id,
            storyboard_line_id=storyboard_line_id,
            generation_job_id=generation_job_id,
            request_id=call.get("requestId"),
            status=call.get("status") or "ok",
            error=call.get("error") or "",
            duration_ms=int(call.get("durationMs") or 0),
            request_messages=call.get("requestMessages"),
            response_text=call.get("responseText") or "",
            prompt_key=call.get("promptKey") or "",
            prompt_version=int(call.get("promptVersion") or 0),
        )


# 持有大纲后台生成任务的强引用，避免被事件循环 GC（同 chat.py 的 tasks 表惯例）
_outline_background_tasks: set[asyncio.Task] = set()
_segment_retry_tasks: set[asyncio.Task] = set()


async def _outline_heartbeat(task_id: str) -> None:
    """大纲生成租约心跳。

    LLM 单次请求期间也定期刷新 updated_at；进程退出后心跳停止，
    全局巡检器才能安全地把超时 outlining 判定为僵尸任务。
    """
    while True:
        await asyncio.sleep(30)
        async with session_factory() as session:
            task = await session.get(ProjectTaskModel, task_id)
            if not task or task.deleted_at is not None or task.status != "outlining":
                return
            config = dict(task.storyboard_config or {})
            progress = dict(config.get("outlineProgress") or {})
            progress["heartbeatAt"] = utcnow().isoformat()
            config["outlineProgress"] = progress
            task.storyboard_config = config
            await session.commit()


def _start_outline_background(task_id: str, operation: Coroutine[Any, Any, None]) -> None:
    async def supervised() -> None:
        heartbeat = asyncio.create_task(_outline_heartbeat(task_id))
        try:
            await operation
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat

    background = asyncio.create_task(supervised())
    _outline_background_tasks.add(background)
    background.add_done_callback(_outline_background_tasks.discard)


async def _run_ass_outline_generation(
    *,
    task_id: str,
    user_id: str,
    project_id: str,
    segments: list[dict],
    selected_humans: list[dict],
    role_ids: list[str],
    emotion: dict,
    extra_requirement: str,
) -> None:
    """后台执行 ASS 两轮大纲生成；进度写 storyboard_config.outlineProgress 供 SSE 轮询推送。"""

    async def on_progress(progress: dict) -> None:
        async with session_factory() as progress_session:
            item = await progress_session.get(ProjectTaskModel, task_id)
            if not item or item.deleted_at is not None:
                return
            config = dict(item.storyboard_config or {})
            config["outlineProgress"] = progress
            item.storyboard_config = config
            await progress_session.commit()

    async with session_factory() as session:
        task = await session.get(ProjectTaskModel, task_id)
        if not task or task.deleted_at is not None:
            return
        try:
            outline = await generate_ass_story_outline(
                segments=segments,
                emotion=emotion,
                selected_humans=selected_humans,
                extra_requirement=extra_requirement,
                on_progress=on_progress,
            )
        except Exception as exc:
            _persist_llm_calls(
                session,
                getattr(exc, "usage_records", None),
                default_operation="ass_scene_plan",
                user_id=user_id,
                project_id=project_id,
                project_task_id=task_id,
                operation_suffix="_failed",
            )
            config = dict(task.storyboard_config or {})
            config["outlineProgress"] = {"phase": "error", "segmentsDone": 0, "segmentsTotal": 0, "error": f"ASS 分镜大纲生成失败：{exc}"[:300]}
            task.storyboard_config = config
            task.status = "outline_failed"
            await session.commit()
            return
        story_bible = await build_ass_story_bible(
            segments=segments,
            emotion=emotion,
            role_ids=role_ids,
            extra_requirement=extra_requirement,
            outline=outline,
        )
        lines = list(
            (
                await session.execute(
                    select(StoryboardLineModel)
                    .where(StoryboardLineModel.project_task_id == task_id, StoryboardLineModel.deleted_at.is_(None))
                    .order_by(StoryboardLineModel.sort_order)
                )
            )
            .scalars()
            .all()
        )
        config = dict(task.storyboard_config or {})
        config["storyBible"] = story_bible
        config.pop("outlineProgress", None)
        task.storyboard_config = config
        task.status = "generating"
        await _apply_story_bible_to_lines(session, lines, story_bible["shots"], now=utcnow())
        _persist_llm_calls(
            session,
            outline["usageRecords"],
            default_operation="ass_story_outline",
            user_id=user_id,
            project_id=project_id,
            project_task_id=task_id,
        )
        await session.commit()


async def _apply_general_outline_to_lines(db: AsyncSession, lines: list[StoryboardLineModel], shots: list[dict], durations: list[float]) -> None:
    """将通用分镜大纲结果回填到占位 lines（镜头类型、人物、时长与大纲字段）。"""
    now = utcnow()
    line_ids = [line.id for line in lines]
    await db.execute(
        update(StoryboardLineCastModel).where(StoryboardLineCastModel.storyboard_line_id.in_(line_ids), StoryboardLineCastModel.deleted_at.is_(None)).values(deleted_at=now)
    )
    for line, shot, duration in zip(lines, shots, durations, strict=True):
        line.shot_type = shot["shotType"]
        line.planned_duration = duration
        line.shot_options = {
            **(line.shot_options or {}),
            "duration": normalize_video_duration(duration),
            "outlineScene": shot["outlineScene"],
            "outlineShot": shot["outlineShot"],
            "outlineIntent": shot["intent"],
            "characterAction": shot["characterAction"],
            "emotionalFocus": shot["emotionalFocus"],
            "cameraPurpose": shot["cameraPurpose"],
            "outlineStatus": "ready",
        }
        line.generation_status = "pending"
        line.generation_error = None
        line.prompt_context_hash = None
        for index, human_id in enumerate(shot["requiredCharacterIds"]):
            db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=index))


async def _run_general_outline_generation(
    *,
    task_id: str,
    user_id: str,
    project_id: str,
    selected_humans: list[dict],
) -> None:
    """后台执行通用分镜大纲生成；进度写 storyboard_config.outlineProgress 供 SSE 轮询推送。"""

    async def on_progress(progress: dict) -> None:
        async with session_factory() as progress_session:
            item = await progress_session.get(ProjectTaskModel, task_id)
            if not item or item.deleted_at is not None:
                return
            config = dict(item.storyboard_config or {})
            config["outlineProgress"] = progress
            item.storyboard_config = config
            await progress_session.commit()

    async with session_factory() as session:
        task = await session.get(ProjectTaskModel, task_id)
        if not task or task.deleted_at is not None:
            return
        config = dict(task.storyboard_config or {})
        empty_count = int(config.get("empty_shot_count", 0))
        character_count = int(config.get("character_shot_count", 0))
        total = empty_count + character_count
        try:
            durations = exact_durations(config.get("total_duration", 0), total)
        except ValueError:
            if total:
                durations = [float(config.get("total_duration", 0)) / total] * total
            else:
                durations = []
        try:
            outline = await generate_general_story_outline(config=config, selected_humans=selected_humans, on_progress=on_progress)
        except Exception as exc:
            _persist_llm_calls(
                session,
                getattr(exc, "usage_records", None),
                default_operation="general_story_outline",
                user_id=user_id,
                project_id=project_id,
                project_task_id=task_id,
                operation_suffix="_failed",
            )
            failed_config = dict(task.storyboard_config or {})
            failed_config["outlineProgress"] = {"phase": "error", "shotsDone": 0, "shotsTotal": total, "error": f"通用分镜大纲生成失败：{exc}"[:300]}
            task.storyboard_config = failed_config
            task.status = "outline_failed"
            await session.commit()
            return
        story_bible = await build_general_story_bible(config=config, shots=outline["shots"], durations=durations)
        lines = list(
            (
                await session.execute(
                    select(StoryboardLineModel)
                    .where(StoryboardLineModel.project_task_id == task_id, StoryboardLineModel.deleted_at.is_(None))
                    .order_by(StoryboardLineModel.sort_order)
                )
            )
            .scalars()
            .all()
        )
        done_config = dict(task.storyboard_config or {})
        done_config["storyBible"] = story_bible
        done_config.pop("outlineProgress", None)
        task.storyboard_config = done_config
        task.status = "generating"
        await _apply_general_outline_to_lines(session, lines, outline["shots"], durations)
        _persist_llm_calls(
            session,
            outline["usageRecords"],
            default_operation="general_story_outline",
            user_id=user_id,
            project_id=project_id,
            project_task_id=task_id,
        )
        await session.commit()


@router.post("/tasks/{task_id}/storyboard-outline/regenerate", status_code=202)
async def regenerate_storyboard_outline(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    if task.storyboard_type not in ("ass", "general"):
        raise HTTPException(422, "该分镜类型不支持生成全局大纲")
    if task.status == "outlining":
        # 进度回调会持续刷新 updated_at；超过阈值未刷新视为后台任务丢失（服务重启等）的僵尸状态，放行重新生成
        # sqlite 读回的 updated_at 不带时区，与 aware 的 utcnow 相减前需要补齐
        updated_at = task.updated_at
        if updated_at and updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=utcnow().tzinfo)
        stale_seconds = (utcnow() - updated_at).total_seconds() if updated_at else 999999
        if stale_seconds < 150:
            raise HTTPException(409, "分镜大纲正在生成中，请等待本轮完成后再提交")
    cast_links = list(
        (await db.execute(select(ProjectCastModel).where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None)).order_by(ProjectCastModel.sort_order)))
        .scalars()
        .all()
    )
    role_ids = [item.digital_human_id for item in cast_links]
    humans = await visible_humans(db, user.id, role_ids)
    human_by_id = {item.id: item for item in humans}
    selected_humans = [
        {
            "id": item.id,
            "name": item.name,
            "gender": item.gender,
            "ageDescription": item.age_description,
            "appearanceStyle": item.appearance_style,
            "clothingDescription": item.clothing_description,
            "systemPrompt": item.system_prompt or item.avatar_prompt or item.description,
        }
        for human_id in role_ids
        if (item := human_by_id.get(human_id))
    ]
    if not selected_humans:
        raise HTTPException(422, "该任务还未选择人物，请先在人物栏选择人物后再生成分镜大纲")
    await consume_daily_quota(db, user_id=user.id, category="chat")

    if task.storyboard_type == "general":
        config = dict(task.storyboard_config or {})
        shots_total = int(config.get("empty_shot_count", 0)) + int(config.get("character_shot_count", 0))
        progress = {"phase": "generating", "shotsDone": 0, "shotsTotal": shots_total, "startedAt": utcnow().isoformat()}
        config["outlineProgress"] = progress
        task.storyboard_config = config
        task.status = "outlining"
        await db.commit()
        _start_outline_background(
            task.id,
            _run_general_outline_generation(
                task_id=task.id,
                user_id=user.id,
                project_id=task.project_id,
                selected_humans=selected_humans,
            ),
        )
        return {"taskId": task.id, "status": "outlining", "progress": progress}

    lines = list(
        (
            await db.execute(
                select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    segments = [
        {
            "index": line.sort_order,
            "start": line.start_time,
            "end": line.end_time,
            "lyrics": line.lyrics,
            "segmentType": (line.shot_options or {}).get("segmentType", "lyric"),
            "timelineLabel": (line.shot_options or {}).get("timelineLabel") or line.lyrics,
        }
        for line in lines
    ]
    progress = {"phase": "planning", "segmentsDone": 0, "segmentsTotal": 0, "startedAt": utcnow().isoformat()}
    config = dict(task.storyboard_config or {})
    config["outlineProgress"] = progress
    task.storyboard_config = config
    task.status = "outlining"
    await db.commit()
    _start_outline_background(
        task.id,
        _run_ass_outline_generation(
            task_id=task.id,
            user_id=user.id,
            project_id=task.project_id,
            segments=segments,
            selected_humans=selected_humans,
            role_ids=role_ids,
            emotion=(task.storyboard_config or {}).get("songEmotion") or {},
            extra_requirement=task.extra_requirement or "",
        ),
    )
    return {"taskId": task.id, "status": "outlining", "progress": progress}


@router.get("/tasks/{task_id}/storyboard-outline/events")
async def storyboard_outline_events(task_id: str, request: Request, user: CurrentUser, db: AsyncSession = Db) -> StreamingResponse:
    """大纲生成进度的 SSE 推送：轮询任务行的 status 与 outlineProgress，终态后关闭。"""
    await owned_task(db, user.id, task_id)

    async def stream():
        last = None
        while not await request.is_disconnected():
            async with session_factory() as session:
                current = (
                    await session.execute(
                        select(ProjectTaskModel)
                        .join(ProjectModel, ProjectModel.id == ProjectTaskModel.project_id)
                        .where(
                            ProjectTaskModel.id == task_id,
                            ProjectTaskModel.deleted_at.is_(None),
                            ProjectModel.user_id == user.id,
                            ProjectModel.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if not current:
                    return
                progress = (current.storyboard_config or {}).get("outlineProgress") or {}
                has_outline = current.status == "outlining"
                has_segment_retry = progress.get("phase") == "segment_retry"
                marker = (current.status, json.dumps(progress, sort_keys=True, ensure_ascii=False))
                if marker != last:
                    payload = {"type": "outline", "taskId": task_id, "status": current.status, "progress": progress}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last = marker
                if not has_outline and not has_segment_retry:
                    return
            await asyncio.sleep(0.75)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


async def _run_segment_retry(
    *,
    task_id: str,
    scene_index: int,
    segments: list[dict],
    scene_plan: list[dict],
    story_bible: dict[str, Any],
    selected_humans: list[dict],
    extra_requirement: str,
    emotion: dict,
    role_ids: list[str],
    user_id: str,
    project_id: str,
) -> None:
    """后台执行单个场景段的重新生成，完成后更新 storyBible 与分镜行。"""
    old_shots = list(story_bible.get("shots") or [])
    try:
        result = await regenerate_ass_scene_segment(
            segments=segments,
            scene_plan=scene_plan,
            scene_index=scene_index,
            global_visual=story_bible.get("globalVisual") or {},
            emotion=emotion,
            selected_humans=selected_humans,
            extra_requirement=extra_requirement,
        )
    except Exception as exc:
        async with session_factory() as session:
            task = await session.get(ProjectTaskModel, task_id)
            if not task or task.deleted_at is not None:
                return
            _persist_llm_calls(session, getattr(exc, "usage_records", None), default_operation="ass_scene_segment", user_id=user_id, project_id=project_id, project_task_id=task_id)
            config = dict(task.storyboard_config or {})
            config["outlineProgress"] = {"phase": "segment_retry_failed", "sceneIndex": scene_index, "error": str(exc)[:300]}
            task.storyboard_config = config
            await session.commit()
        return
    async with session_factory() as session:
        task = await session.get(ProjectTaskModel, task_id)
        if not task or task.deleted_at is not None:
            return
        lines = list(
            (
                await session.execute(
                    select(StoryboardLineModel)
                    .where(StoryboardLineModel.project_task_id == task_id, StoryboardLineModel.deleted_at.is_(None))
                    .order_by(StoryboardLineModel.sort_order)
                )
            )
            .scalars()
            .all()
        )
        shot_start, shot_count = result["shotStart"], result["shotCount"]
        updated_shots = old_shots[:shot_start] + result["shots"] + old_shots[shot_start + shot_count :]
        for position, shot in enumerate(updated_shots):
            shot["index"] = position
        finalize_shot_durations(updated_shots, segments)
        prefix = f"s{scene_index + 1}."
        merged_outline = {
            "globalVisual": story_bible.get("globalVisual"),
            "locations": story_bible.get("locations") or [],
            "motifs": [m for m in (story_bible.get("motifs") or []) if not str(m.get("id") or "").startswith(prefix)] + result["motifs"],
            "scenePlan": scene_plan,
            "failedSegments": [item for item in (story_bible.get("failedSegments") or []) if item.get("sceneIndex") != scene_index],
            "shots": updated_shots,
        }
        new_bible = await build_ass_story_bible(
            segments=segments,
            emotion=emotion,
            role_ids=role_ids,
            extra_requirement=extra_requirement or "",
            outline=merged_outline,
        )
        config = dict(task.storyboard_config or {})
        config["storyBible"] = new_bible
        config.pop("outlineProgress", None)
        task.storyboard_config = config
        target_lines = lines[shot_start : shot_start + shot_count]
        segment_plans = new_bible["shots"][shot_start : shot_start + shot_count]
        await _apply_story_bible_to_lines(session, target_lines, segment_plans, now=utcnow())
        _persist_llm_calls(session, result["usageRecords"], default_operation="ass_scene_segment", user_id=user_id, project_id=project_id, project_task_id=task_id)
        await session.commit()


@router.post("/tasks/{task_id}/storyboard-outline/segments/{scene_index}/regenerate", status_code=202)
async def regenerate_storyboard_outline_segment(task_id: str, scene_index: int, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    if task.storyboard_type != "ass":
        raise HTTPException(422, "只有 ASS 分镜支持场景段重试")
    story_bible = dict((task.storyboard_config or {}).get("storyBible") or {})
    scene_plan = story_bible.get("scenePlan") or []
    if not 0 <= scene_index < len(scene_plan):
        raise HTTPException(422, "场景段序号超出范围")
    lines = list(
        (
            await db.execute(
                select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    cast_links = list(
        (await db.execute(select(ProjectCastModel).where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None)).order_by(ProjectCastModel.sort_order)))
        .scalars()
        .all()
    )
    role_ids = [item.digital_human_id for item in cast_links]
    humans = await visible_humans(db, user.id, role_ids)
    human_by_id = {item.id: item for item in humans}
    selected_humans = [
        {
            "id": item.id,
            "name": item.name,
            "gender": item.gender,
            "ageDescription": item.age_description,
            "appearanceStyle": item.appearance_style,
            "clothingDescription": item.clothing_description,
            "systemPrompt": item.system_prompt or item.avatar_prompt or item.description,
        }
        for human_id in role_ids
        if (item := human_by_id.get(human_id))
    ]
    if not selected_humans:
        raise HTTPException(422, "该任务还未选择人物，请先在人物栏选择人物后再重试场景段")
    segments = [
        {
            "index": line.sort_order,
            "start": line.start_time,
            "end": line.end_time,
            "lyrics": line.lyrics,
            "segmentType": (line.shot_options or {}).get("segmentType", "lyric"),
            "timelineLabel": (line.shot_options or {}).get("timelineLabel") or line.lyrics,
        }
        for line in lines
    ]
    old_shots = list(story_bible.get("shots") or [])
    if len(old_shots) != len(segments):
        raise HTTPException(422, "分镜数据与时间轴不一致，请重新生成全局大纲")
    # 幂等：该场景段正在后台重试中
    current_progress = (task.storyboard_config or {}).get("outlineProgress") or {}
    if current_progress.get("phase") == "segment_retry" and current_progress.get("sceneIndex") == scene_index:
        raise HTTPException(409, "该场景段正在重新生成中，请等待本轮完成后再提交")
    await consume_daily_quota(db, user_id=user.id, category="chat")
    emotion = (task.storyboard_config or {}).get("songEmotion") or {}
    progress = {"phase": "segment_retry", "sceneIndex": scene_index, "startedAt": utcnow().isoformat()}
    config = dict(task.storyboard_config or {})
    config["outlineProgress"] = progress
    task.storyboard_config = config
    await db.commit()
    background = asyncio.create_task(
        _run_segment_retry(
            task_id=task.id,
            scene_index=scene_index,
            segments=segments,
            scene_plan=scene_plan,
            story_bible=story_bible,
            selected_humans=selected_humans,
            extra_requirement=task.extra_requirement or "",
            emotion=emotion,
            role_ids=role_ids,
            user_id=user.id,
            project_id=task.project_id,
        )
    )
    _segment_retry_tasks.add(background)
    background.add_done_callback(_segment_retry_tasks.discard)
    return {"taskId": task.id, "sceneIndex": scene_index, "status": "segment_retrying", "progress": progress}


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = await owned_task(db, user.id, task_id)
    await soft_delete_task_tree(db, [item.id], utcnow())
    await db.commit()
    return {"ok": True}


@router.get("/digital-human-styles")
async def list_styles(user: CurrentUser, db: AsyncSession = Db) -> list[dict]:
    items = list(
        (
            await db.execute(
                select(DigitalHumanStyleModel)
                .where(DigitalHumanStyleModel.deleted_at.is_(None), or_(DigitalHumanStyleModel.scope == "system", DigitalHumanStyleModel.user_id == user.id))
                .order_by(DigitalHumanStyleModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return [{"id": item.id, "name": item.name, "scope": item.scope, "readOnly": item.scope == "system"} for item in items]


@router.post("/digital-human-styles", status_code=201)
async def create_style(payload: StyleCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = DigitalHumanStyleModel(id=uid("style"), user_id=user.id, name=payload.name.strip(), scope="private")
    db.add(item)
    await db.commit()
    return {"id": item.id, "name": item.name, "scope": item.scope, "readOnly": False}


@router.delete("/digital-human-styles/{style_id}")
async def delete_style(style_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    result = await db.execute(
        select(DigitalHumanStyleModel).where(
            DigitalHumanStyleModel.id == style_id, DigitalHumanStyleModel.user_id == user.id, DigitalHumanStyleModel.scope == "private", DigitalHumanStyleModel.deleted_at.is_(None)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "分类不存在")
    item.deleted_at = utcnow()
    await db.execute(
        update(DigitalHumanModel).where(DigitalHumanModel.style_id == style_id, DigitalHumanModel.user_id == user.id, DigitalHumanModel.deleted_at.is_(None)).values(style_id=None)
    )
    await db.commit()
    return {"ok": True}


def human_json(item: DigitalHumanModel, style_name: str | None = None) -> dict:
    return {
        "id": item.id,
        "name": item.name,
        "styleId": item.style_id,
        "style": style_name or "未分类",
        "avatar": item.avatar_thumbnail_url or item.avatar_url,
        "originalAvatar": item.avatar_url,
        "assetAvatarUrl": item.asset_avatar_url,
        "description": item.description,
        "avatarPrompt": item.avatar_prompt,
        "assetCode": item.asset_code,
        "gender": item.gender,
        "ageDescription": item.age_description,
        "appearanceStyle": item.appearance_style,
        "clothingDescription": item.clothing_description,
        "suitableMusicStyles": item.suitable_music_styles,
        "systemPrompt": item.system_prompt,
        "scope": item.scope,
        "readOnly": item.scope == "system",
    }


@router.get("/digital-humans")
async def list_humans(user: CurrentUser, db: AsyncSession = Db) -> list[dict]:
    items = await visible_humans(db, user.id)
    style_ids = [item.style_id for item in items if item.style_id]
    styles = {
        item.id: item.name for item in (await db.execute(select(DigitalHumanStyleModel).where(DigitalHumanStyleModel.id.in_(style_ids) if style_ids else False))).scalars().all()
    }
    return [human_json(item, styles.get(item.style_id)) for item in items]


async def _sync_human_asset_avatar(human: DigitalHumanModel) -> None:
    """为数字人注册 AIGC 平台虚拟资产（asset://），生成视频时用于过真人人脸校验。

    同步等待上游 Active（约数秒）；失败只记录日志，降级继续用原始 TOS 路径。
    换图后旧 asset 失效：调用方需先清空 asset_avatar_url 再传新 avatar_url。
    """
    from .error_logging import log_background_error
    from .providers import create_real_face_asset

    if not human.avatar_url or human.asset_avatar_url:
        return
    try:
        # 同步等待上游 Active，但设上限避免接口长时间阻塞；超时降级走 TOS 路径，由启动任务兜底补注册
        asset_url = await asyncio.wait_for(
            create_real_face_asset(human.avatar_url, name=f"mv-{human.asset_code or human.id}"),
            timeout=30,
        )
    except Exception as exc:
        await log_background_error(
            user_id=human.user_id,
            path="/virtual/assets/create",
            error_type="AssetError",
            message=f"digital human asset create failed: {human.id}: {exc}",
        )
        return
    human.asset_avatar_url = asset_url


@router.post("/digital-humans", status_code=201)
async def create_human(payload: DigitalHumanCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    if not is_tos_url(payload.avatar_url) or (payload.avatar_thumbnail_url and not is_tos_url(payload.avatar_thumbnail_url)):
        raise HTTPException(422, "角色图片必须先上传到配置的 TOS")
    style = None
    if payload.style_id:
        style = await db.get(DigitalHumanStyleModel, payload.style_id)
        if not style or style.deleted_at is not None or (style.scope != "system" and style.user_id != user.id):
            raise HTTPException(422, "角色分类不可用")
    item = DigitalHumanModel(id=uid("dh"), user_id=user.id, scope="private", **payload.model_dump())
    db.add(item)
    await db.commit()
    # 用户上传/生成的三视图同样注册平台虚拟资产，生成视频时用 asset:// 过真人人脸校验
    await _sync_human_asset_avatar(item)
    await db.commit()
    return human_json(item, style.name if style else None)


@router.patch("/digital-humans/{human_id}")
async def update_human(human_id: str, payload: DigitalHumanUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    result = await db.execute(
        select(DigitalHumanModel).where(
            DigitalHumanModel.id == human_id, DigitalHumanModel.user_id == user.id, DigitalHumanModel.scope == "private", DigitalHumanModel.deleted_at.is_(None)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "私有角色不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key in {"avatar_url", "avatar_thumbnail_url"} and value and not is_tos_url(str(value)):
            raise HTTPException(422, "角色图片必须存储在配置的 TOS")
        setattr(item, key, value)
    # 换图后旧资产链接失效：清空后重新注册，确保 asset:// 始终对应当前头像
    if "avatar_url" in payload.model_dump(exclude_unset=True):
        item.asset_avatar_url = None
        await db.commit()
        await _sync_human_asset_avatar(item)
    await db.commit()
    return human_json(item)


@router.delete("/digital-humans/{human_id}")
async def delete_human(human_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    result = await db.execute(
        select(DigitalHumanModel).where(
            DigitalHumanModel.id == human_id, DigitalHumanModel.user_id == user.id, DigitalHumanModel.scope == "private", DigitalHumanModel.deleted_at.is_(None)
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "私有角色不存在")
    item.deleted_at = utcnow()
    now = item.deleted_at
    await db.execute(update(ProjectCastModel).where(ProjectCastModel.digital_human_id == human_id, ProjectCastModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.execute(
        update(StoryboardLineCastModel).where(StoryboardLineCastModel.digital_human_id == human_id, StoryboardLineCastModel.deleted_at.is_(None)).values(deleted_at=now)
    )
    await db.commit()
    return {"ok": True}


@router.put("/tasks/{task_id}/cast")
async def replace_cast(task_id: str, payload: CastUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    await owned_task(db, user.id, task_id)
    visible = await visible_humans(db, user.id, payload.digital_human_ids)
    if len({item.id for item in visible}) != len(set(payload.digital_human_ids)):
        raise HTTPException(422, "包含不可用角色")
    old = list((await db.execute(select(ProjectCastModel).where(ProjectCastModel.project_task_id == task_id, ProjectCastModel.deleted_at.is_(None)))).scalars().all())
    now = utcnow()
    for item in old:
        item.deleted_at = now
    for index, human_id in enumerate(payload.digital_human_ids):
        db.add(ProjectCastModel(id=uid("cast"), project_task_id=task_id, digital_human_id=human_id, sort_order=index))
    await db.commit()
    return {"cast": payload.digital_human_ids}


@router.post("/tasks/{task_id}/storyboard/lines", status_code=201)
async def create_line(task_id: str, payload: StoryboardLineCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    await owned_task(db, user.id, task_id)
    visible = await visible_humans(db, user.id, payload.digital_human_ids)
    if len({item.id for item in visible}) != len(set(payload.digital_human_ids)):
        raise HTTPException(422, "包含不可用角色")
    count = len((await db.execute(select(StoryboardLineModel.id).where(StoryboardLineModel.project_task_id == task_id, StoryboardLineModel.deleted_at.is_(None)))).all())
    data = payload.model_dump(exclude={"digital_human_ids"})
    line = StoryboardLineModel(id=uid("line"), project_task_id=task_id, sort_order=count, generation_status="succeeded", generated_at=utcnow(), **data)
    db.add(line)
    await db.flush()
    for index, human_id in enumerate(payload.digital_human_ids):
        db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=index))
    await db.commit()
    return await line_json(db, line, payload.digital_human_ids)


@router.patch("/storyboard-lines/{line_id}")
async def update_line(line_id: str, payload: StoryboardLineUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    line = await owned_line(db, user.id, line_id)
    data = payload.model_dump(exclude_unset=True, exclude={"digital_human_ids"})
    for key, value in data.items():
        setattr(line, key, value)
    if payload.digital_human_ids is not None:
        visible = await visible_humans(db, user.id, payload.digital_human_ids)
        if len({item.id for item in visible}) != len(set(payload.digital_human_ids)):
            raise HTTPException(422, "包含不可用角色")
        old = list(
            (await db.execute(select(StoryboardLineCastModel).where(StoryboardLineCastModel.storyboard_line_id == line.id, StoryboardLineCastModel.deleted_at.is_(None))))
            .scalars()
            .all()
        )
        for item in old:
            item.deleted_at = utcnow()
        for index, human_id in enumerate(payload.digital_human_ids):
            db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=index))
    await db.commit()
    return await line_json(db, line, payload.digital_human_ids or [])


@router.delete("/storyboard-lines/{line_id}")
async def delete_line(line_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    line = await owned_line(db, user.id, line_id)
    now = utcnow()
    line.deleted_at = now
    for model in (StoryboardLineCastModel, SceneAssetModel, ShotAssetModel, VoiceAssetModel):
        await db.execute(update(model).where(model.storyboard_line_id == line.id, model.deleted_at.is_(None)).values(deleted_at=now))
    await db.execute(update(GenerationJobModel).where(GenerationJobModel.storyboard_line_id == line.id, GenerationJobModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.commit()
    return {"ok": True}


@router.post("/tasks/{task_id}/storyboard/reorder")
async def reorder_lines(task_id: str, payload: ReorderLines, user: CurrentUser, db: AsyncSession = Db) -> dict:
    await owned_task(db, user.id, task_id)
    lines = list((await db.execute(select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task_id, StoryboardLineModel.deleted_at.is_(None)))).scalars().all())
    if {line.id for line in lines} != set(payload.line_ids):
        raise HTTPException(422, "分镜列表不完整或包含其他任务的分镜")
    by_id = {line.id: line for line in lines}
    for index, line_id in enumerate(payload.line_ids):
        by_id[line_id].sort_order = index
    await db.commit()
    return {"ok": True}


def _line_json_from_assets(
    line: StoryboardLineModel,
    cast: list[str],
    scenes: list[SceneAssetModel],
    shots: list[ShotAssetModel],
    voices: list[VoiceAssetModel],
    *,
    include_history: bool = True,
) -> dict:
    """组装单行脚本 JSON（纯函数，资产由调用方预取）。

    include_history=False 时每类资产只回传当前选用项并附历史版本计数（P2 响应裁剪；
    完整历史经 GET /tasks/{task_id}/storyboard-lines/{line_id} 按需获取）。
    """
    scene_items = [{"id": a.id, "imageUrl": a.image_thumbnail_url or a.image_url, "originalImageUrl": a.image_url, "isCurrent": a.is_current} for a in scenes]
    shot_items = [
        {
            "id": a.id,
            "coverUrl": a.cover_thumbnail_url or a.cover_url,
            "originalCoverUrl": a.cover_url,
            "videoUrl": a.video_url,
            "duration": a.duration,
            "resolution": a.resolution,
            "ratio": a.ratio,
            "isCurrent": a.is_current,
        }
        for a in shots
    ]
    voice_items = [{"id": a.id, "url": a.audio_url, "duration": a.duration, "isCurrent": a.is_current} for a in voices]
    payload = {
        "id": line.id,
        "source": line.source,
        "shotType": line.shot_type,
        "plannedDuration": line.planned_duration,
        "lyrics": line.lyrics,
        "lyricsZh": line.lyrics_zh,
        "start": line.start_time,
        "end": line.end_time,
        "scenePrompt": line.scene_prompt,
        "shotPrompt": line.shot_prompt,
        "shotOptions": line.shot_options,
        "generationStatus": line.generation_status,
        "generationError": line.generation_error,
        "generationAttempt": line.generation_attempt,
        "generatedAt": line.generated_at.isoformat() if line.generated_at else None,
        "digitalHumanIds": cast,
        "sceneAssets": scene_items,
        "shotAssets": shot_items,
        "voiceAssets": voice_items,
    }
    if not include_history:
        payload["sceneAssets"] = [item for item in scene_items if item["isCurrent"]]
        payload["shotAssets"] = [item for item in shot_items if item["isCurrent"]]
        payload["voiceAssets"] = [item for item in voice_items if item["isCurrent"]]
        payload["sceneAssetCount"] = len(scenes)
        payload["shotAssetCount"] = len(shots)
        payload["voiceAssetCount"] = len(voices)
    return payload


async def line_json(db: AsyncSession, line: StoryboardLineModel, cast: list[str]) -> dict:
    scenes = list(
        (await db.execute(select(SceneAssetModel).where(SceneAssetModel.storyboard_line_id == line.id, SceneAssetModel.deleted_at.is_(None)).order_by(SceneAssetModel.created_at)))
        .scalars()
        .all()
    )
    shots = list(
        (await db.execute(select(ShotAssetModel).where(ShotAssetModel.storyboard_line_id == line.id, ShotAssetModel.deleted_at.is_(None)).order_by(ShotAssetModel.created_at)))
        .scalars()
        .all()
    )
    voices = list(
        (await db.execute(select(VoiceAssetModel).where(VoiceAssetModel.storyboard_line_id == line.id, VoiceAssetModel.deleted_at.is_(None)).order_by(VoiceAssetModel.created_at)))
        .scalars()
        .all()
    )
    return _line_json_from_assets(line, cast, scenes, shots, voices)


@router.get("/tasks/{task_id}/storyboard-lines/{line_id}")
async def get_storyboard_line(task_id: str, line_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    """单行全量（含完整资产历史）：生成落定后的增量合并 / 详情弹窗懒加载历史版本（P2）。"""
    task = await owned_task(db, user.id, task_id)
    line = await owned_line(db, user.id, line_id)
    if line.project_task_id != task.id:
        raise HTTPException(422, "分镜不属于指定子项目")
    line_cast = list(
        (
            await db.execute(
                select(StoryboardLineCastModel)
                .where(StoryboardLineCastModel.storyboard_line_id == line.id, StoryboardLineCastModel.deleted_at.is_(None))
                .order_by(StoryboardLineCastModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    return await line_json(db, line, [item.digital_human_id for item in line_cast])


async def _refresh_storyboard_status(db: AsyncSession, task: ProjectTaskModel) -> None:
    statuses = list(
        (await db.execute(select(StoryboardLineModel.generation_status).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    if statuses and all(value == "succeeded" for value in statuses):
        task.status = "ready"
    elif any(value == "succeeded" for value in statuses) and any(value == "failed" for value in statuses):
        task.status = "partial"
    elif statuses and all(value == "failed" for value in statuses):
        task.status = "failed"
    else:
        task.status = "generating"


@router.post("/tasks/{task_id}/storyboard-lines/{line_id}/generate")
async def generate_one_storyboard_line(task_id: str, line_id: str, payload: StoryboardLineGenerate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    line = await owned_line(db, user.id, line_id)
    if line.project_task_id != task.id:
        raise HTTPException(422, "分镜不属于指定子项目")
    if task.storyboard_type == "ass" and (line.shot_options or {}).get("outlineStatus") in {"pending", "failed"}:
        raise HTTPException(422, "该分镜所在场景段尚未生成大纲，请先生成分镜大纲")
    if line.generation_status == "running":
        raise HTTPException(409, "该分镜正在生成")
    # 单账号并行上限：统计该用户全部子项目中处于 running 的提示词生成行数，达到 100 拒绝受理
    running_count = int(
        (
            await db.execute(
                select(func.count(StoryboardLineModel.id))
                .join(ProjectTaskModel, StoryboardLineModel.project_task_id == ProjectTaskModel.id)
                .join(ProjectModel, ProjectTaskModel.project_id == ProjectModel.id)
                .where(
                    ProjectModel.user_id == user.id,
                    ProjectModel.deleted_at.is_(None),
                    ProjectTaskModel.deleted_at.is_(None),
                    StoryboardLineModel.deleted_at.is_(None),
                    StoryboardLineModel.generation_status == "running",
                )
            )
        ).scalar_one()
    )
    if running_count >= 100:
        raise HTTPException(429, "同时进行的提示词生成已达上限（100 条），请等待部分完成后再试")
    lines = list(
        (
            await db.execute(
                select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    cast_links = list(
        (await db.execute(select(ProjectCastModel).where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None)).order_by(ProjectCastModel.sort_order)))
        .scalars()
        .all()
    )
    task_cast_ids = [item.digital_human_id for item in cast_links]
    line_cast = list(
        (
            await db.execute(
                select(StoryboardLineCastModel)
                .where(StoryboardLineCastModel.storyboard_line_id == line.id, StoryboardLineCastModel.deleted_at.is_(None))
                .order_by(StoryboardLineCastModel.sort_order)
            )
        )
        .scalars()
        .all()
    )
    planned_role_ids = [item.digital_human_id for item in line_cast]
    allowed_ids = planned_role_ids if task.storyboard_type == "general" else task_cast_ids
    human_models = list(
        (await db.execute(select(DigitalHumanModel).where(DigitalHumanModel.id.in_(allowed_ids) if allowed_ids else False, DigitalHumanModel.deleted_at.is_(None)))).scalars().all()
    )
    human_by_id = {item.id: item for item in human_models}
    allowed_humans = [
        {
            "id": human.id,
            "name": human.name,
            "gender": human.gender,
            "ageDescription": human.age_description,
            "appearanceStyle": human.appearance_style,
            "clothingDescription": human.clothing_description,
            "suitableMusicStyles": human.suitable_music_styles,
            "systemPrompt": human.system_prompt or human.avatar_prompt or human.description,
        }
        for human_id in allowed_ids
        if (human := human_by_id.get(human_id))
    ]
    current = {
        "id": line.id,
        "index": line.sort_order,
        "lyrics": line.lyrics,
        "start": line.start_time,
        "end": line.end_time,
        "shotType": line.shot_type,
        "plannedDuration": line.planned_duration,
        "plannedDigitalHumanIds": planned_role_ids,
        "outline": line.shot_options,
    }
    if task.storyboard_type == "ass":
        full_context = {
            "songId": task.storyboard_config.get("songId"),
            "songEmotion": task.storyboard_config.get("songEmotion"),
            "storyBible": task.storyboard_config.get("storyBible"),
            "allLyrics": [{"index": item.sort_order, "lyrics": item.lyrics, "start": item.start_time, "end": item.end_time} for item in lines],
            "overallRequirement": task.extra_requirement,
        }
    else:
        full_context = {
            "storyboardConfig": task.storyboard_config,
            "shotOutline": [{"index": item.sort_order, "shotType": item.shot_type, "plannedDuration": item.planned_duration, "outline": item.shot_options} for item in lines],
            "overallRequirement": task.extra_requirement,
        }
    context_hash = hashlib.sha256(
        json.dumps(
            {
                "promptVersion": PROMPT_VERSION,
                "schemaVersion": SCHEMA_VERSION,
                "storyBibleVersion": STORY_BIBLE_VERSION,
                "model": settings.llm_model,
                "temperature": 0.2,
                "current": current,
                "full": full_context,
                "cast": allowed_humans,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if not payload.force and line.generation_status == "succeeded" and line.prompt_context_hash == context_hash:
        return await line_json(db, line, [item.digital_human_id for item in line_cast])
    await consume_daily_quota(db, user_id=user.id, category="chat")
    now = utcnow()
    line.generation_status, line.generation_error = "running", None
    line.generation_attempt += 1
    job = GenerationJobModel(
        id=uid("job"),
        user_id=user.id,
        project_id=task.project_id,
        project_task_id=task.id,
        storyboard_line_id=line.id,
        kind="storyboard_line",
        status="running",
        progress=10,
        request={"current": current, "fullContext": full_context},
        attempt=line.generation_attempt,
        idempotency_key=f"storyboard:{line.id}:{context_hash}",
        started_at=now,
    )
    db.add(job)
    await db.commit()
    try:
        async with storyboard_generation_slots:
            result = await generate_storyboard_line(source=task.storyboard_type, current=current, full_context=full_context, allowed_humans=allowed_humans)
        line.scene_prompt, line.shot_prompt = result["scenePrompt"], result["shotPrompt"]
        line.generation_status, line.prompt_context_hash, line.generated_at = "succeeded", context_hash, utcnow()
        if task.storyboard_type == "ass":
            for item in line_cast:
                item.deleted_at = utcnow()
            for index, human_id in enumerate(result["digitalHumanIds"]):
                db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=index))
        # job.result 只保留瘦身后的调用记录：请求快照与返回原文体量大，统一入 llm_call_logs
        slim_records = [{key: value for key, value in call.items() if key not in ("requestMessages", "responseText")} for call in result.get("usageRecords") or []]
        job.status, job.progress, job.result, job.finished_at = "succeeded", 100, {**result, "usageRecords": slim_records}, utcnow()
        usage_records = result.get("usageRecords") or [{"operation": "storyboard_line", "usage": result.get("usage"), "requestId": result.get("requestId")}]
        _persist_llm_calls(
            db,
            usage_records,
            default_operation="storyboard_line",
            user_id=user.id,
            project_id=task.project_id,
            project_task_id=task.id,
            storyboard_line_id=line.id,
            generation_job_id=job.id,
        )
        await _refresh_storyboard_status(db, task)
        await db.commit()
        response = await line_json(db, line, result["digitalHumanIds"])
        normalized = normalize_usage(result.get("usage"))
        response["usage"] = {key: normalized[key] for key in ("inputTokens", "outputTokens", "cachedInputTokens", "totalTokens")}
        return response
    except Exception as exc:
        line.generation_status, line.generation_error = "failed", str(exc)[:2000]
        job.status, job.error, job.finished_at = "failed", str(exc)[:2000], utcnow()
        failed_calls = getattr(exc, "usage_records", None) or [
            {"operation": "storyboard_line_failed", "usage": getattr(exc, "usage", {}), "requestId": getattr(exc, "request_id", None)}
        ]
        _persist_llm_calls(
            db,
            failed_calls,
            default_operation="storyboard_line_failed",
            user_id=user.id,
            project_id=task.project_id,
            project_task_id=task.id,
            storyboard_line_id=line.id,
            generation_job_id=job.id,
            operation_suffix="_failed",
        )
        await _refresh_storyboard_status(db, task)
        await db.commit()
        raise HTTPException(502, f"单条分镜生成失败：{exc}") from exc


@router.post("/tasks/{task_id}/storyboard/retry-failed")
async def reset_failed_storyboard_lines(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    failed = list(
        (
            await db.execute(
                select(StoryboardLineModel).where(
                    StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.generation_status == "failed", StoryboardLineModel.deleted_at.is_(None)
                )
            )
        )
        .scalars()
        .all()
    )
    for line in failed:
        line.generation_status, line.generation_error = "pending", None
    task.status = "generating"
    await db.commit()
    return {"ok": True, "lineIds": [line.id for line in failed]}


@router.get("/token-usage")
async def list_token_usage(user: CurrentUser, project_task_id: str | None = None, db: AsyncSession = Db) -> dict:
    filters = [TokenUsageModel.user_id == user.id, TokenUsageModel.deleted_at.is_(None)]
    if project_task_id:
        await owned_task(db, user.id, project_task_id)
        filters.append(TokenUsageModel.project_task_id == project_task_id)
    items = list((await db.execute(select(TokenUsageModel).where(*filters).order_by(TokenUsageModel.created_at))).scalars().all())
    return {
        "summary": {
            "inputTokens": sum(item.input_tokens for item in items),
            "outputTokens": sum(item.output_tokens for item in items),
            "cachedInputTokens": sum(item.cached_input_tokens for item in items),
            "totalTokens": sum(item.total_tokens for item in items),
            "calls": len(items),
        },
        "records": [
            {
                "id": item.id,
                "operation": item.operation,
                "provider": item.provider,
                "model": item.model,
                "requestId": item.request_id,
                "projectId": item.project_id,
                "projectTaskId": item.project_task_id,
                "storyboardLineId": item.storyboard_line_id,
                "generationJobId": item.generation_job_id,
                "chatSessionId": item.chat_session_id,
                "inputTokens": item.input_tokens,
                "outputTokens": item.output_tokens,
                "cachedInputTokens": item.cached_input_tokens,
                "totalTokens": item.total_tokens,
                "createdAt": item.created_at.isoformat(),
            }
            for item in items
        ],
    }


def material_export_public(item: MaterialExportModel) -> dict:
    return {
        "id": item.id,
        "taskId": item.project_task_id,
        "jobId": item.generation_job_id,
        "status": item.status,
        "progress": item.progress,
        "stage": item.stage,
        "totalAssets": item.total_assets,
        "processedAssets": item.processed_assets,
        "totalBytes": item.total_bytes,
        "processedBytes": item.processed_bytes,
        "archiveSize": item.archive_size,
        "archiveUrl": item.archive_url,
        "error": item.error,
        "createdAt": item.created_at.isoformat(),
        "updatedAt": item.updated_at.isoformat(),
    }


async def _set_export_progress(
    export_id: str,
    job: Job,
    progress: int,
    stage: str,
    **values,
) -> None:
    lock = export_progress_locks.setdefault(export_id, asyncio.Lock())
    async with lock:
        async with session_factory() as session:
            item = await session.get(MaterialExportModel, export_id)
            if not item or item.deleted_at is not None:
                raise RuntimeError("导出任务不存在")
            progress = max(item.progress, job.progress, min(progress, 99))
            item.status = "running"
            item.progress = progress
            item.stage = stage
            if item.started_at is None:
                item.started_at = utcnow()
            for key, value in values.items():
                setattr(item, key, value)
            await session.commit()
        await jobs.update_progress(job, progress)


async def _run_material_export(export_id: str, job: Job) -> dict:
    try:
        async with export_slots:
            async with session_factory() as session:
                export = await session.get(MaterialExportModel, export_id)
                if not export or export.deleted_at is not None:
                    raise RuntimeError("导出任务不存在")
                task = await session.get(ProjectTaskModel, export.project_task_id)
                if not task or task.deleted_at is not None:
                    raise RuntimeError("子项目不存在")
                project = await session.get(ProjectModel, task.project_id)
                lines = list(
                    (
                        await session.execute(
                            select(StoryboardLineModel)
                            .where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None))
                            .order_by(StoryboardLineModel.sort_order)
                        )
                    )
                    .scalars()
                    .all()
                )
                shot_assets = list(
                    (
                        await session.execute(
                            select(ShotAssetModel)
                            .where(ShotAssetModel.storyboard_line_id.in_([line.id for line in lines]) if lines else False, ShotAssetModel.deleted_at.is_(None))
                            .order_by(ShotAssetModel.created_at)
                        )
                    )
                    .scalars()
                    .all()
                )
                task_cast_ids = list(
                    (
                        await session.execute(
                            select(ProjectCastModel.digital_human_id)
                            .where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None))
                            .order_by(ProjectCastModel.sort_order)
                        )
                    )
                    .scalars()
                    .all()
                )
                line_cast_ids = list(
                    (
                        await session.execute(
                            select(StoryboardLineCastModel.digital_human_id)
                            .where(
                                StoryboardLineCastModel.storyboard_line_id.in_([line.id for line in lines]) if lines else False,
                                StoryboardLineCastModel.deleted_at.is_(None),
                            )
                            .order_by(StoryboardLineCastModel.sort_order)
                        )
                    )
                    .scalars()
                    .all()
                )
                human_ids = list(dict.fromkeys([*task_cast_ids, *line_cast_ids]))
                humans_by_id = {
                    human.id: human
                    for human in (
                        (
                            await session.execute(
                                select(DigitalHumanModel).where(
                                    DigitalHumanModel.id.in_(human_ids) if human_ids else False,
                                    DigitalHumanModel.deleted_at.is_(None),
                                    or_(DigitalHumanModel.scope == "system", DigitalHumanModel.user_id == project.user_id),
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                }
                project_name, task_title, overall_prompt = project.name, task.title, task.overall_prompt
                line_values = [
                    {"id": line.id, "lyrics": line.lyrics, "shot_type": line.shot_type, "scene_prompt": line.scene_prompt, "shot_prompt": line.shot_prompt} for line in lines
                ]
                asset_values = [{"id": asset.id, "line_id": asset.storyboard_line_id, "video_url": asset.video_url, "is_current": asset.is_current} for asset in shot_assets]
                human_values = [
                    {"id": human.id, "name": human.name, "asset_code": human.asset_code, "avatar_url": human.avatar_url}
                    for human_id in human_ids
                    if (human := humans_by_id.get(human_id)) and human.avatar_url
                ]
            # 每镜只导出当前选中版（is_current）；无当前版的行回退到最新一版（asset_values 按创建时间升序，后者覆盖前者）
            current_by_line: dict[str, dict] = {}
            for asset in asset_values:
                existing = current_by_line.get(asset["line_id"])
                if not existing or asset["is_current"] or not existing["is_current"]:
                    current_by_line[asset["line_id"]] = asset
            downloads: list[dict] = []
            for index, line in enumerate(line_values, start=1):
                asset = current_by_line.get(line["id"])
                if asset:
                    downloads.append({"url": asset["video_url"], "arcname": f"videos/{index:02d}.mp4"})
            human_filenames: list[tuple[dict, str]] = []
            for index, human in enumerate(human_values, start=1):
                source_suffix = Path(urlsplit(human["avatar_url"]).path).suffix.lower()
                suffix = source_suffix if source_suffix in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
                filename = f"{index:02d}-{human['asset_code'] or human['id']}{suffix}"
                human_filenames.append((human, filename))
                downloads.append({"url": human["avatar_url"], "arcname": f"characters/{filename}"})
            total_assets = len(downloads)
            await _set_export_progress(export_id, job, 5, "正在整理视频脚本与素材", total_assets=total_assets)
            markdown = [f"# {project_name} · {task_title}", "", "## 整体提示词", "", overall_prompt or "（未填写）", "", "## 分镜提示词", ""]
            for index, line in enumerate(line_values, start=1):
                markdown.extend(
                    [
                        f"### {index:02d}. {line['lyrics'] or line['shot_type'] or '分镜'}",
                        "",
                        f"- 场景：{line['scene_prompt']}",
                        f"- 镜头：{line['shot_prompt']}",
                        "",
                    ]
                )
            if human_filenames:
                markdown.extend(["## 人物素材", ""])
            for human, filename in human_filenames:
                markdown.extend([f"- {human['name']}：`characters/{filename}`", ""])
            processed_assets = processed_bytes = known_total_bytes = 0
            last_progress = 5
            with tempfile.TemporaryDirectory(prefix=f"mvagent-export-{export_id}-") as temporary_directory:
                temporary_path = Path(temporary_directory)
                archive_path = temporary_path / f"{export_id}.zip"
                # 并发下载到临时目录，完成后按清单顺序写入 ZIP，保证包内镜序稳定。
                # 共用 AsyncClient 复用 TLS/HTTP 连接；文件仍流式落盘，提升并发不会线性放大内存。
                in_flight: dict[int, float] = {}
                download_slots = asyncio.Semaphore(settings.export_download_concurrency)

                async def download_one(position: int, item: dict) -> None:
                    nonlocal processed_assets, processed_bytes, known_total_bytes, last_progress
                    target = temporary_path / f"dl-{position:04d}"

                    async def on_download(current: int, declared: int | None) -> None:
                        nonlocal last_progress
                        in_flight[position] = current / declared if declared else 0.0
                        progress = 5 + int(65 * (processed_assets + sum(in_flight.values())) / max(1, total_assets))
                        if progress > last_progress:
                            last_progress = progress
                            await _set_export_progress(
                                export_id,
                                job,
                                progress,
                                f"正在下载素材 {processed_assets + 1}/{total_assets}",
                                processed_assets=processed_assets,
                                processed_bytes=processed_bytes + current,
                                total_bytes=known_total_bytes + (declared or 0),
                            )

                    async with download_slots:
                        _, _, size = await download_public_url_to_path(
                            item["url"],
                            target,
                            progress_callback=on_download,
                            client=download_client,
                        )
                    in_flight.pop(position, None)
                    item["path"] = target
                    processed_assets += 1
                    processed_bytes += size
                    known_total_bytes += size
                    progress = 5 + int(65 * processed_assets / max(1, total_assets))
                    last_progress = max(last_progress, progress)
                    await _set_export_progress(
                        export_id,
                        job,
                        progress,
                        f"已下载 {processed_assets}/{total_assets} 个素材",
                        processed_assets=processed_assets,
                        processed_bytes=processed_bytes,
                        total_bytes=known_total_bytes,
                    )

                limits = httpx.Limits(
                    max_connections=settings.export_download_concurrency,
                    max_keepalive_connections=settings.export_download_concurrency,
                )
                async with httpx.AsyncClient(timeout=180, follow_redirects=False, limits=limits) as download_client:
                    await asyncio.gather(*(download_one(position, item) for position, item in enumerate(downloads)))
                # 打包 70–85%：按清单顺序写入（videos/01.mp4… 与镜序一致）
                with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_STORED, allowZip64=True) as bundle:
                    for written, item in enumerate(downloads, start=1):
                        bundle.write(item["path"], item["arcname"])
                        item["path"].unlink(missing_ok=True)
                        progress = 70 + int(15 * written / max(1, total_assets))
                        if progress > last_progress:
                            last_progress = progress
                            await _set_export_progress(
                                export_id,
                                job,
                                progress,
                                f"正在打包素材 {written}/{total_assets}",
                                processed_assets=processed_assets,
                                processed_bytes=processed_bytes,
                                total_bytes=known_total_bytes,
                            )
                    bundle.writestr("prompts.md", "\n".join(markdown).encode("utf-8"), compress_type=zipfile.ZIP_DEFLATED)
                archive_size = archive_path.stat().st_size
                await _set_export_progress(export_id, job, 85, "正在上传压缩包到 TOS", archive_size=archive_size)
                # 上传 85–99%：TOS data_transfer_listener 在 worker 线程回报字节数，主协程轮询折算进度
                upload_state = {"consumed": 0}

                def on_upload(consumed: int, _total: int) -> None:
                    upload_state["consumed"] = consumed

                upload_task = asyncio.create_task(
                    get_storage().put_file(
                        safe_key(f"users/{job.user_id}/exports/{job.project_task_id}", f"{export_id}.zip"),
                        archive_path,
                        "application/zip",
                        progress_callback=on_upload,
                    )
                )
                while not upload_task.done():
                    await asyncio.sleep(1.5)
                    fraction = min(1.0, upload_state["consumed"] / max(1, archive_size))
                    progress = 85 + int(14 * fraction)
                    if progress > last_progress:
                        last_progress = progress
                        await _set_export_progress(
                            export_id,
                            job,
                            progress,
                            "正在上传压缩包到 TOS",
                            archive_size=archive_size,
                        )
                archive_url = await upload_task
            async with session_factory() as session:
                export = await session.get(MaterialExportModel, export_id)
                export.status = "ready"
                export.progress = 100
                export.stage = "导出完成"
                export.archive_url = archive_url
                export.archive_size = archive_size
                export.finished_at = utcnow()
                await session.commit()
            return {"exportId": export_id, "archiveUrl": archive_url, "archiveSize": archive_size}
    except Exception as exc:
        async with session_factory() as session:
            export = await session.get(MaterialExportModel, export_id)
            if export:
                export.status = "failed"
                export.stage = "导出失败"
                export.error = str(exc)
                export.finished_at = utcnow()
                await session.commit()
        raise
    finally:
        export_progress_locks.pop(export_id, None)


@router.post("/tasks/{task_id}/material-exports", status_code=202)
async def create_material_export(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    active_for_task = (
        (
            await db.execute(
                select(MaterialExportModel).where(
                    MaterialExportModel.user_id == user.id,
                    MaterialExportModel.project_task_id == task.id,
                    MaterialExportModel.status.in_(("queued", "running")),
                    MaterialExportModel.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .first()
    )
    if active_for_task:
        return material_export_public(active_for_task)
    active_count = len(
        list(
            (
                await db.execute(
                    select(MaterialExportModel.id).where(
                        MaterialExportModel.user_id == user.id,
                        MaterialExportModel.status.in_(("queued", "running")),
                        MaterialExportModel.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
    )
    if active_count >= settings.export_per_user_concurrency:
        raise HTTPException(429, f"每个用户最多同时导出 {settings.export_per_user_concurrency} 个子项目")
    # 清理同任务的历史已完成/已失败导出（每个子项目只保留最新一次）
    now = utcnow()
    await db.execute(
        update(MaterialExportModel)
        .where(
            MaterialExportModel.project_task_id == task.id,
            MaterialExportModel.deleted_at.is_(None),
            MaterialExportModel.status.in_(("ready", "failed", "cancelled")),
        )
        .values(deleted_at=now)
    )
    export = MaterialExportModel(id=uid("export"), user_id=user.id, project_task_id=task.id)
    db.add(export)
    await db.commit()
    await db.refresh(export)
    export_id = export.id
    job = await jobs.create(
        "export",
        {"export_id": export_id},
        lambda item: _run_material_export(export_id, item),
        user_id=user.id,
        project_id=task.project_id,
        project_task_id=task.id,
    )
    export.generation_job_id = job.id
    await db.commit()
    await db.refresh(export)
    return material_export_public(export)


@router.get("/tasks/{task_id}/material-exports")
async def list_material_exports(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> list[dict]:
    await owned_task(db, user.id, task_id)
    items = list(
        (
            await db.execute(
                select(MaterialExportModel)
                .where(MaterialExportModel.user_id == user.id, MaterialExportModel.project_task_id == task_id, MaterialExportModel.deleted_at.is_(None))
                .order_by(MaterialExportModel.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return [material_export_public(item) for item in items]


@router.get("/material-exports/{export_id}")
async def get_material_export(export_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = await db.get(MaterialExportModel, export_id)
    if not item or item.deleted_at is not None or item.user_id != user.id:
        raise HTTPException(404, "导出任务不存在")
    return material_export_public(item)


@router.get("/material-exports/{export_id}/events")
async def material_export_events(export_id: str, request: Request, user: CurrentUser, db: AsyncSession = Db) -> StreamingResponse:
    item = await db.get(MaterialExportModel, export_id)
    if not item or item.deleted_at is not None or item.user_id != user.id:
        raise HTTPException(404, "导出任务不存在")

    async def stream():
        last = None
        while not await request.is_disconnected():
            async with session_factory() as session:
                current = await session.get(MaterialExportModel, export_id)
                if not current or current.deleted_at is not None or current.user_id != user.id:
                    return
                marker = (current.status, current.progress, current.stage, current.updated_at)
                if marker != last:
                    payload = {"type": "export", "export": material_export_public(current)}
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    last = marker
                if current.status in {"ready", "failed"}:
                    return
            await asyncio.sleep(0.75)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
