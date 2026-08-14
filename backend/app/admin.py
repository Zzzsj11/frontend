from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentUser
from .config import settings
from .database import database_session
from .jobs import jobs as job_manager
from .models import (
    AdminOperationLogModel,
    AiModelModel,
    AiProviderModel,
    ApiErrorLogModel,
    ApiRequestLogModel,
    DigitalHumanModel,
    GenerationJobModel,
    LlmCallLogModel,
    ProjectModel,
    PromptTemplateModel,
    PromptVersionModel,
    TokenUsageModel,
    UserModel,
    utcnow,
)
from .prompts import DEFAULT_PROMPTS, invalidate, render_lenient, template_variables
from .providers import ProviderError, list_video_models, query_provider_task, resume_generation, store_provider_result

router = APIRouter(prefix="/api/admin", tags=["admin"])
Db = Depends(database_session)


def require_admin(user):
    if user.role != "admin":
        raise HTTPException(403, "需要管理员权限")


def iso(value):
    return value.isoformat() if value else None


async def audit(db, request, user, action, target_type, target_id=None, before=None, after=None):
    db.add(
        AdminOperationLogModel(
            id=f"audit-{uuid.uuid4().hex}",
            admin_user_id=user.id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            before_data=before or {},
            after_data=after or {},
            client_ip=request.client.host if request.client else None,
        )
    )


@router.get("/dashboard")
async def dashboard(user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)

    async def count(model, *where):
        return (await db.execute(select(func.count()).select_from(model).where(model.deleted_at.is_(None), *where))).scalar_one()

    usage = (
        await db.execute(
            select(
                func.coalesce(func.sum(TokenUsageModel.input_tokens), 0),
                func.coalesce(func.sum(TokenUsageModel.output_tokens), 0),
                func.coalesce(func.sum(TokenUsageModel.total_tokens), 0),
            ).where(TokenUsageModel.deleted_at.is_(None))
        )
    ).one()
    statuses = dict((await db.execute(select(GenerationJobModel.status, func.count()).where(GenerationJobModel.deleted_at.is_(None)).group_by(GenerationJobModel.status))).all())
    return {
        "users": await count(UserModel),
        "projects": await count(ProjectModel),
        "jobs": await count(GenerationJobModel),
        "systemHumans": await count(DigitalHumanModel, DigitalHumanModel.scope == "system"),
        "errors": await count(ApiErrorLogModel),
        "usage": {"inputTokens": usage[0], "outputTokens": usage[1], "totalTokens": usage[2]},
        "jobStatuses": statuses,
    }


