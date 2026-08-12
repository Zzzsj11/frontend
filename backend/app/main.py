from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from PIL import UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.exceptions import HTTPException as StarletteHTTPException

from .admin import public_router as model_options_router
from .admin import router as admin_router
from .ass_storyboard import group_cues, parse_ass
from .auth import (
    CurrentUser,
    clear_refresh_cookie,
    hash_password,
    issue_tokens,
    login,
    refresh_cookie_value,
    revoke_refresh,
    rotate_refresh,
    seed_admin,
    user_public,
    verify_password,
)
from .balance import query_business_balance
from .chat import chat_manager
from .config import settings
from .database import close_database, database_ok, database_session, init_database
from .domain import owned_line, owned_project, owned_task, uid, visible_humans
from .domain import router as domain_router
from .error_logging import record_api_error, request_payload
from .jobs import jobs
from .media_constraints import normalize_video_duration
from .models import AiModelModel, DigitalHumanModel, GenerationJobModel, ProjectCastModel, ProjectTaskModel, SongEmotionProfileModel, StoryboardLineModel, UserModel
from .providers import generate_image, generate_video, resume_generation
from .redis_store import close_redis, redis_ok
from .request_logging import api_request_log_middleware
from .schemas import ChatMessageCreate, ChatSessionCreate, ImageGenerationCreate, LoginCreate, PasswordChange, RemoteImportCreate, VideoGenerationCreate
from .seed import ensure_pending_asset_avatars, recover_stale_storyboard_generation, seed_system_data
from .storage import get_storage, import_remote, make_image_thumbnail, safe_key
from .usage_quota import consume_daily_quota

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_database()
    await seed_admin()
    await seed_system_data()
    await recover_stale_storyboard_generation()
    # 数字人虚拟资产注册（系统 + 用户上传）：后台执行（幂等），生成视频时用 asset:// 链接过真人人脸校验
    asyncio.create_task(ensure_pending_asset_avatars())
    recovered = await jobs.recover_stale_jobs(resume_generation)
    if recovered["resumed"] or recovered["failed"]:
        logger.info("媒体生成任务恢复：续跑 %s 个，判败 %s 个", recovered["resumed"], recovered["failed"])
    yield
    await close_redis()
    await close_database()


