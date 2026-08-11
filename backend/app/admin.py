from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import CurrentUser
from .database import database_session
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
    TokenUsageModel,
    UserModel,
)

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
async def projects(user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    rows = (
        await db.execute(
            select(ProjectModel, UserModel.username)
            .join(UserModel, UserModel.id == ProjectModel.user_id)
            .where(ProjectModel.deleted_at.is_(None))
            .order_by(ProjectModel.created_at.desc())
            .limit(300)
        )
    ).all()
    return [{"id": p.id, "name": p.name, "username": u, "status": p.status, "createdAt": iso(p.created_at)} for p, u in rows]


@router.get("/jobs")
async def jobs(user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    rows = (await db.execute(select(GenerationJobModel).where(GenerationJobModel.deleted_at.is_(None)).order_by(GenerationJobModel.created_at.desc()).limit(300))).scalars()
    return [{"id": j.id, "userId": j.user_id, "kind": j.kind, "status": j.status, "provider": j.provider, "error": j.error, "createdAt": iso(j.created_at)} for j in rows]


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
async def audits(user: CurrentUser, db: AsyncSession = Db):
    require_admin(user)
    rows = (
        await db.execute(select(AdminOperationLogModel).where(AdminOperationLogModel.deleted_at.is_(None)).order_by(AdminOperationLogModel.created_at.desc()).limit(300))
    ).scalars()
    return [{"id": x.id, "adminUserId": x.admin_user_id, "action": x.action, "targetType": x.target_type, "targetId": x.target_id, "createdAt": iso(x.created_at)} for x in rows]


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
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Db,
):
    """API 请求耗时列表（不含输入输出原文，详情走 /request-logs/{id}）。"""
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
    total = (await db.execute(select(func.count()).select_from(ApiRequestLogModel).where(*conditions))).scalar_one()
    rows = (await db.execute(select(ApiRequestLogModel).where(*conditions).order_by(ApiRequestLogModel.created_at.desc()).limit(limit).offset(offset))).scalars()
    return {"total": total, "items": [_request_log_summary(x) for x in rows]}


@router.get("/request-logs/{log_id}")
async def request_log_detail(log_id: str, user: CurrentUser, db: AsyncSession = Db):
    """单条请求的全量详情：含脱敏后的输入参数与输出原文。"""
    require_admin(user)
    item = await db.get(ApiRequestLogModel, log_id)
    if not item or item.deleted_at is not None:
        raise HTTPException(404, "请求日志不存在")
    return {**_request_log_summary(item), "requestPayload": item.request_payload or {}, "responseBody": item.response_body or {}}


public_router = APIRouter(prefix="/api")


@public_router.get("/model-options")
async def model_options(user: CurrentUser, modality: str | None = None, db: AsyncSession = Db):
    query = select(AiModelModel).where(AiModelModel.deleted_at.is_(None), AiModelModel.status == "active", AiModelModel.user_visible.is_(True))
    if modality:
        query = query.where(AiModelModel.modality == modality)
    rows = (await db.execute(query.order_by(AiModelModel.modality, AiModelModel.sort_order))).scalars()
    return [{"id": x.code, "name": x.name, "modality": x.modality, "capabilities": x.capabilities, "isDefault": x.is_default} for x in rows]
