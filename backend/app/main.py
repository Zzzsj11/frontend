from __future__ import annotations

import asyncio
import json
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from .chat import chat_manager
from .config import DATA_DIR, settings
from .database import close_database, database_ok, init_database
from .jobs import jobs
from .providers import generate_image, generate_video
from .schemas import (
    ChatMessageCreate,
    ChatSessionCreate,
    ImageGenerationCreate,
    RemoteImportCreate,
    VideoGenerationCreate,
)
from .storage import get_storage, import_remote, safe_key
from .redis_store import close_redis, redis_ok
from .ass_storyboard import generate_ass_storyboard


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await init_database()
    yield
    await close_redis()
    await close_database()


app = FastAPI(title="MV Agent API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def sse(payload: dict) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@app.get("/api/health")
async def health() -> dict:
    postgres = await database_ok()
    redis = await redis_ok()
    return {
        "ok": postgres and redis,
        "postgres": postgres,
        "redis": redis,
        "storage": settings.storage_backend,
        "chatConfigured": bool(settings.llm_api_key),
        "imageConfigured": bool(settings.image_api_key),
        "videoConfigured": bool(settings.video_api_key),
    }


@app.post("/api/uploads")
async def upload(file: UploadFile = File(...), category: str = "uploads") -> dict:
    content = await file.read()
    if len(content) > 100 * 1024 * 1024:
        raise HTTPException(413, "文件不能超过 100MB")
    key = safe_key(category, file.filename or "upload.bin")
    url = await get_storage().put_bytes(key, content, file.content_type)
    return {"url": url, "key": key, "filename": file.filename}


@app.post("/api/uploads/import")
async def remote_import(payload: RemoteImportCreate) -> dict:
    return {"url": await import_remote(payload.url, payload.category, payload.filename)}


@app.post("/api/storyboards/ass")
async def create_ass_storyboard(
    song_id: str = Form(...),
    ass_file: UploadFile = File(...),
    digital_human_ids: str = Form("[]"),
    extra_requirement: str = Form(""),
) -> dict:
    if not ass_file.filename or not ass_file.filename.lower().endswith(".ass"):
        raise HTTPException(422, "仅支持 .ass 文件")
    content = await ass_file.read()
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(422, "ASS 文件必须大于 0 且不超过 5MB")
    try:
        role_ids = json.loads(digital_human_ids)
        if not isinstance(role_ids, list) or not all(isinstance(value, str) for value in role_ids):
            raise ValueError
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(422, "digital_human_ids 必须是字符串数组") from exc
    try:
        return await generate_ass_storyboard(
            song_id=song_id.strip(),
            content=content,
            digital_human_ids=role_ids,
            extra_requirement=extra_requirement.strip(),
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(502, f"ASS 分镜生成失败：{exc}") from exc


@app.post("/api/generations/images", status_code=202)
async def create_image_generation(payload: ImageGenerationCreate) -> dict:
    job = await jobs.create("image", payload.model_dump(mode="json"), lambda item: generate_image(payload, item))
    return job.public()


@app.post("/api/generations/videos", status_code=202)
async def create_video_generation(payload: VideoGenerationCreate) -> dict:
    job = await jobs.create("video", payload.model_dump(mode="json"), lambda item: generate_video(payload, item))
    return job.public()


@app.get("/api/generations/{job_id}")
async def get_generation(job_id: str) -> dict:
    job = await jobs.get(job_id)
    if not job:
        raise HTTPException(404, "生成任务不存在")
    return job.public()


@app.get("/api/generations/{job_id}/events")
async def generation_events(job_id: str, request: Request) -> StreamingResponse:
    if not await jobs.get(job_id):
        raise HTTPException(404, "生成任务不存在")

    async def stream():
        last = None
        while not await request.is_disconnected():
            job = await jobs.get(job_id)
            if not job:
                return
            snapshot = job.public()
            marker = (job.status, job.progress, job.updated_at)
            if marker != last:
                yield sse({"type": "job", "job": snapshot})
                last = marker
            if job.status in {"succeeded", "failed", "cancelled"}:
                return
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/api/chat/sessions")
async def list_chat_sessions() -> list[dict]:
    return await chat_manager.list()


@app.post("/api/chat/sessions", status_code=201)
async def create_chat_session(payload: ChatSessionCreate) -> dict:
    return (await chat_manager.create(payload.system_prompt)).summary()


async def chat_or_404(session_id: str):
    session = await chat_manager.get(session_id)
    if not session:
        raise HTTPException(404, "对话不存在")
    return session


@app.get("/api/chat/{session_id}")
async def get_chat_session(session_id: str) -> dict:
    session = await chat_or_404(session_id)
    return {**session.summary(), "messages": session.messages}


@app.post("/api/chat/{session_id}/messages", status_code=202)
async def post_chat_message(session_id: str, payload: ChatMessageCreate) -> dict:
    session = await chat_or_404(session_id)
    try:
        last_seq = await chat_manager.post(session, payload.text.strip())
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"ok": True, "lastSeq": last_seq}


@app.post("/api/chat/{session_id}/interrupt")
async def interrupt_chat(session_id: str) -> dict:
    await chat_or_404(session_id)
    await chat_manager.interrupt(session_id)
    return {"ok": True}


@app.delete("/api/chat/{session_id}")
async def delete_chat(session_id: str) -> dict:
    if not await chat_manager.delete(session_id):
        raise HTTPException(404, "对话不存在")
    return {"ok": True}


@app.get("/api/chat/{session_id}/events")
async def chat_events(session_id: str, request: Request, after: int = 0) -> StreamingResponse:
    session = await chat_or_404(session_id)

    async def stream():
        cursor = after
        yield sse({"type": "hello", "session": session.summary()})
        while not await request.is_disconnected():
            fresh = await chat_manager.events_after(session_id, cursor)
            if fresh:
                for event in fresh:
                    cursor = event["seq"]
                    yield sse({"type": "event", "event": event})
            else:
                yield sse({"type": "heartbeat", "ts": time.time()})
            await asyncio.sleep(1)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/media/{file_path:path}")
async def local_media(file_path: str) -> FileResponse:
    root = (DATA_DIR / "media").resolve()
    target = (root / file_path).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise HTTPException(403, "非法路径") from exc
    if not target.is_file():
        raise HTTPException(404, "媒体不存在")
    return FileResponse(target)