app = FastAPI(title="MV Agent API", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
# 测试流量耗时采集：仅带 X-Test-Run-Id 头或 API_REQUEST_LOG_ALL=true 时入库
app.middleware("http")(api_request_log_middleware)
app.include_router(domain_router)
app.include_router(admin_router)
app.include_router(model_options_router)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = str(exc.detail)
    error_code = await record_api_error(request, status_code=exc.status_code, error_type=type(exc).__name__, message=detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail, "errorCode": error_code}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    def translated(item: dict) -> str:
        field = ".".join(str(value) for value in item["loc"] if value not in {"body", "query", "path"}) or "请求参数"
        kind, context = item.get("type", ""), item.get("ctx") or {}
        messages = {
            "missing": "不能为空",
            "string_type": "必须是文本",
            "list_type": "必须是数组",
            "bool_type": "必须是布尔值",
            "int_type": "必须是整数",
            "int_parsing": "必须是整数",
            "float_type": "必须是数值",
            "float_parsing": "必须是数值",
            "literal_error": "不是支持的选项",
            "string_too_short": f"长度不能少于 {context.get('min_length')} 个字符",
            "string_too_long": f"长度不能超过 {context.get('max_length')} 个字符",
            "greater_than": f"必须大于 {context.get('gt')}",
            "greater_than_equal": f"必须大于等于 {context.get('ge')}",
            "less_than": f"必须小于 {context.get('lt')}",
            "less_than_equal": f"必须小于等于 {context.get('le')}",
        }
        return f"{field}：{messages.get(kind, '格式或取值不正确')}"

    message = "；".join(translated(item) for item in exc.errors())
    error_code = await record_api_error(request, status_code=422, error_type=type(exc).__name__, message=message, exc=exc, payload=await request_payload(request))
    return JSONResponse(status_code=422, content={"detail": message, "errorCode": error_code})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_code = await record_api_error(request, status_code=500, error_type=type(exc).__name__, message=str(exc), exc=exc)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误", "errorCode": error_code})


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def require_active_model(db: AsyncSession, code: str, modality: str) -> None:
    model = (
        await db.execute(
            select(AiModelModel).where(AiModelModel.code == code, AiModelModel.modality == modality, AiModelModel.status == "active", AiModelModel.deleted_at.is_(None))
        )
    ).scalar_one_or_none()
    if not model:
        label = {"chat": "文本", "image": "图片", "video": "视频", "audio": "音频"}.get(modality, "生成")
        raise HTTPException(422, f"不支持或已停用的{label}模型：{code}")


@app.get("/api/health")
async def health(response: Response) -> dict:
    postgres, redis = await database_ok(), await redis_ok()
    if not postgres or not redis:
        response.status_code = 503
    return {
        "ok": postgres and redis,
        "postgres": postgres,
        "redis": redis,
        "storage": settings.storage_backend,
        "chatConfigured": bool(settings.llm_api_key),
        "imageConfigured": bool(settings.image_api_key),
        "videoConfigured": bool(settings.video_api_key),
    }


@app.get("/api/account/balance")
async def account_balance(_user: CurrentUser, force: bool = False) -> dict:
    return await query_business_balance(force=force)


@app.post("/api/auth/login")
async def auth_login(payload: LoginCreate, request: Request, response: Response) -> dict:
    user = await login(payload.username, payload.password)
    if not user:
        raise HTTPException(401, "用户名或密码错误")
    return await issue_tokens(user, request, response)


@app.post("/api/auth/refresh")
async def auth_refresh(request: Request, response: Response, refresh: Annotated[str | None, Depends(refresh_cookie_value)]) -> dict:
    user = await rotate_refresh(refresh)
    if not user:
        clear_refresh_cookie(response)
        raise HTTPException(401, "刷新凭证无效或已过期")
    return await issue_tokens(user, request, response)


@app.post("/api/auth/logout")
async def auth_logout(response: Response, refresh: Annotated[str | None, Depends(refresh_cookie_value)]) -> dict:
    await revoke_refresh(refresh)
    clear_refresh_cookie(response)
    return {"ok": True}


@app.get("/api/auth/me")
async def auth_me(user: CurrentUser) -> dict:
    return user_public(user)


@app.post("/api/auth/change-password")
async def change_password(payload: PasswordChange, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(422, "当前密码错误")
    if payload.current_password == payload.new_password:
        raise HTTPException(422, "新密码不能与当前密码相同")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    await db.commit()
    return {"ok": True}


@app.post("/api/uploads")
async def upload(user: CurrentUser, file: UploadFile = File(...), category: str = "uploads") -> dict:
    content = await file.read(100 * 1024 * 1024 + 1)
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(413, "文件不能超过 100MB")
    key = safe_key(f"users/{user.id}/{category}", file.filename or "upload.bin")
    if (file.content_type or "").startswith("image/"):
        try:
            thumbnail = make_image_thumbnail(content)
        except (UnidentifiedImageError, OSError) as exc:
            raise HTTPException(422, "图片文件无法解析") from exc
        storage = get_storage()
        url = await storage.put_bytes(key, content, file.content_type)
        thumbnail_url = await storage.put_bytes(f"{key.rsplit('.', 1)[0]}-thumbnail.jpg", thumbnail, "image/jpeg")
    else:
        url = await get_storage().put_bytes(key, content, file.content_type)
        thumbnail_url = None
    return {"url": url, "thumbnailUrl": thumbnail_url, "key": key, "filename": file.filename}


@app.post("/api/uploads/import")
async def remote_import(payload: RemoteImportCreate, user: CurrentUser) -> dict:
    try:
        url = await import_remote(payload.url, f"users/{user.id}/{payload.category}", payload.filename)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"url": url}


@app.post("/api/storyboards/ass")
async def create_ass_storyboard(
    user: CurrentUser,
    project_id: str = Form(...),
    song_id: str = Form(...),
    ass_file: UploadFile = File(...),
    digital_human_ids: str = Form("[]"),
    extra_requirement: str = Form(""),
    ratio: Literal["16:9", "9:16", "4:3", "1:1"] = Form("16:9"),
    resolution: Literal["480p", "720p", "1080p"] = Form("480p"),
    image_model: str = Form("gpt-image-2"),
    video_model: str = Form("doubao-seedance-2.0"),
    db: AsyncSession = Depends(database_session),
) -> dict:
    await owned_project(db, user.id, project_id)
    await require_active_model(db, image_model, "image")
    await require_active_model(db, video_model, "video")
    if not ass_file.filename or not ass_file.filename.lower().endswith(".ass"):
        raise HTTPException(422, "仅支持 .ass 文件")
    number_candidates = list(dict.fromkeys(re.findall(r"(?<!\d)\d{5,}(?!\d)", ass_file.filename)))
    if not number_candidates:
        raise HTTPException(422, "ASS 文件名中未找到歌曲数字编号，请使用包含歌曲编号的文件名")
    profiles = list(
        (await db.execute(select(SongEmotionProfileModel).where(SongEmotionProfileModel.song_code.in_(number_candidates), SongEmotionProfileModel.deleted_at.is_(None))))
        .scalars()
        .all()
    )
    if not profiles:
        raise HTTPException(422, f"ASS 文件名中的编号 {', '.join(number_candidates)} 未匹配到歌曲情感标注数据")
    if len(profiles) > 1:
        raise HTTPException(422, "ASS 文件名包含多个可匹配的歌曲编号，请保留唯一编号")
    emotion = profiles[0]
    if song_id.strip() and song_id.strip() != emotion.song_code:
        raise HTTPException(422, f"输入的歌曲编号 {song_id.strip()} 与 ASS 文件名编号 {emotion.song_code} 不一致")
    emotion_context = {
        "songCode": emotion.song_code,
        "songName": emotion.song_name,
        "artists": emotion.artists,
        "primaryCategory": emotion.primary_category,
        "secondaryCategory": emotion.secondary_category,
        "tertiaryCategory": emotion.tertiary_category,
        "materialCategory": emotion.material_category,
        "seasons": emotion.seasons,
        "atmosphere": emotion.atmosphere,
    }
    content = await ass_file.read(5 * 1024 * 1024 + 1)
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(422, "ASS 文件必须大于 0 且不超过 5MB")
    try:
        role_ids = json.loads(digital_human_ids)
        if not isinstance(role_ids, list) or not all(isinstance(value, str) for value in role_ids):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, "digital_human_ids 必须是字符串数组") from exc
    visible = await visible_humans(db, user.id, role_ids)
    if len({item.id for item in visible}) != len(set(role_ids)):
        raise HTTPException(422, "包含不可用角色")
    try:
        cues, encoding = parse_ass(content)
        segments = group_cues(cues)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    ass_url = await get_storage().put_bytes(safe_key(f"users/{user.id}/ass", ass_file.filename), content, ass_file.content_type)
    title = f"{emotion.song_name} – {emotion.song_code}"
    task = ProjectTaskModel(
        id=uid("task"),
        project_id=project_id,
        title=title,
        storyboard_type="ass",
        status="parsed",
        source_ass_url=ass_url,
        extra_requirement=extra_requirement.strip(),
        overall_prompt=extra_requirement.strip(),
        storyboard_config={
            "songId": emotion.song_code,
            "songEmotion": emotion_context,
            "ratio": ratio,
            "resolution": resolution,
            "imageModel": image_model,
            "videoModel": video_model,
            "meta": {"encoding": encoding, "dialogues": len(cues), "segments": len(segments)},
        },
    )
    db.add(task)
    await db.flush()
    for index, human_id in enumerate(role_ids):
        db.add(ProjectCastModel(id=uid("cast"), project_task_id=task.id, digital_human_id=human_id, sort_order=index))
    result_lines = []
    for index, value in enumerate(segments):
        source_duration = round(max(0.0, float(value.get("end") or 0) - float(value.get("start") or 0)), 2)
        gap_before = round(max(0.0, float(value.get("start") or 0) - float(segments[index - 1].get("end") or value.get("start") or 0)), 2) if index else 0.0
        gap_after = round(max(0.0, float(segments[index + 1].get("start") or value.get("end") or 0) - float(value.get("end") or 0)), 2) if index + 1 < len(segments) else 0.0
        planned_duration = float(normalize_video_duration(source_duration))
        shot_options = {
            "ratio": ratio,
            "resolution": resolution,
            "imageModel": image_model,
            "videoModel": video_model,
            "duration": normalize_video_duration(source_duration),
            "materialDuration": source_duration,
            "segmentType": value.get("segmentType", "lyric"),
            "timelineLabel": value.get("timelineLabel") or value.get("lyrics", ""),
            "sourceDuration": source_duration,
            "gapBefore": gap_before,
            "gapAfter": gap_after,
            "gapAfterAllocation": "none",
            "outlineStatus": "pending",
        }
        line = StoryboardLineModel(
            id=uid("line"),
            project_task_id=task.id,
            sort_order=index,
            source="ass",
            shot_type="empty",
            lyrics=value.get("lyrics", ""),
            start_time=value.get("start"),
            end_time=value.get("end"),
            planned_duration=planned_duration,
            scene_prompt="",
            shot_prompt="",
            shot_options=shot_options,
            generation_status="pending",
        )
        db.add(line)
        await db.flush()
        result_lines.append(
            {
                **value,
                "id": line.id,
                "shotType": "empty",
                "plannedDuration": planned_duration,
                "shotOptions": shot_options,
                "scenePrompt": "",
                "shotPrompt": "",
                "digitalHumanIds": [],
                "generationStatus": "pending",
            }
        )
    await db.commit()
    return {
        "title": title,
        "cast": role_ids,
        "taskId": task.id,
        "projectId": project_id,
        "sourceAssUrl": ass_url,
        "status": "parsed",
        "songEmotion": emotion_context,
        "lines": result_lines,
    }


