from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from contextlib import asynccontextmanager, suppress
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from PIL import UnidentifiedImageError
from pydantic import BaseModel
from sqlalchemy import select, update
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
    revoke_all_refresh_tokens,
    revoke_refresh,
    rotate_refresh,
    seed_admin,
    user_public,
    verify_password,
)
from .balance import query_business_balance
from .chat import chat_manager
from .config import settings, validate_runtime_security
from .database import close_database, database_ok, database_session, init_database
from .domain import owned_line, owned_project, owned_task, uid, visible_humans
from .domain import router as domain_router
from .error_logging import record_api_error, request_payload
from .h3_prompt_compiler import compile_h3_prompt
from .jobs import jobs
from .media_constraints import normalize_video_duration
from .models import (
    AiModelModel,
    AiProviderModel,
    DigitalHumanModel,
    GenerationJobModel,
    ProjectCastModel,
    ProjectTaskModel,
    SongEmotionProfileModel,
    StoryboardLineModel,
    UserModel,
    utcnow,
)
from .prompts import get_prompt
from .providers import generate_image, generate_video, resume_generation
from .redis_store import clear_login_attempts, close_redis, login_attempt_count, record_login_failure, redis_ok
from .request_logging import api_request_log_middleware
from .schemas import (
    ChatMessageCreate,
    ChatSessionCreate,
    GenerationObservedRequest,
    GenerationStatusBatchRequest,
    ImageGenerationCreate,
    LoginCreate,
    PasswordChange,
    PortraitPromptParams,
    RemoteImportCreate,
    VideoGenerationCreate,
)
from .seed import recover_stale_storyboard_generation, seed_system_data
from .storage import get_storage, import_remote, make_image_thumbnail, safe_key
from .usage_quota import consume_daily_quota

logger = logging.getLogger(__name__)

ALLOWED_UPLOAD_TYPES: dict[str, set[str]] = {
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".webp": {"image/webp"},
    ".gif": {"image/gif"},
    ".mp4": {"video/mp4"},
    ".mov": {"video/quicktime"},
    ".webm": {"video/webm"},
    ".mp3": {"audio/mpeg", "audio/mp3"},
    ".wav": {"audio/wav", "audio/x-wav", "audio/vnd.wave"},
    ".m4a": {"audio/mp4", "audio/x-m4a"},
    ".ogg": {"audio/ogg", "video/ogg"},
}


def validate_media_upload(file: UploadFile) -> None:
    filename = file.filename or ""
    suffix = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    content_type = (file.content_type or "").lower().split(";", 1)[0]
    if suffix not in ALLOWED_UPLOAD_TYPES or content_type not in ALLOWED_UPLOAD_TYPES[suffix]:
        raise HTTPException(422, "仅支持常见图片、视频和音频格式，且文件扩展名必须与 MIME 类型一致")


async def stale_generation_reaper() -> None:
    """定期收编 API 进程重启后遗留的僵尸生成状态。"""
    while True:
        await asyncio.sleep(60)
        try:
            await recover_stale_storyboard_generation()
        except Exception:
            logger.exception("僵尸生成任务巡检失败")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_runtime_security()
    await init_database()
    await seed_admin()
    await seed_system_data()
    await recover_stale_storyboard_generation()
    # 数字人虚拟资产补注册由 cron 脚本每分钟执行（scripts/ensure_asset_avatars.py，带防重入锁），
    # 不再在启动时重复扫描，避免与 cron 并发导致同一人物重复注册资产
    if settings.job_execution_mode != "worker":
        recovered = await jobs.recover_stale_jobs(resume_generation)
        if recovered["resumed"] or recovered["failed"]:
            logger.info("媒体生成任务恢复：续跑 %s 个，判败 %s 个", recovered["resumed"], recovered["failed"])
    reaper = asyncio.create_task(stale_generation_reaper())
    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
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


