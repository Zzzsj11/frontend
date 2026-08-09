from __future__ import annotations

import io
import hashlib
import asyncio
import json
import uuid
import zipfile

import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentUser
from .database import database_session
from .models import (
    ApiErrorLogModel,
    DigitalHumanModel,
    DigitalHumanStyleModel,
    GenerationJobModel,
    MaterialExportModel,
    ProjectCastModel,
    ProjectModel,
    ProjectTaskModel,
    SceneAssetModel,
    ShotAssetModel,
    StoryboardLineCastModel,
    StoryboardLineModel,
    TokenUsageModel,
    VoiceAssetModel,
    utcnow,
    UserModel,
    RefreshTokenModel,
    ChatSessionModel,
    ChatMessageModel,
)
from .media_constraints import normalize_video_duration
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
    UserCreate,
    UserUpdate,
)
from .auth import hash_password, user_public
from .storage import get_storage, is_tos_url, safe_key
from .storyboard_prompt import generate_storyboard_line
from .config import settings
from .token_usage import add_token_usage, normalize_usage
from .story_bible import STORY_BIBLE_VERSION, build_general_story_bible, exact_durations
from .storyboard_prompt import PROMPT_VERSION, SCHEMA_VERSION


router = APIRouter(prefix="/api")
Db = Depends(database_session)
storyboard_generation_slots = asyncio.Semaphore(settings.storyboard_generation_concurrency)


@router.get("/admin/api-errors")
async def list_api_errors(user: CurrentUser, limit: int = 100, db: AsyncSession = Db) -> dict:
    require_admin(user)
    limit = min(500, max(1, limit))
    items = list((await db.execute(select(ApiErrorLogModel).where(ApiErrorLogModel.deleted_at.is_(None)).order_by(ApiErrorLogModel.created_at.desc()).limit(limit))).scalars().all())
    return {"items": [{"id": item.id, "errorCode": item.error_code, "userId": item.user_id, "method": item.method, "path": item.path, "queryString": item.query_string, "statusCode": item.status_code, "errorType": item.error_type, "message": item.message, "requestPayload": item.request_payload, "traceback": item.traceback, "clientIp": item.client_ip, "userAgent": item.user_agent, "createdAt": item.created_at.isoformat()} for item in items]}


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
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")


@router.get("/admin/users")
async def list_users(user: CurrentUser, db: AsyncSession = Db) -> list[dict]:
    require_admin(user)
    items = (await db.execute(select(UserModel).where(UserModel.deleted_at.is_(None)).order_by(UserModel.created_at))).scalars().all()
    return [{**user_public(item), "status": item.status, "createdAt": item.created_at.isoformat()} for item in items]