@router.get("/projects")
async def projects(
    user: CurrentUser,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Db,
):
    """项目列表：offset 分页，limit 上限 300，防止全量拉取拖垮数据库。"""
    require_admin(user)
    limit, offset = max(1, min(limit, 300)), max(0, offset)
    conditions = [ProjectModel.deleted_at.is_(None)]
    total = (await db.execute(select(func.count()).select_from(ProjectModel).where(*conditions))).scalar_one()
    rows = (
        await db.execute(
            select(ProjectModel, UserModel.username)
            .join(UserModel, UserModel.id == ProjectModel.user_id)
            .where(*conditions)
            .order_by(ProjectModel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return {
        "total": total,
        "items": [{"id": p.id, "name": p.name, "username": u, "status": p.status, "createdAt": iso(p.created_at)} for p, u in rows],
    }


@router.get("/jobs")
async def jobs(
    user: CurrentUser,
    db: AsyncSession = Db,
    kind: str | None = None,
    status: str | None = None,
    q: str | None = None,
    page: int = 1,
    page_size: int = 50,
):
    """生成任务全量收集：含供应商 taskId，支持类型/状态/关键词筛选与分页"""
    require_admin(user)
    page = max(page, 1)
    page_size = min(max(page_size, 1), 200)
    conditions = [GenerationJobModel.deleted_at.is_(None)]
    if kind in {"image", "video"}:
        conditions.append(GenerationJobModel.kind == kind)
    if status:
        conditions.append(GenerationJobModel.status == status)
    if q and q.strip():
        term = f"%{q.strip()}%"
        conditions.append(or_(GenerationJobModel.id.ilike(term), GenerationJobModel.provider_task_id.ilike(term)))
    total = (await db.execute(select(func.count()).select_from(GenerationJobModel).where(*conditions))).scalar_one()
    stale_cutoff = utcnow() - timedelta(minutes=10)
    stale_col = case(
        (GenerationJobModel.status.in_(("queued", "running")) & (GenerationJobModel.updated_at < stale_cutoff), True),
        else_=False,
    )
    rows = (
        await db.execute(
            select(GenerationJobModel, UserModel.username, stale_col.label("stale"))
            .join(UserModel, UserModel.id == GenerationJobModel.user_id, isouter=True)
            .where(*conditions)
            .order_by(GenerationJobModel.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    items = [
        {
            "id": j.id,
            "username": username,
            "kind": j.kind,
            "status": j.status,
            "progress": j.progress,
            "provider": j.provider,
            "providerTaskId": j.provider_task_id,
            "model": (j.request or {}).get("model"),
            "storyboardLineId": j.storyboard_line_id,
            "error": j.error,
            "stale": bool(stale),
            "durationSeconds": round((j.finished_at - j.started_at).total_seconds()) if j.finished_at and j.started_at else None,
            "createdAt": iso(j.created_at),
            "finishedAt": iso(j.finished_at),
        }
        for j, username, stale in rows
    ]
    return {"total": total, "page": page, "pageSize": page_size, "items": items}


@router.post("/jobs/{job_id}/sync")
async def sync_generation_job(job_id: str, request: Request, user: CurrentUser, db: AsyncSession = Db):
    """按供应商 taskId 主动对账：已成功则补落库资产挽回结果，已失败同步原因，供应商仍在跑而本机无协程则重新挂轮询"""
    require_admin(user)
    model = await db.get(GenerationJobModel, job_id)
    if not model or model.deleted_at is not None:
        raise HTTPException(404, "任务不存在")
    if not model.provider_task_id:
        raise HTTPException(422, "该任务没有供应商任务ID，无法同步")
    if job_manager.is_active(job_id):
        return {"providerStatus": None, "action": "skipped", "detail": "任务正在本机执行中，无需同步"}
    try:
        data = await query_provider_task(model.kind, model.provider_task_id)
    except Exception as exc:
        raise HTTPException(502, f"查询供应商失败：{str(exc)[:300]}") from exc
    provider_status = str(data.get("status", "")).upper()
    action = "unchanged"
    if provider_status == "SUCCESS" and model.status != "succeeded":
        job = await job_manager.get(job_id)
        if job:
            result = await store_provider_result(job, data)
            await job_manager.finalize_success(job, result)
            action = "recovered"
    elif (provider_status in {"FAILED", "CANCELLED"} or "FAIL" in provider_status) and model.status != "failed":
        job = await job_manager.get(job_id)
        if job:
            await job_manager.finalize_failure(job, str(data.get("failReason") or f"供应商任务状态：{provider_status}"))
            action = "failed"
    elif "FAIL" not in provider_status and provider_status != "CANCELLED" and model.status in {"queued", "running"}:
        if await job_manager.resume_one(job_id, resume_generation):
            action = "resumed"
    await audit(db, request, user, "job.sync", "generation_job", job_id, after={"providerStatus": provider_status, "action": action})
    await db.commit()
    return {"providerStatus": provider_status, "action": action, "progress": data.get("progress")}


@router.get("/usage")
async def usage(user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    rows = (
        await db.execute(
            select(
                TokenUsageModel.model,
                TokenUsageModel.provider,
                func.sum(TokenUsageModel.input_tokens),
                func.sum(TokenUsageModel.output_tokens),
                func.sum(TokenUsageModel.total_tokens),
                func.count(),
            )
            .where(TokenUsageModel.deleted_at.is_(None))
            .group_by(TokenUsageModel.model, TokenUsageModel.provider)
        )
    ).all()
    return [{"model": r[0], "provider": r[1], "inputTokens": r[2] or 0, "outputTokens": r[3] or 0, "totalTokens": r[4] or 0, "calls": r[5]} for r in rows]


class ProviderIn(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=120)
    base_url: str = ""
    status: str = "active"


class ModelIn(BaseModel):
    provider_id: str
    code: str = Field(min_length=1, max_length=160)
    name: str
    modality: str
    provider_model_id: str
    capabilities: dict = {}
    status: str = "active"
    user_visible: bool = True
    is_default: bool = False


@router.get("/providers")
async def providers(user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    rows = (await db.execute(select(AiProviderModel).where(AiProviderModel.deleted_at.is_(None)).order_by(AiProviderModel.name))).scalars()
    return [{"id": x.id, "code": x.code, "name": x.name, "baseUrl": x.base_url, "status": x.status} for x in rows]


@router.post("/providers", status_code=201)
async def create_provider(payload: ProviderIn, request: Request, user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    item = AiProviderModel(id=f"provider-{uuid.uuid4().hex}", code=payload.code, name=payload.name, base_url=payload.base_url, status=payload.status)
    db.add(item)
    await audit(db, request, user, "provider.create", "ai_provider", item.id, after=payload.model_dump())
    await db.commit()
    return {"id": item.id}


@router.get("/models")
async def models(user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    rows = (await db.execute(select(AiModelModel).where(AiModelModel.deleted_at.is_(None)).order_by(AiModelModel.modality, AiModelModel.sort_order))).scalars()
    return [
        {
            "id": x.id,
            "providerId": x.provider_id,
            "code": x.code,
            "name": x.name,
            "modality": x.modality,
            "providerModelId": x.provider_model_id,
            "capabilities": x.capabilities,
            "status": x.status,
            "userVisible": x.user_visible,
            "isDefault": x.is_default,
        }
        for x in rows
    ]


@router.post("/models", status_code=201)
async def create_model(payload: ModelIn, request: Request, user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    item = AiModelModel(id=f"model-{uuid.uuid4().hex}", **payload.model_dump())
    db.add(item)
    await audit(db, request, user, "model.create", "ai_model", item.id, after=payload.model_dump())
    await db.commit()
    return {"id": item.id}


@router.patch("/models/{model_id}")
async def update_model(model_id: str, payload: dict, request: Request, user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    item = await db.get(AiModelModel, model_id)
    if not item or item.deleted_at:
        raise HTTPException(404, "模型不存在")
    allowed = {"name", "status", "user_visible", "is_default", "capabilities", "sort_order"}
    before = {k: getattr(item, k) for k in allowed}
    for k, v in payload.items():
        if k in allowed:
            setattr(item, k, v)
    await audit(db, request, user, "model.update", "ai_model", item.id, before, payload)
    await db.commit()
    return {"ok": True}


@router.get("/audit-logs")
async def audits(
    user: CurrentUser,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Db,
):
    """操作审计列表：offset 分页，limit 上限 300，防止全量拉取拖垮数据库。"""
    require_admin(user)
    limit, offset = max(1, min(limit, 300)), max(0, offset)
    conditions = [AdminOperationLogModel.deleted_at.is_(None)]
    total = (await db.execute(select(func.count()).select_from(AdminOperationLogModel).where(*conditions))).scalar_one()
    rows = (await db.execute(select(AdminOperationLogModel).where(*conditions).order_by(AdminOperationLogModel.created_at.desc()).limit(limit).offset(offset))).scalars()
    return {
        "total": total,
        "items": [
            {
                "id": x.id,
                "adminUserId": x.admin_user_id,
                "action": x.action,
                "targetType": x.target_type,
                "targetId": x.target_id,
                "createdAt": iso(x.created_at),
            }
            for x in rows
        ],
    }


def _llm_call_summary(x: LlmCallLogModel) -> dict:
    return {
        "id": x.id,
        "operation": x.operation,
        "model": x.model,
        "status": x.status,
        "error": x.error,
        "durationMs": x.duration_ms,
        "inputTokens": x.input_tokens,
        "outputTokens": x.output_tokens,
        "cachedInputTokens": x.cached_input_tokens,
        "totalTokens": x.total_tokens,
        "requestId": x.request_id,
        "userId": x.user_id,
        "projectId": x.project_id,
        "projectTaskId": x.project_task_id,
        "storyboardLineId": x.storyboard_line_id,
        "generationJobId": x.generation_job_id,
        "promptKey": x.prompt_key,
        "promptVersion": x.prompt_version,
        "createdAt": iso(x.created_at),
    }


@router.get("/llm-calls")
async def llm_calls(
    user: CurrentUser,
    projectTaskId: str | None = None,
    storyboardLineId: str | None = None,
    operation: str | None = None,
    status: str | None = None,
    requestId: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Db,
):
    """分镜 LLM 调用留痕列表（不含请求/返回原文，详情走 /llm-calls/{id}）。"""
    require_admin(user)
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    conditions = [LlmCallLogModel.deleted_at.is_(None)]
    if projectTaskId:
        conditions.append(LlmCallLogModel.project_task_id == projectTaskId)
    if storyboardLineId:
        conditions.append(LlmCallLogModel.storyboard_line_id == storyboardLineId)
    if operation:
        conditions.append(LlmCallLogModel.operation == operation)
    if status:
        conditions.append(LlmCallLogModel.status == status)
    if requestId:
        conditions.append(LlmCallLogModel.request_id == requestId)
    total = (await db.execute(select(func.count()).select_from(LlmCallLogModel).where(*conditions))).scalar_one()
    rows = (await db.execute(select(LlmCallLogModel).where(*conditions).order_by(LlmCallLogModel.created_at.desc()).limit(limit).offset(offset))).scalars()
    return {"total": total, "items": [_llm_call_summary(x) for x in rows]}


@router.get("/llm-calls/{log_id}")
async def llm_call_detail(log_id: str, user: CurrentUser, db: AsyncSession = Db):
    """单条 LLM 调用的全量详情：含请求消息快照与返回原文。"""
    require_admin(user)
    item = await db.get(LlmCallLogModel, log_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(404, "调用记录不存在")
    return {**_llm_call_summary(item), "provider": item.provider, "requestMessages": item.request_messages or [], "responseText": item.response_text or ""}


def _request_log_summary(x: ApiRequestLogModel) -> dict:
    return {
        "id": x.id,
        "runId": x.run_id,
        "method": x.method,
        "path": x.path,
        "queryString": x.query_string,
        "statusCode": x.status_code,
        "durationMs": x.duration_ms,
        "userId": x.user_id,
        "clientIp": x.client_ip,
        "createdAt": iso(x.created_at),
    }


@router.get("/request-logs/runs")
async def request_log_runs(user: CurrentUser, db: AsyncSession = Db):
    """测试批次列表：每个批次对应一次全量测试，附耗时统计。"""
    require_admin(user)
    rows = (
        await db.execute(
            select(
                ApiRequestLogModel.run_id,
                func.count().label("requests"),
                func.avg(ApiRequestLogModel.duration_ms).label("avg_ms"),
                func.max(ApiRequestLogModel.duration_ms).label("max_ms"),
                func.min(ApiRequestLogModel.created_at).label("started_at"),
                func.max(ApiRequestLogModel.created_at).label("finished_at"),
                func.sum(case((ApiRequestLogModel.status_code >= 500, 1), else_=0)).label("errors"),
            )
            .where(ApiRequestLogModel.deleted_at.is_(None), ApiRequestLogModel.run_id != "")
            .group_by(ApiRequestLogModel.run_id)
            .order_by(func.max(ApiRequestLogModel.created_at).desc())
            .limit(50)
        )
    ).all()
    return [
        {
            "runId": row.run_id,
            "requests": row.requests,
            "avgMs": round(row.avg_ms or 0),
            "maxMs": row.max_ms or 0,
            "errors": row.errors or 0,
            "startedAt": iso(row.started_at),
            "finishedAt": iso(row.finished_at),
        }
        for row in rows
    ]


@router.get("/request-logs")
async def request_logs(
    user: CurrentUser,
    runId: str | None = None,
    path: str | None = None,
    method: str | None = None,
    status: int | None = None,
    minMs: int | None = None,
    orderBy: str = "created",
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Db,
):
    """API 请求耗时列表（不含输入输出原文，详情走 /request-logs/{id}）。

    minMs=仅返回耗时不低于该值的请求；orderBy=duration 时按耗时倒序（慢请求 TOP）。
    """
    require_admin(user)
    limit, offset = max(1, min(limit, 200)), max(0, offset)
    conditions = [ApiRequestLogModel.deleted_at.is_(None)]
    if runId:
        conditions.append(ApiRequestLogModel.run_id == runId)
    if path:
        conditions.append(ApiRequestLogModel.path.contains(path))
    if method:
        conditions.append(ApiRequestLogModel.method == method.upper())
    if status:
        conditions.append(ApiRequestLogModel.status_code == status)
    if minMs is not None:
        conditions.append(ApiRequestLogModel.duration_ms >= max(0, minMs))
    order_by_clause = (ApiRequestLogModel.duration_ms.desc(), ApiRequestLogModel.created_at.desc()) if orderBy == "duration" else (ApiRequestLogModel.created_at.desc(),)
    total = (await db.execute(select(func.count()).select_from(ApiRequestLogModel).where(*conditions))).scalar_one()
    rows = (await db.execute(select(ApiRequestLogModel).where(*conditions).order_by(*order_by_clause).limit(limit).offset(offset))).scalars()
    return {"total": total, "items": [_request_log_summary(x) for x in rows]}


@router.get("/request-logs/summary")
async def request_log_summary(
    user: CurrentUser,
    db: AsyncSession = Db,
    hours: int = 24,
    minCount: int = 3,
    limit: int = 50,
):
    """按 path+method 聚合正式流量（run_id 为空）的耗时分布：count/avg/p95/max。

    直接回答「哪个接口慢」：按 max 倒序取 TOP；p95 精确计算识别偶发慢请求
    与稳定慢接口。跨方言实现（p95 在 Python 计算，不依赖 PostgreSQL
    percentile_cont，测试库 SQLite 同样可用）。
    """
    require_admin(user)
    hours = max(1, min(hours, 168))
    limit = max(1, min(limit, 100))
    since = utcnow() - timedelta(hours=hours)
    # 取时间窗口内最近 2 万条正式流量的耗时明细（防止极端流量下内存膨胀），
    # 在 Python 中按 path+method 分桶计算 count/avg/p95/max
    rows = (
        await db.execute(
            select(
                ApiRequestLogModel.path,
                ApiRequestLogModel.method,
                ApiRequestLogModel.duration_ms,
            )
            .where(
                ApiRequestLogModel.deleted_at.is_(None),
                ApiRequestLogModel.created_at >= since,
                ApiRequestLogModel.run_id == "",
            )
            .order_by(ApiRequestLogModel.created_at.desc())
            .limit(20_000)
        )
    ).all()
    buckets: dict[tuple[str, str], list[int]] = {}
    for path, method, duration_ms in rows:
        buckets.setdefault((path, method), []).append(duration_ms)
    summary = []
    for (path, method), durations in buckets.items():
        if len(durations) < minCount:
            continue
        durations.sort()
        summary.append(
            {
                "path": path,
                "method": method,
                "count": len(durations),
                "avgMs": round(sum(durations) / len(durations)),
                "p95Ms": durations[int(len(durations) * 0.95) - 1],
                "maxMs": durations[-1],
            }
        )
    summary.sort(key=lambda row: row["maxMs"], reverse=True)
    return summary[:limit]


@router.get("/request-logs/{log_id}")
async def request_log_detail(log_id: str, user: CurrentUser, db: AsyncSession = Db):
    """单条请求的全量详情：含脱敏后的输入参数与输出原文。"""
    require_admin(user)
    item = await db.get(ApiRequestLogModel, log_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(404, "请求日志不存在")
    return {**_request_log_summary(item), "requestPayload": item.request_payload or {}, "responseBody": item.response_body or {}}


public_router = APIRouter(prefix="/api")


# ── 提示词注册中心（版本化 + 发布/回滚 + 试渲染） ─────────────────────────────


class PromptDraftIn(BaseModel):
    content: str = Field(min_length=1)
    change_note: str = ""


class PromptPublishIn(BaseModel):
    version_id: str


class PromptPreviewIn(BaseModel):
    content: str
    variables: dict[str, Any] = {}


def _prompt_version_summary(v: PromptVersionModel) -> dict:
    return {
        "id": v.id,
        "version": v.version,
        "status": v.status,
        "changeNote": v.change_note,
        "createdBy": v.created_by,
        "publishedAt": iso(v.published_at),
        "createdAt": iso(v.created_at),
    }


async def _get_prompt_template(db: AsyncSession, key: str) -> PromptTemplateModel:
    template = (await db.execute(select(PromptTemplateModel).where(PromptTemplateModel.key == key, PromptTemplateModel.deleted_at.is_(None)))).scalar_one_or_none()
    if not template:
        raise HTTPException(404, "提示词模板不存在")
    return template


def _validate_prompt_content(template: PromptTemplateModel, content: str) -> None:
    """发布前校验：安全片段必含、模板变量必须已声明、json 模板必须是字符串数组。"""
    missing = [fragment for fragment in (template.required_fragments or []) if fragment not in content]
    if missing:
        raise HTTPException(422, f"缺少必含安全片段：{missing}")
    undeclared = [name for name in template_variables(content) if name not in (template.variables or {})]
    if undeclared:
        raise HTTPException(422, f"模板变量未声明（代码不会为其传值）：{undeclared}")
    if (template.format or "text") == "json":
        try:
            parsed = json.loads(content)
        except ValueError as exc:
            raise HTTPException(422, f"JSON 模板解析失败：{exc}") from exc
        if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
            raise HTTPException(422, "JSON 模板必须是字符串数组")


@router.get("/prompts")
async def prompt_templates(user: CurrentUser, db: AsyncSession = Db):
    """提示词模板列表：含当前已发布版本摘要。"""
    require_admin(user)
    rows = (await db.execute(select(PromptTemplateModel).where(PromptTemplateModel.deleted_at.is_(None)).order_by(PromptTemplateModel.engine, PromptTemplateModel.key))).scalars()
    result = []
    for item in rows:
        current = await db.get(PromptVersionModel, item.current_version_id) if item.current_version_id else None
        result.append(
            {
                "id": item.id,
                "key": item.key,
                "name": item.name,
                "description": item.description,
                "engine": item.engine,
                "format": item.format,
                "variables": item.variables or {},
                "requiredFragments": item.required_fragments or [],
                "currentVersion": _prompt_version_summary(current) if current and current.deleted_at is None else None,
                "updatedAt": iso(item.updated_at),
            }
        )
    return result


@router.get("/prompts/{key}")
async def prompt_template_detail(key: str, user: CurrentUser, db: AsyncSession = Db):
    """模板详情：全部版本（新到旧）+ 内置默认内容（用于 diff 与一键恢复）。"""
    require_admin(user)
    template = await _get_prompt_template(db, key)
    versions = (
        await db.execute(
            select(PromptVersionModel).where(PromptVersionModel.template_id == template.id, PromptVersionModel.deleted_at.is_(None)).order_by(PromptVersionModel.version.desc())
        )
    ).scalars()
    default = DEFAULT_PROMPTS.get(key)
    return {
        "id": template.id,
        "key": template.key,
        "name": template.name,
        "description": template.description,
        "engine": template.engine,
        "format": template.format or "text",
        "variables": template.variables or {},
        "requiredFragments": template.required_fragments or [],
        "currentVersionId": template.current_version_id,
        "versions": [{**_prompt_version_summary(v), "content": v.content} for v in versions],
        "defaultContent": default["content"] if default else None,
    }


@router.post("/prompts/{key}/versions", status_code=201)
async def prompt_create_draft(key: str, payload: PromptDraftIn, request: Request, user: CurrentUser, db: AsyncSession = Db):
    """新建草稿版本（版本号递增）；内容校验在发布时才强制执行，草稿允许暂存不完整内容。"""
    require_admin(user)
    template = await _get_prompt_template(db, key)
    latest = (await db.execute(select(func.max(PromptVersionModel.version)).where(PromptVersionModel.template_id == template.id))).scalar_one()
    draft = PromptVersionModel(
        id=f"pv-{uuid.uuid4().hex}",
        template_id=template.id,
        version=int(latest or 0) + 1,
        content=payload.content,
        change_note=payload.change_note,
        status="draft",
        created_by=getattr(user, "username", "") or user.id,
    )
    db.add(draft)
    await audit(db, request, user, "prompt.draft", "prompt_template", template.id, after={"key": key, "version": draft.version, "changeNote": payload.change_note})
    await db.commit()
    return {"id": draft.id, "version": draft.version}


@router.post("/prompts/{key}/publish")
async def prompt_publish(key: str, payload: PromptPublishIn, request: Request, user: CurrentUser, db: AsyncSession = Db):
    """发布指定版本；回滚 = 选择旧版本发布。发布前强制校验，发布后注册中心缓存立即失效。"""
    require_admin(user)
    template = await _get_prompt_template(db, key)
    version = await db.get(PromptVersionModel, payload.version_id)
    if not version or version.template_id != template.id or version.deleted_at is not None:
        raise HTTPException(404, "提示词版本不存在")
    _validate_prompt_content(template, version.content)
    before = {"currentVersionId": template.current_version_id}
    current = await db.get(PromptVersionModel, template.current_version_id) if template.current_version_id else None
    if current and current.status == "published":
        current.status = "archived"
    version.status = "published"
    version.published_at = utcnow()
    template.current_version_id = version.id
    await audit(db, request, user, "prompt.publish", "prompt_template", template.id, before, {"currentVersionId": version.id, "version": version.version})
    await db.commit()
    invalidate(key)
    return {"ok": True, "version": version.version}


@router.post("/prompts/{key}/preview")
async def prompt_preview(key: str, payload: PromptPreviewIn, user: CurrentUser, db: AsyncSession = Db):
    """试渲染：只替换已提供的变量，返回渲染结果与校验报告，不调用任何模型。"""
    require_admin(user)
    template = await _get_prompt_template(db, key)
    used = template_variables(payload.content)
    rendered = render_lenient(payload.content, payload.variables)
    json_error = ""
    if (template.format or "text") == "json":
        try:
            parsed = json.loads(rendered)
            if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
                json_error = "JSON 模板必须是字符串数组"
        except ValueError as exc:
            json_error = str(exc)
    return {
        "rendered": rendered,
        "usedVariables": used,
        "missingVariables": [name for name in used if name not in payload.variables],
        "undeclaredVariables": [name for name in used if name not in (template.variables or {})],
        "missingFragments": [fragment for fragment in (template.required_fragments or []) if fragment not in payload.content],
        "jsonError": json_error,
    }


@router.delete("/prompts/{key}/versions/{version_id}")
async def prompt_delete_draft(key: str, version_id: str, request: Request, user: CurrentUser, db: AsyncSession = Db):
    """软删除草稿版本；published/archived 版本保留历史不可删除。"""
    require_admin(user)
    template = await _get_prompt_template(db, key)
    version = await db.get(PromptVersionModel, version_id)
    if not version or version.template_id != template.id or version.deleted_at is not None:
        raise HTTPException(404, "提示词版本不存在")
    if version.status != "draft":
        raise HTTPException(409, "仅草稿版本可删除")
    version.deleted_at = utcnow()
    await audit(db, request, user, "prompt.discard", "prompt_template", template.id, {"version": version.version})
    await db.commit()
    return {"ok": True}


@public_router.get("/model-options")
async def model_options(user: CurrentUser, modality: str | None = None, db: AsyncSession = Db):
    query = select(AiModelModel).where(AiModelModel.deleted_at.is_(None), AiModelModel.status == "active", AiModelModel.user_visible.is_(True))
    if modality:
        query = query.where(AiModelModel.modality == modality)
    rows = (await db.execute(query.order_by(AiModelModel.modality, AiModelModel.sort_order))).scalars()
    return [{"id": x.code, "name": x.name, "modality": x.modality, "capabilities": x.capabilities, "isDefault": x.is_default} for x in rows]


@public_router.get("/aigc/models")
async def aigc_provider_models(user: CurrentUser):
    """工具：实时查询上游 AIGC 平台当前账号可见的模型列表（/v1/models）。

    用途：核对环境变量（VIDEO_API_KEY/AIGC_TOKEN）指向的账号在平台侧实际开放了哪些
    模型，排查“模型名不存在/不可用”类问题；key 与生成链路同一来源，不做缓存。
    """
    try:
        models = await list_video_models()
    except ProviderError as exc:
        raise HTTPException(502, f"上游模型列表查询失败：{exc}") from exc
    return {
        "provider": "yinghe",
        "baseUrl": settings.video_api_base_url,
        "apiKeySuffix": settings.video_api_key[-6:],
        "count": len(models),
        "models": models,
    }