async def generation_context(user: UserModel, task_id: str | None, line_id: str | None, db: AsyncSession) -> tuple[str | None, str | None, str | None]:
    if not task_id and not line_id:
        return None, None, None
    if line_id:
        line = await owned_line(db, user.id, line_id)
        task = await owned_task(db, user.id, line.project_task_id)
        if task_id and task.id != task_id:
            raise HTTPException(422, "分镜不属于指定子项目")
    else:
        task = await owned_task(db, user.id, task_id or "")
    return task.project_id, task.id, line_id


async def _check_concurrency(db: AsyncSession, user_id: str, kind: str, limit: int) -> None:
    """检查单用户同类型生成任务的并发数，超限抛出 429。"""
    from sqlalchemy import func

    count = (
        await db.execute(
            select(func.count(GenerationJobModel.id)).where(
                GenerationJobModel.user_id == user_id,
                GenerationJobModel.kind == kind,
                GenerationJobModel.deleted_at.is_(None),
                GenerationJobModel.status.in_(("queued", "running")),
            )
        )
    ).scalar_one()
    if count >= limit:
        label = "视频" if kind == "video" else "图片"
        raise HTTPException(429, f"同时进行的{label}生成已达上限（{limit}个），请等待部分任务完成后再提交")


@app.post("/api/generations/images", status_code=202)
async def create_image_generation(payload: ImageGenerationCreate, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    await require_active_model(db, payload.model or settings.image_model, "image")
    project_id, task_id, line_id = await generation_context(user, payload.project_task_id, payload.storyboard_line_id, db)
    await _check_concurrency(db, user.id, "image", 20)
    await consume_daily_quota(db, user_id=user.id, category="image", limit=settings.daily_image_limit)
    job = await jobs.create(
        "image",
        payload.model_dump(mode="json"),
        lambda item: generate_image(payload, item),
        user_id=user.id,
        project_id=project_id,
        project_task_id=task_id,
        storyboard_line_id=line_id,
    )
    return job.public()


async def _resolve_asset_avatar_urls(db: AsyncSession, image_urls: list[str]) -> list[str]:
    """把数字人头像 TOS 路径替换为 AIGC 平台 asset:// 链接（过真人人脸校验）；非头像 URL 原样保留。"""
    if not image_urls:
        return image_urls
    humans = (
        (
            await db.execute(
                select(DigitalHumanModel).where(
                    DigitalHumanModel.deleted_at.is_(None),
                    DigitalHumanModel.asset_avatar_url.isnot(None),
                    DigitalHumanModel.asset_avatar_url != "",
                )
            )
        )
        .scalars()
        .all()
    )
    lookup: dict[str, str] = {}
    for human in humans:
        lookup[human.avatar_url] = human.asset_avatar_url
        if human.avatar_thumbnail_url:
            lookup[human.avatar_thumbnail_url] = human.asset_avatar_url
    return [lookup.get(url, url) for url in image_urls]


@app.post("/api/generations/videos", status_code=202)
async def create_video_generation(payload: VideoGenerationCreate, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    await require_active_model(db, payload.model or settings.video_model, "video")
    project_id, task_id, line_id = await generation_context(user, payload.project_task_id, payload.storyboard_line_id, db)
    await _check_concurrency(db, user.id, "video", 20)
    await consume_daily_quota(db, user_id=user.id, category="video", limit=settings.daily_video_limit)
    # 数字人头像优先用平台虚拟资产（asset://），其余 URL（如场景图）原样保留
    payload.image_urls = await _resolve_asset_avatar_urls(db, payload.image_urls)
    job = await jobs.create(
        "video",
        payload.model_dump(mode="json"),
        lambda item: generate_video(payload, item),
        user_id=user.id,
        project_id=project_id,
        project_task_id=task_id,
        storyboard_line_id=line_id,
    )
    return job.public()


@app.get("/api/generations/{job_id}")
async def get_generation(job_id: str, user: CurrentUser) -> dict:
    job = await jobs.get(job_id, user.id)
    if not job:
        raise HTTPException(404, "生成任务不存在")
    return job.public()


@app.get("/api/tasks/{task_id}/generations/active")
async def list_active_task_generations(task_id: str, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> list[dict]:
    """任务下仍在排队/执行中的媒体生成任务（页面刷新后前端据此恢复等待态）"""
    await owned_task(db, user.id, task_id)
    rows = (
        (
            await db.execute(
                select(GenerationJobModel).where(
                    GenerationJobModel.project_task_id == task_id,
                    GenerationJobModel.user_id == user.id,
                    GenerationJobModel.deleted_at.is_(None),
                    GenerationJobModel.status.in_(("queued", "running")),
                )
            )
        )
        .scalars()
        .all()
    )
    return [{"id": row.id, "kind": row.kind, "storyboardLineId": row.storyboard_line_id, "progress": row.progress} for row in rows]


@app.get("/api/generations/{job_id}/events")
async def generation_events(job_id: str, request: Request, user: CurrentUser) -> StreamingResponse:
    if not await jobs.get(job_id, user.id):
        raise HTTPException(404, "生成任务不存在")

    async def stream():
        last = None
        while not await request.is_disconnected():
            job = await jobs.get(job_id, user.id)
            if not job:
                return
            marker = (job.status, job.progress, job.updated_at)
            if marker != last:
                yield sse({"type": "job", "job": job.public()})
                last = marker
            if job.status in {"succeeded", "failed", "cancelled"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/chat/sessions")
async def list_chat_sessions(user: CurrentUser) -> list[dict]:
    return await chat_manager.list(user.id)


@app.post("/api/chat/sessions", status_code=201)
async def create_chat_session(payload: ChatSessionCreate, user: CurrentUser) -> dict:
    return (await chat_manager.create(user.id, payload.system_prompt)).summary()


async def chat_or_404(user_id: str, session_id: str):
    session = await chat_manager.get(user_id, session_id)
    if not session:
        raise HTTPException(404, "对话不存在")
    return session


@app.get("/api/chat/{session_id}")
async def get_chat_session(session_id: str, user: CurrentUser) -> dict:
    session = await chat_or_404(user.id, session_id)
    return {**session.summary(), "messages": session.messages}


@app.post("/api/chat/{session_id}/messages", status_code=202)
async def post_chat_message(session_id: str, payload: ChatMessageCreate, user: CurrentUser) -> dict:
    session = await chat_or_404(user.id, session_id)
    try:
        last_seq = await chat_manager.post(session, payload.text.strip(), daily_limit=settings.daily_chat_limit)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "lastSeq": last_seq}


@app.post("/api/chat/{session_id}/interrupt")
async def interrupt_chat(session_id: str, user: CurrentUser) -> dict:
    await chat_or_404(user.id, session_id)
    await chat_manager.interrupt(session_id)
    return {"ok": True}


@app.delete("/api/chat/{session_id}")
async def delete_chat(session_id: str, user: CurrentUser) -> dict:
    if not await chat_manager.delete(user.id, session_id):
        raise HTTPException(404, "对话不存在")
    return {"ok": True}


@app.get("/api/chat/{session_id}/events")
async def chat_events(session_id: str, request: Request, user: CurrentUser, after: int = 0) -> StreamingResponse:
    session = await chat_or_404(user.id, session_id)

    async def stream():
        cursor = after
        yield sse({"type": "hello", "session": session.summary()})
        while not await request.is_disconnected():
            fresh = await chat_manager.events_after(user.id, session_id, cursor)
            if fresh:
                for event in fresh:
                    cursor = event["seq"]
                    yield sse({"type": "event", "event": event})
            else:
                yield sse({"type": "heartbeat", "ts": time.time()})
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})
