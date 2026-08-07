from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .ass_storyboard import group_cues, parse_ass
from .auth import (
    CurrentUser,
    REFRESH_COOKIE,
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
from .chat import chat_manager
from .config import settings
from .database import close_database, database_ok, database_session, init_database
from .domain import owned_line, owned_project, owned_task, router as domain_router, uid, visible_humans
from .jobs import jobs
from .media_constraints import normalize_video_duration
from .models import ProjectCastModel, ProjectTaskModel, SongEmotionProfileModel, StoryboardLineCastModel, StoryboardLineModel, UserModel
from .providers import generate_image, generate_video
from .redis_store import close_redis, redis_ok
from .schemas import ChatMessageCreate, ChatSessionCreate, ImageGenerationCreate, LoginCreate, PasswordChange, RemoteImportCreate, VideoGenerationCreate
from .storage import get_storage, import_remote, safe_key
from .seed import recover_stale_storyboard_generation, seed_system_data
from .story_bible import build_ass_story_bible
from .error_logging import record_api_error, request_payload


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_database()
    await seed_admin()
    await seed_system_data()
    await recover_stale_storyboard_generation()
    yield
    await close_redis()
    await close_database()


app = FastAPI(title="MV Agent API", version="0.3.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
app.include_router(domain_router)


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = str(exc.detail)
    error_code = await record_api_error(request, status_code=exc.status_code, error_type=type(exc).__name__, message=detail)
    return JSONResponse(status_code=exc.status_code, content={"detail": detail, "errorCode": error_code}, headers=exc.headers)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    message = "; ".join(f"{'.'.join(map(str, item['loc']))}: {item['msg']}" for item in exc.errors())
    error_code = await record_api_error(request, status_code=422, error_type=type(exc).__name__, message=message, exc=exc, payload=await request_payload(request))
    return JSONResponse(status_code=422, content={"detail": message, "errorCode": error_code})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    error_code = await record_api_error(request, status_code=500, error_type=type(exc).__name__, message=str(exc), exc=exc)
    return JSONResponse(status_code=500, content={"detail": "服务器内部错误", "errorCode": error_code})


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/health")
async def health(response: Response) -> dict:
    postgres, redis = await database_ok(), await redis_ok()
    if not postgres or not redis:
        response.status_code = 503
    return {"ok": postgres and redis, "postgres": postgres, "redis": redis, "storage": settings.storage_backend, "chatConfigured": bool(settings.llm_api_key), "imageConfigured": bool(settings.image_api_key), "videoConfigured": bool(settings.video_api_key)}


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
    url = await get_storage().put_bytes(key, content, file.content_type)
    return {"url": url, "key": key, "filename": file.filename}


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
    db: AsyncSession = Depends(database_session),
) -> dict:
    await owned_project(db, user.id, project_id)
    if not ass_file.filename or not ass_file.filename.lower().endswith(".ass"):
        raise HTTPException(422, "仅支持 .ass 文件")
    number_candidates = list(dict.fromkeys(re.findall(r"(?<!\d)\d{5,}(?!\d)", ass_file.filename)))
    if not number_candidates:
        raise HTTPException(422, "ASS 文件名中未找到歌曲数字编号，请使用包含歌曲编号的文件名")
    profiles = list((await db.execute(select(SongEmotionProfileModel).where(SongEmotionProfileModel.song_code.in_(number_candidates), SongEmotionProfileModel.deleted_at.is_(None)))).scalars().all())
    if not profiles:
        raise HTTPException(422, f"ASS 文件名中的编号 {', '.join(number_candidates)} 未匹配到歌曲情感标注数据")
    if len(profiles) > 1:
        raise HTTPException(422, "ASS 文件名包含多个可匹配的歌曲编号，请保留唯一编号")
    emotion = profiles[0]
    if song_id.strip() and song_id.strip() != emotion.song_code:
        raise HTTPException(422, f"输入的歌曲编号 {song_id.strip()} 与 ASS 文件名编号 {emotion.song_code} 不一致")
    emotion_context = {
        "songCode": emotion.song_code, "songName": emotion.song_name, "artists": emotion.artists,
        "primaryCategory": emotion.primary_category, "secondaryCategory": emotion.secondary_category,
        "tertiaryCategory": emotion.tertiary_category, "materialCategory": emotion.material_category,
        "seasons": emotion.seasons, "atmosphere": emotion.atmosphere,
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
    title = f"ASS 分镜 · {emotion.song_code} · {emotion.song_name}"
    story_bible = build_ass_story_bible(segments=segments, emotion=emotion_context, role_ids=role_ids, extra_requirement=extra_requirement.strip())
    task = ProjectTaskModel(id=uid("task"), project_id=project_id, title=title, storyboard_type="ass", status="generating", source_ass_url=ass_url, extra_requirement=extra_requirement.strip(), overall_prompt=extra_requirement.strip(), storyboard_config={"songId": emotion.song_code, "songEmotion": emotion_context, "storyBible": story_bible, "meta": {"encoding": encoding, "dialogues": len(cues), "segments": len(segments)}})
    db.add(task)
    await db.flush()
    for index, human_id in enumerate(role_ids):
        db.add(ProjectCastModel(id=uid("cast"), project_task_id=task.id, digital_human_id=human_id, sort_order=index))
    result_lines = []
    for index, value in enumerate(segments):
        assigned_roles = [role_ids[index % len(role_ids)]] if role_ids else []
        planned_duration = round(float(value.get("end") or 0) - float(value.get("start") or 0), 1)
        line = StoryboardLineModel(id=uid("line"), project_task_id=task.id, sort_order=index, source="ass", lyrics=value.get("lyrics", ""), start_time=value.get("start"), end_time=value.get("end"), planned_duration=planned_duration, scene_prompt="", shot_prompt="", shot_options={"ratio": "16:9", "duration": normalize_video_duration(planned_duration)}, generation_status="pending")
        db.add(line)
        await db.flush()
        for role_index, human_id in enumerate(assigned_roles):
            db.add(StoryboardLineCastModel(id=uid("linecast"), storyboard_line_id=line.id, digital_human_id=human_id, sort_order=role_index))
        result_lines.append({**value, "id": line.id, "plannedDuration": planned_duration, "scenePrompt": "", "shotPrompt": "", "digitalHumanIds": assigned_roles, "generationStatus": "pending"})
    await db.commit()
    return {"title": title, "cast": role_ids, "taskId": task.id, "projectId": project_id, "sourceAssUrl": ass_url, "status": "generating", "songEmotion": emotion_context, "lines": result_lines}


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


@app.post("/api/generations/images", status_code=202)
async def create_image_generation(payload: ImageGenerationCreate, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    project_id, task_id, line_id = await generation_context(user, payload.project_task_id, payload.storyboard_line_id, db)
    job = await jobs.create("image", payload.model_dump(mode="json"), lambda item: generate_image(payload, item), user_id=user.id, project_id=project_id, project_task_id=task_id, storyboard_line_id=line_id)
    return job.public()


@app.post("/api/generations/videos", status_code=202)
async def create_video_generation(payload: VideoGenerationCreate, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    project_id, task_id, line_id = await generation_context(user, payload.project_task_id, payload.storyboard_line_id, db)
    job = await jobs.create("video", payload.model_dump(mode="json"), lambda item: generate_video(payload, item), user_id=user.id, project_id=project_id, project_task_id=task_id, storyboard_line_id=line_id)
    return job.public()


@app.get("/api/generations/{job_id}")
async def get_generation(job_id: str, user: CurrentUser) -> dict:
    job = await jobs.get(job_id, user.id)
    if not job:
        raise HTTPException(404, "生成任务不存在")
    return job.public()


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
        last_seq = await chat_manager.post(session, payload.text.strip())
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