async def require_active_model(db: AsyncSession, code: str, modality: str) -> tuple[AiModelModel, AiProviderModel]:
    row = (
        await db.execute(
            select(AiModelModel, AiProviderModel)
            .join(AiProviderModel, AiProviderModel.id == AiModelModel.provider_id)
            .where(
                AiModelModel.code == code,
                AiModelModel.modality == modality,
                AiModelModel.status == "active",
                AiModelModel.deleted_at.is_(None),
                AiProviderModel.status == "active",
                AiProviderModel.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if not row:
        label = {"chat": "文本", "image": "图片", "video": "视频", "audio": "音频"}.get(modality, "生成")
        raise HTTPException(422, f"不支持或已停用的{label}模型：{code}")
    return row


def generation_request_snapshot(payload: BaseModel, model: AiModelModel, provider: AiProviderModel) -> dict:
    capabilities = dict(model.capabilities or {})
    default_pool = "yinghe-generation" if provider.code == "yinghe" else f"{provider.code}:{model.modality}"
    return {
        **payload.model_dump(mode="json"),
        "_provider": provider.code,
        "_providerModelId": model.provider_model_id,
        "_capabilities": capabilities,
        "_executionPool": capabilities.get("executionPool") or default_pool,
        "_executionConcurrency": capabilities.get("executionConcurrency") or settings.provider_generation_worker_concurrency,
    }


def validate_video_references(payload: VideoGenerationCreate, capabilities: dict) -> None:
    for field, capability_key, label in (
        (payload.image_urls, "referenceImage", "图片"),
        (payload.video_urls, "referenceVideo", "视频"),
        (payload.audio_urls, "referenceAudio", "音频"),
    ):
        rule = capabilities.get(capability_key)
        if not isinstance(rule, dict):
            continue
        minimum, maximum = int(rule.get("min") or 0), int(rule.get("max") or 0)
        if len(field) < minimum:
            raise HTTPException(422, f"该视频模型至少需要 {minimum} 个参考{label}")
        if len(field) > maximum:
            supported = "暂不支持" if maximum == 0 else f"最多支持 {maximum} 个"
            raise HTTPException(422, f"该视频模型{supported}参考{label}")
    total_maximum = int(capabilities.get("referenceTotalMax") or 0)
    total = len(payload.image_urls) + len(payload.video_urls) + len(payload.audio_urls)
    if total_maximum and total > total_maximum:
        raise HTTPException(422, f"该视频模型所有参考文件合计最多支持 {total_maximum} 个")
    if capabilities.get("referenceAudioRequiresVisual") and payload.audio_urls and not (payload.image_urls or payload.video_urls):
        raise HTTPException(422, "该视频模型的参考音频不能单独使用，必须同时提供图片或视频")


def validate_h3_mode_inputs(payload: VideoGenerationCreate) -> None:
    """H3 产品模式约束；尾帧模式当前明确不开放。"""
    mode = payload.h3_mode
    images, videos, audios = payload.image_urls, payload.video_urls, payload.audio_urls
    if mode == "text" and (images or videos or audios):
        raise HTTPException(422, "H3 纯文本模式不能提供参考素材")
    if mode == "first_frame" and (len(images) != 1 or videos or audios):
        raise HTTPException(422, "H3 首帧模式必须且只能提供 1 张首帧图片")
    if mode == "first_last" and (len(images) != 2 or videos or audios):
        raise HTTPException(422, "H3 首尾帧模式必须且只能提供首帧、尾帧两张图片")
    if mode == "reference":
        if len(images) > 6 or len(videos) > 1 or len(audios) > 3:
            raise HTTPException(422, "H3 多参考模式最多支持 6 张图片、1 段视频和 3 段音频")
        if audios and not (images or videos):
            raise HTTPException(422, "H3 多参考音频不能单独使用，必须同时提供图片或视频")
        if not (images or videos):
            raise HTTPException(422, "H3 多参考模式至少需要 1 张图片或 1 段视频")


@app.get("/api/health")
async def health(response: Response) -> dict:
    postgres, redis = await database_ok(), await redis_ok()
    if not postgres or not redis:
        response.status_code = 503
    return {"ok": postgres and redis}


@app.get("/api/account/balance")
async def account_balance(_user: CurrentUser, force: bool = False) -> dict:
    return await query_business_balance(force=force)


@app.post("/api/auth/login")
async def auth_login(payload: LoginCreate, request: Request, response: Response) -> dict:
    client_ip = request.client.host if request.client else "unknown"
    username = payload.username.strip().lower()
    identities = (
        hashlib.sha256(f"ip\0{client_ip}".encode()).hexdigest(),
        hashlib.sha256(f"username\0{username}".encode()).hexdigest(),
    )
    try:
        attempts = max(await asyncio.gather(*(login_attempt_count(identity) for identity in identities)))
    except Exception:
        logger.exception("登录限流存储不可用")
        attempts = 1
    if attempts >= settings.login_rate_limit_attempts:
        raise HTTPException(
            429,
            "登录尝试过于频繁，请稍后再试",
            headers={"Retry-After": str(settings.login_rate_limit_window_seconds)},
        )
    user = await login(payload.username, payload.password)
    if not user:
        try:
            await asyncio.gather(*(record_login_failure(identity, settings.login_rate_limit_window_seconds) for identity in identities))
        except Exception:
            logger.exception("记录登录失败次数异常")
        raise HTTPException(401, "用户名或密码错误")
    try:
        await asyncio.gather(*(clear_login_attempts(identity) for identity in identities))
    except Exception:
        logger.exception("清理登录限流计数失败")
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
async def change_password(
    payload: PasswordChange,
    request: Request,
    response: Response,
    user: CurrentUser,
    db: AsyncSession = Depends(database_session),
) -> dict:
    if not verify_password(user.password_hash, payload.current_password):
        raise HTTPException(422, "当前密码错误")
    if payload.current_password == payload.new_password:
        raise HTTPException(422, "新密码不能与当前密码相同")
    user.password_hash = hash_password(payload.new_password)
    user.must_change_password = False
    user.auth_version += 1
    await revoke_all_refresh_tokens(user.id, db)
    await db.commit()
    tokens = await issue_tokens(user, request, response)
    return {"ok": True, **tokens}


@app.post("/api/uploads")
async def upload(user: CurrentUser, file: UploadFile = File(...), category: str = "uploads") -> dict:
    validate_media_upload(file)
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


async def _portrait_prompt(description: str, style: str) -> str:
    """数字人定妆照提示词：模板在提示词注册中心（portrait.digital_human_ref），描述/风格的条件拼接逻辑留在代码。"""
    parts = []
    if description.strip():
        parts.append(f"角色描述：{description.strip()}")
    if style.strip():
        parts.append(f"画面风格：{style.strip()}")
    extra = "。".join(parts) + "。" if parts else ""
    return (await get_prompt("portrait.digital_human_ref")).render(extra=extra)


@app.post("/api/generations/images/portrait-prompt")
async def preview_portrait_prompt(payload: PortraitPromptParams, user: CurrentUser) -> dict:
    """按当前注册中心模板拼装定妆照提示词（不调模型、不落库）；前端用于草稿恢复与重生兜底。"""
    return {"prompt": await _portrait_prompt(payload.description, payload.style)}


@app.post("/api/generations/images", status_code=202)
async def create_image_generation(payload: ImageGenerationCreate, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    if payload.portrait is not None:
        payload.prompt = await _portrait_prompt(payload.portrait.description, payload.portrait.style)
    if not payload.prompt.strip():
        raise HTTPException(422, "prompt 与 portrait 至少提供其一")
    model, provider = await require_active_model(db, payload.model or settings.image_model, "image")
    project_id, task_id, line_id = await generation_context(user, payload.project_task_id, payload.storyboard_line_id, db)
    await _check_concurrency(db, user.id, "image", settings.image_generation_concurrency)
    await consume_daily_quota(db, user_id=user.id, category="image")
    job = await jobs.create(
        "image",
        generation_request_snapshot(payload, model, provider),
        lambda item: generate_image(payload, item),
        user_id=user.id,
        project_id=project_id,
        project_task_id=task_id,
        storyboard_line_id=line_id,
    )
    # 响应携带最终生效的 prompt（portrait 模式由后端拼装），供前端落库 avatarPrompt
    return {**job.public(), "prompt": payload.prompt}


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
    model, provider = await require_active_model(db, payload.model or settings.video_model, "video")
    validate_video_references(payload, dict(model.capabilities or {}))
    if provider.code == "runninghub":
        validate_h3_mode_inputs(payload)
    project_id, task_id, line_id = await generation_context(user, payload.project_task_id, payload.storyboard_line_id, db)
    await _check_concurrency(db, user.id, "video", settings.video_generation_concurrency)
    await consume_daily_quota(db, user_id=user.id, category="video")
    # 数字人头像优先用平台虚拟资产（asset://），其余 URL（如场景图）原样保留
    if provider.code == "yinghe":
        payload.image_urls = await _resolve_asset_avatar_urls(db, payload.image_urls)
    h3_compilation = compile_h3_prompt(payload) if provider.code == "runninghub" else None
    if h3_compilation:
        payload.prompt = h3_compilation.prompt
    snapshot = generation_request_snapshot(payload, model, provider)
    if h3_compilation:
        snapshot.update(
            {
                "_sourcePrompt": h3_compilation.source_prompt,
                "_compiledPrompt": h3_compilation.prompt,
                "_h3Mode": h3_compilation.mode,
                "_promptCompiler": h3_compilation.compiler,
                "_promptCompilerVersion": h3_compilation.version,
                "_referenceBindings": h3_compilation.reference_bindings,
                "_promptWarnings": list(h3_compilation.warnings),
                "_workflowVersion": (model.capabilities or {}).get("workflowVersion"),
                "_referenceImageCount": len(payload.image_urls),
                "_referenceVideoCount": len(payload.video_urls),
                "_referenceAudioCount": len(payload.audio_urls),
            }
        )
    job = await jobs.create(
        "video",
        snapshot,
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


@app.post("/api/generations/status")
async def get_generation_status_batch(payload: GenerationStatusBatchRequest, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> list[dict]:
    """单次读取一组媒体任务状态，避免大批量生成时逐任务轮询压垮 API。"""
    job_ids = list(dict.fromkeys(payload.ids))
    rows = (
        (
            await db.execute(
                select(GenerationJobModel).where(
                    GenerationJobModel.id.in_(job_ids),
                    GenerationJobModel.user_id == user.id,
                    GenerationJobModel.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "status": row.status,
            "progress": row.progress,
            "result": row.result,
            "error": row.error,
        }
        for row in rows
    ]


@app.post("/api/generations/observed")
async def acknowledge_generation_results(payload: GenerationObservedRequest, user: CurrentUser, db: AsyncSession = Depends(database_session)) -> dict:
    """Browser acknowledgement after a terminal result has crossed the response boundary."""
    now = utcnow()
    result = await db.execute(
        update(GenerationJobModel)
        .where(
            GenerationJobModel.id.in_(list(dict.fromkeys(payload.ids))),
            GenerationJobModel.user_id == user.id,
            GenerationJobModel.status.in_(("succeeded", "failed", "cancelled")),
            GenerationJobModel.first_result_observed_at.is_(None),
            GenerationJobModel.deleted_at.is_(None),
        )
        .values(first_result_observed_at=now, updated_at=now)
    )
    await db.commit()
    return {"observed": result.rowcount}


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
    system_prompt = payload.system_prompt.strip() or (await get_prompt("chat.default_system")).render()
    return (await chat_manager.create(user.id, system_prompt)).summary()


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