@router.post("/admin/users", status_code=201)
async def create_user(payload: UserCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    require_admin(user)
    username = payload.username.strip().lower()
    exists = (await db.execute(select(UserModel).where(UserModel.username == username, UserModel.deleted_at.is_(None)))).scalar_one_or_none()
    if exists:
        raise HTTPException(409, "用户名已存在")
    item = UserModel(id=uid("user"), username=username, password_hash=hash_password(payload.password), display_name=payload.display_name, role=payload.role, must_change_password=True)
    db.add(item); await db.commit(); return user_public(item)


@router.patch("/admin/users/{user_id}")
async def update_user(user_id: str, payload: UserUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    require_admin(user)
    item = await db.get(UserModel, user_id)
    if not item or item.deleted_at is not None: raise HTTPException(404, "用户不存在")
    for key, value in payload.model_dump(exclude_unset=True).items(): setattr(item, key, value)
    await db.commit(); return user_public(item)


@router.delete("/admin/users/{user_id}")
async def delete_user(user_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    require_admin(user)
    if user_id == user.id: raise HTTPException(422, "不能删除当前登录用户")
    item = await db.get(UserModel, user_id)
    if not item or item.deleted_at is not None: raise HTTPException(404, "用户不存在")
    now = utcnow(); item.deleted_at = now; item.status = "disabled"
    projects = list((await db.execute(select(ProjectModel).where(ProjectModel.user_id == user_id, ProjectModel.deleted_at.is_(None)))).scalars().all())
    task_ids = list((await db.execute(select(ProjectTaskModel.id).where(ProjectTaskModel.project_id.in_([p.id for p in projects]) if projects else False, ProjectTaskModel.deleted_at.is_(None)))).scalars().all())
    for project in projects: project.deleted_at = now
    await soft_delete_task_tree(db, task_ids, now)
    for model in (RefreshTokenModel, DigitalHumanStyleModel, DigitalHumanModel, ChatSessionModel, GenerationJobModel, MaterialExportModel):
        await db.execute(update(model).where(model.user_id == user_id, model.deleted_at.is_(None)).values(deleted_at=now))
    session_ids = list((await db.execute(select(ChatSessionModel.id).where(ChatSessionModel.user_id == user_id))).scalars().all())
    if session_ids: await db.execute(update(ChatMessageModel).where(ChatMessageModel.session_id.in_(session_ids), ChatMessageModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.commit(); return {"ok": True}


EMPTY_SCENES = [
    ("城市旧街的潮湿路面倒映暖色路灯，落叶散落在石板路上", "低机位沿街道缓慢推进，浅景深，画面稳定，无人物出镜"),
    ("安静河岸边的空长椅，远处城市灯光刚刚亮起", "镜头从水面倒影缓慢抬升到长椅，轻微横摇"),
    ("暖色房间里的老唱片机缓慢旋转，窗外光线渐暗", "微距拍摄唱针落下，镜头沿唱片纹理缓慢旋转"),
]
CHARACTER_SCENES = [
    ("公寓窗边，余晖穿过薄纱窗帘，房间内漂浮细小尘埃", "人物独自靠在窗边凝视远方，镜头从中景缓慢推进至面部近景"),
    ("傍晚十字路口，人群在霓虹灯下经过，背景车辆虚化成光斑", "人物逆着人流缓慢前行，手持镜头平稳跟随"),
    ("临街咖啡馆靠窗座位，桌面放着两杯咖啡，其中一把椅子空着", "人物抬头看向窗外，镜头快速跟焦到眼神变化"),
]


async def owned_project(db: AsyncSession, user_id: str, project_id: str) -> ProjectModel:
    result = await db.execute(
        select(ProjectModel).where(
            ProjectModel.id == project_id, ProjectModel.user_id == user_id, ProjectModel.deleted_at.is_(None)
        )
    )
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
    query = select(DigitalHumanModel).where(
        DigitalHumanModel.deleted_at.is_(None),
        DigitalHumanModel.status == "active",
        or_(DigitalHumanModel.scope == "system", DigitalHumanModel.user_id == user_id),
    )
    if ids is not None:
        query = query.where(DigitalHumanModel.id.in_(ids))
    return list((await db.execute(query)).scalars().all())


async def soft_delete_task_tree(db: AsyncSession, task_ids: list[str], now) -> None:
    if not task_ids:
        return
    line_ids = list((await db.execute(select(StoryboardLineModel.id).where(StoryboardLineModel.project_task_id.in_(task_ids), StoryboardLineModel.deleted_at.is_(None)))).scalars().all())
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
        (await db.execute(select(ProjectModel).where(ProjectModel.user_id == user.id, ProjectModel.deleted_at.is_(None)).order_by(ProjectModel.updated_at.desc()))).scalars().all()
    )
    if not projects:
        return []
    tasks = list(
        (await db.execute(select(ProjectTaskModel).where(ProjectTaskModel.project_id.in_([p.id for p in projects]), ProjectTaskModel.deleted_at.is_(None)).order_by(ProjectTaskModel.created_at))).scalars().all()
    )
    by_project: dict[str, list[ProjectTaskModel]] = {}
    for task in tasks:
        by_project.setdefault(task.project_id, []).append(task)
    return [project_json(project, by_project.get(project.id, [])) for project in projects]


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
    now = utcnow(); item.deleted_at = now
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


@router.post("/projects/{project_id}/storyboards/general", status_code=201)
async def create_general_storyboard(project_id: str, payload: GeneralStoryboardCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    await owned_project(db, user.id, project_id)
    total = payload.empty_shot_count + payload.character_shot_count
    if total < 1:
        raise HTTPException(422, "至少需要一个分镜")
    if payload.character_shot_count and not payload.digital_human_ids:
        raise HTTPException(422, "人物镜数量大于 0 时至少需要选择一个角色")
    visible = await visible_humans(db, user.id, payload.digital_human_ids)
    if len({item.id for item in visible}) != len(set(payload.digital_human_ids)):
        raise HTTPException(422, "包含不可用角色")
    config = payload.model_dump(mode="json")
    title = f"通用分镜 · {payload.tertiary_category or payload.secondary_category}"
    task = ProjectTaskModel(id=uid("task"), project_id=project_id, title=title, storyboard_type="general", status="generating", extra_requirement=payload.extra_requirement, overall_prompt=payload.overall_prompt, storyboard_config=config)
    db.add(task)
    await db.flush()
    for index, human_id in enumerate(payload.digital_human_ids):
        db.add(ProjectCastModel(id=uid("cast"), project_task_id=task.id, digital_human_id=human_id, sort_order=index))
    try:
        durations = exact_durations(payload.total_duration, total)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    definitions: list[tuple[str, tuple[str, str], list[str]]] = []
    for index in range(max(payload.empty_shot_count, payload.character_shot_count)):
        if index < payload.empty_shot_count:
            definitions.append(("empty", EMPTY_SCENES[index % len(EMPTY_SCENES)], []))
        if index < payload.character_shot_count:
            roles = [payload.digital_human_ids[index % len(payload.digital_human_ids)]] if payload.digital_human_ids else []
            if index == payload.character_shot_count - 1 and len(payload.digital_human_ids) > 1:
                partner = payload.digital_human_ids[(index + 1) % len(payload.digital_human_ids)]
                if partner not in roles:
                    roles.append(partner)
            definitions.append(("character", CHARACTER_SCENES[index % len(CHARACTER_SCENES)], roles))
    config["storyBible"] = build_general_story_bible(config=config, definitions=definitions)
    task.storyboard_config = config
    output = []
    for index, (shot_type, (scene, shot), roles) in enumerate(definitions):
        duration = durations[index]
        line = StoryboardLineModel(id=uid("line"), project_task_id=task.id, sort_order=index, source="general", shot_type=shot_type, planned_duration=duration, scene_prompt="", shot_prompt="", shot_options={"ratio": payload.ratio, "resolution": payload.resolution, "imageModel": payload.image_model, "videoModel": payload.video_model, "duration": normalize_video_duration(duration), "outlineScene": scene, "outlineShot": shot}, generation_status="pending")
        db.add(line)
        await db.flush()
        for role_index, human_id in enumerate(roles):
            db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=role_index))
        output.append({"id": line.id, "shotType": shot_type, "plannedDuration": duration, "scenePrompt": "", "shotPrompt": "", "digitalHumanIds": roles, "generationStatus": "pending"})
    await db.commit()
    return {"taskId": task.id, "projectId": project_id, "title": title, "status": "generating", "cast": payload.digital_human_ids, "totalDuration": payload.total_duration, "storyboardConfig": config, "lines": output}


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    lines = list((await db.execute(select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order))).scalars().all())
    cast = list((await db.execute(select(ProjectCastModel).where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None)).order_by(ProjectCastModel.sort_order))).scalars().all())
    line_cast = list((await db.execute(select(StoryboardLineCastModel).where(StoryboardLineCastModel.storyboard_line_id.in_([line.id for line in lines]) if lines else False, StoryboardLineCastModel.deleted_at.is_(None)))).scalars().all())
    casts: dict[str, list[str]] = {}
    for link in line_cast:
        casts.setdefault(link.storyboard_line_id, []).append(link.digital_human_id)
    return {**task_json(task), "cast": [item.digital_human_id for item in cast], "lines": [await line_json(db, line, casts.get(line.id, [])) for line in lines]}


@router.patch("/tasks/{task_id}")
async def update_task(task_id: str, payload: TaskUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = await owned_task(db, user.id, task_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    await db.commit()
    await db.refresh(item)
    return task_json(item)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = await owned_task(db, user.id, task_id)
    await soft_delete_task_tree(db, [item.id], utcnow())
    await db.commit()
    return {"ok": True}


@router.get("/digital-human-styles")
async def list_styles(user: CurrentUser, db: AsyncSession = Db) -> list[dict]:
    items = list((await db.execute(select(DigitalHumanStyleModel).where(DigitalHumanStyleModel.deleted_at.is_(None), or_(DigitalHumanStyleModel.scope == "system", DigitalHumanStyleModel.user_id == user.id)).order_by(DigitalHumanStyleModel.sort_order))).scalars().all())
    return [{"id": item.id, "name": item.name, "scope": item.scope, "readOnly": item.scope == "system"} for item in items]


@router.post("/digital-human-styles", status_code=201)
async def create_style(payload: StyleCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    item = DigitalHumanStyleModel(id=uid("style"), user_id=user.id, name=payload.name.strip(), scope="private")
    db.add(item)
    await db.commit()
    return {"id": item.id, "name": item.name, "scope": item.scope, "readOnly": False}


@router.delete("/digital-human-styles/{style_id}")
async def delete_style(style_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    result = await db.execute(select(DigitalHumanStyleModel).where(DigitalHumanStyleModel.id == style_id, DigitalHumanStyleModel.user_id == user.id, DigitalHumanStyleModel.scope == "private", DigitalHumanStyleModel.deleted_at.is_(None)))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "分类不存在")
    item.deleted_at = utcnow()
    await db.execute(update(DigitalHumanModel).where(DigitalHumanModel.style_id == style_id, DigitalHumanModel.user_id == user.id, DigitalHumanModel.deleted_at.is_(None)).values(style_id=None))
    await db.commit()
    return {"ok": True}


def human_json(item: DigitalHumanModel, style_name: str | None = None) -> dict:
    return {"id": item.id, "name": item.name, "styleId": item.style_id, "style": style_name or "未分类", "avatar": item.avatar_thumbnail_url or item.avatar_url, "originalAvatar": item.avatar_url, "description": item.description, "avatarPrompt": item.avatar_prompt, "assetCode": item.asset_code, "gender": item.gender, "ageDescription": item.age_description, "appearanceStyle": item.appearance_style, "clothingDescription": item.clothing_description, "suitableMusicStyles": item.suitable_music_styles, "systemPrompt": item.system_prompt, "scope": item.scope, "readOnly": item.scope == "system"}


@router.get("/digital-humans")
async def list_humans(user: CurrentUser, db: AsyncSession = Db) -> list[dict]:
    items = await visible_humans(db, user.id)
    style_ids = [item.style_id for item in items if item.style_id]
    styles = {item.id: item.name for item in (await db.execute(select(DigitalHumanStyleModel).where(DigitalHumanStyleModel.id.in_(style_ids) if style_ids else False))).scalars().all()}
    return [human_json(item, styles.get(item.style_id)) for item in items]


@router.post("/digital-humans", status_code=201)
async def create_human(payload: DigitalHumanCreate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    if not is_tos_url(payload.avatar_url) or (payload.avatar_thumbnail_url and not is_tos_url(payload.avatar_thumbnail_url)):
        raise HTTPException(422, "角色图片必须先上传到配置的 TOS")
    if payload.style_id:
        style = await db.get(DigitalHumanStyleModel, payload.style_id)
        if not style or style.deleted_at is not None or (style.scope != "system" and style.user_id != user.id):
            raise HTTPException(422, "角色分类不可用")
    item = DigitalHumanModel(id=uid("dh"), user_id=user.id, scope="private", **payload.model_dump())
    db.add(item)
    await db.commit()
    return human_json(item)


@router.patch("/digital-humans/{human_id}")
async def update_human(human_id: str, payload: DigitalHumanUpdate, user: CurrentUser, db: AsyncSession = Db) -> dict:
    result = await db.execute(select(DigitalHumanModel).where(DigitalHumanModel.id == human_id, DigitalHumanModel.user_id == user.id, DigitalHumanModel.scope == "private", DigitalHumanModel.deleted_at.is_(None)))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "私有角色不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        if key in {"avatar_url", "avatar_thumbnail_url"} and value and not is_tos_url(str(value)):
            raise HTTPException(422, "角色图片必须存储在配置的 TOS")
        setattr(item, key, value)
    await db.commit()
    return human_json(item)


@router.delete("/digital-humans/{human_id}")
async def delete_human(human_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    result = await db.execute(select(DigitalHumanModel).where(DigitalHumanModel.id == human_id, DigitalHumanModel.user_id == user.id, DigitalHumanModel.scope == "private", DigitalHumanModel.deleted_at.is_(None)))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(404, "私有角色不存在")
    item.deleted_at = utcnow()
    now = item.deleted_at
    await db.execute(update(ProjectCastModel).where(ProjectCastModel.digital_human_id == human_id, ProjectCastModel.deleted_at.is_(None)).values(deleted_at=now))
    await db.execute(update(StoryboardLineCastModel).where(StoryboardLineCastModel.digital_human_id == human_id, StoryboardLineCastModel.deleted_at.is_(None)).values(deleted_at=now))
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
        old = list((await db.execute(select(StoryboardLineCastModel).where(StoryboardLineCastModel.storyboard_line_id == line.id, StoryboardLineCastModel.deleted_at.is_(None)))).scalars().all())
        for item in old:
            item.deleted_at = utcnow()
        for index, human_id in enumerate(payload.digital_human_ids):
            db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=index))
    await db.commit()
    return await line_json(db, line, payload.digital_human_ids or [])


@router.delete("/storyboard-lines/{line_id}")
async def delete_line(line_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    line = await owned_line(db, user.id, line_id)
    now = utcnow(); line.deleted_at = now
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


async def line_json(db: AsyncSession, line: StoryboardLineModel, cast: list[str]) -> dict:
    scenes = list((await db.execute(select(SceneAssetModel).where(SceneAssetModel.storyboard_line_id == line.id, SceneAssetModel.deleted_at.is_(None)).order_by(SceneAssetModel.created_at))).scalars().all())
    shots = list((await db.execute(select(ShotAssetModel).where(ShotAssetModel.storyboard_line_id == line.id, ShotAssetModel.deleted_at.is_(None)).order_by(ShotAssetModel.created_at))).scalars().all())
    voices = list((await db.execute(select(VoiceAssetModel).where(VoiceAssetModel.storyboard_line_id == line.id, VoiceAssetModel.deleted_at.is_(None)).order_by(VoiceAssetModel.created_at))).scalars().all())
    return {
        "id": line.id, "source": line.source, "shotType": line.shot_type, "plannedDuration": line.planned_duration,
        "lyrics": line.lyrics, "lyricsZh": line.lyrics_zh, "start": line.start_time, "end": line.end_time,
        "scenePrompt": line.scene_prompt, "shotPrompt": line.shot_prompt, "shotOptions": line.shot_options,
        "generationStatus": line.generation_status, "generationError": line.generation_error,
        "generationAttempt": line.generation_attempt, "generatedAt": line.generated_at.isoformat() if line.generated_at else None,
        "digitalHumanIds": cast,
        "sceneAssets": [{"id": a.id, "imageUrl": a.image_url, "isCurrent": a.is_current} for a in scenes],
        "shotAssets": [{"id": a.id, "coverUrl": a.cover_url, "videoUrl": a.video_url, "duration": a.duration, "resolution": a.resolution, "ratio": a.ratio, "isCurrent": a.is_current} for a in shots],
        "voiceAssets": [{"id": a.id, "url": a.audio_url, "duration": a.duration, "isCurrent": a.is_current} for a in voices],
    }


async def _refresh_storyboard_status(db: AsyncSession, task: ProjectTaskModel) -> None:
    statuses = list((await db.execute(select(StoryboardLineModel.generation_status).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)))).scalars().all())
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
    if line.generation_status == "running":
        raise HTTPException(409, "该分镜正在生成")
    lines = list((await db.execute(select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order))).scalars().all())
    cast_links = list((await db.execute(select(ProjectCastModel).where(ProjectCastModel.project_task_id == task.id, ProjectCastModel.deleted_at.is_(None)).order_by(ProjectCastModel.sort_order))).scalars().all())
    task_cast_ids = [item.digital_human_id for item in cast_links]
    line_cast = list((await db.execute(select(StoryboardLineCastModel).where(StoryboardLineCastModel.storyboard_line_id == line.id, StoryboardLineCastModel.deleted_at.is_(None)).order_by(StoryboardLineCastModel.sort_order))).scalars().all())
    planned_role_ids = [item.digital_human_id for item in line_cast]
    allowed_ids = planned_role_ids if task.storyboard_type == "general" else task_cast_ids
    human_models = list((await db.execute(select(DigitalHumanModel).where(DigitalHumanModel.id.in_(allowed_ids) if allowed_ids else False, DigitalHumanModel.deleted_at.is_(None)))).scalars().all())
    human_by_id = {item.id: item for item in human_models}
    allowed_humans = [
        {
            "id": human.id, "name": human.name, "gender": human.gender,
            "ageDescription": human.age_description, "appearanceStyle": human.appearance_style,
            "clothingDescription": human.clothing_description,
            "suitableMusicStyles": human.suitable_music_styles,
            "systemPrompt": human.system_prompt or human.avatar_prompt or human.description,
        }
        for human_id in allowed_ids if (human := human_by_id.get(human_id))
    ]
    current = {"id": line.id, "index": line.sort_order, "lyrics": line.lyrics, "start": line.start_time, "end": line.end_time, "shotType": line.shot_type, "plannedDuration": line.planned_duration, "plannedDigitalHumanIds": planned_role_ids, "outline": line.shot_options}
    if task.storyboard_type == "ass":
        full_context = {"songId": task.storyboard_config.get("songId"), "songEmotion": task.storyboard_config.get("songEmotion"), "storyBible": task.storyboard_config.get("storyBible"), "allLyrics": [{"index": item.sort_order, "lyrics": item.lyrics, "start": item.start_time, "end": item.end_time} for item in lines], "overallRequirement": task.extra_requirement}
    else:
        full_context = {"storyboardConfig": task.storyboard_config, "shotOutline": [{"index": item.sort_order, "shotType": item.shot_type, "plannedDuration": item.planned_duration, "outline": item.shot_options} for item in lines], "overallRequirement": task.extra_requirement}
    context_hash = hashlib.sha256(json.dumps({"promptVersion": PROMPT_VERSION, "schemaVersion": SCHEMA_VERSION, "storyBibleVersion": STORY_BIBLE_VERSION, "model": settings.llm_model, "temperature": 0.2, "current": current, "full": full_context, "cast": allowed_humans}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    if not payload.force and line.generation_status == "succeeded" and line.prompt_context_hash == context_hash:
        return await line_json(db, line, [item.digital_human_id for item in line_cast])
    now = utcnow()
    line.generation_status, line.generation_error = "running", None
    line.generation_attempt += 1
    job = GenerationJobModel(id=uid("job"), user_id=user.id, project_id=task.project_id, project_task_id=task.id, storyboard_line_id=line.id, kind="storyboard_line", status="running", progress=10, request={"current": current, "fullContext": full_context}, attempt=line.generation_attempt, idempotency_key=f"storyboard:{line.id}:{context_hash}", started_at=now)
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
        job.status, job.progress, job.result, job.finished_at = "succeeded", 100, result, utcnow()
        usage_records = result.get("usageRecords") or [{"operation": "storyboard_line", "usage": result.get("usage"), "requestId": result.get("requestId")}]
        for call in usage_records:
            add_token_usage(db, operation=call.get("operation") or "storyboard_line", provider="openai-compatible", model=settings.llm_model, usage=call.get("usage"), user_id=user.id, project_id=task.project_id, project_task_id=task.id, storyboard_line_id=line.id, generation_job_id=job.id, request_id=call.get("requestId"))
        await _refresh_storyboard_status(db, task)
        await db.commit()
        response = await line_json(db, line, result["digitalHumanIds"])
        normalized = normalize_usage(result.get("usage"))
        response["usage"] = {key: normalized[key] for key in ("inputTokens", "outputTokens", "cachedInputTokens", "totalTokens")}
        return response
    except Exception as exc:
        line.generation_status, line.generation_error = "failed", str(exc)[:2000]
        job.status, job.error, job.finished_at = "failed", str(exc)[:2000], utcnow()
        failed_calls = getattr(exc, "usage_records", None) or [{"operation": "storyboard_line_failed", "usage": getattr(exc, "usage", {}), "requestId": getattr(exc, "request_id", None)}]
        for call in failed_calls:
            operation = call.get("operation") or "storyboard_line_failed"
            add_token_usage(db, operation=f"{operation}_failed", provider="openai-compatible", model=settings.llm_model, usage=call.get("usage"), user_id=user.id, project_id=task.project_id, project_task_id=task.id, storyboard_line_id=line.id, generation_job_id=job.id, request_id=call.get("requestId"))
        await _refresh_storyboard_status(db, task)
        await db.commit()
        raise HTTPException(502, f"单条分镜生成失败：{exc}") from exc


@router.post("/tasks/{task_id}/storyboard/retry-failed")
async def reset_failed_storyboard_lines(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    failed = list((await db.execute(select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.generation_status == "failed", StoryboardLineModel.deleted_at.is_(None)))).scalars().all())
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
            {"id": item.id, "operation": item.operation, "provider": item.provider, "model": item.model,
             "requestId": item.request_id, "projectId": item.project_id, "projectTaskId": item.project_task_id,
             "storyboardLineId": item.storyboard_line_id, "generationJobId": item.generation_job_id,
             "chatSessionId": item.chat_session_id, "inputTokens": item.input_tokens,
             "outputTokens": item.output_tokens, "cachedInputTokens": item.cached_input_tokens,
             "totalTokens": item.total_tokens, "createdAt": item.created_at.isoformat()}
            for item in items
        ],
    }


@router.post("/tasks/{task_id}/material-export", status_code=201)
async def export_materials(task_id: str, user: CurrentUser, db: AsyncSession = Db) -> dict:
    task = await owned_task(db, user.id, task_id)
    project = await owned_project(db, user.id, task.project_id)
    lines = list((await db.execute(select(StoryboardLineModel).where(StoryboardLineModel.project_task_id == task.id, StoryboardLineModel.deleted_at.is_(None)).order_by(StoryboardLineModel.sort_order))).scalars().all())
    shot_assets = list((await db.execute(select(ShotAssetModel).where(ShotAssetModel.storyboard_line_id.in_([line.id for line in lines]) if lines else False, ShotAssetModel.deleted_at.is_(None)).order_by(ShotAssetModel.created_at))).scalars().all())
    by_line: dict[str, list[ShotAssetModel]] = {}
    for asset in shot_assets:
        by_line.setdefault(asset.storyboard_line_id, []).append(asset)
    export = MaterialExportModel(id=uid("export"), user_id=user.id, project_task_id=task.id, status="running")
    db.add(export)
    await db.commit()
    try:
        markdown = [f"# {project.name} · {task.title}", "", "## 整体提示词", "", task.overall_prompt or "（未填写）", "", "## 分镜提示词", ""]
        archive = io.BytesIO()
        async with httpx.AsyncClient(timeout=180, follow_redirects=True) as client:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
                for index, line in enumerate(lines, start=1):
                    markdown.extend([f"### {index:02d}. {line.lyrics or line.shot_type or '分镜'}", "", f"- 场景：{line.scene_prompt}", f"- 镜头：{line.shot_prompt}", ""])
                    for version, asset in enumerate(by_line.get(line.id, []), start=1):
                        response = await client.get(asset.video_url)
                        response.raise_for_status()
                        bundle.writestr(f"videos/{index:02d}-v{version:02d}-{asset.id}.mp4", response.content)
                bundle.writestr("prompts.md", "\n".join(markdown).encode("utf-8"))
        archive_url = await get_storage().put_bytes(safe_key(f"users/{user.id}/exports", f"{task.id}.zip"), archive.getvalue(), "application/zip")
        export.status = "ready"
        export.archive_url = archive_url
        await db.commit()
        return {"id": export.id, "status": export.status, "archiveUrl": archive_url}
    except Exception as exc:
        export.status = "failed"
        export.error = str(exc)
        await db.commit()
        raise HTTPException(502, f"素材导出失败：{exc}") from exc
