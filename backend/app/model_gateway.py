"""Opt-in independent model service routing; direct mode remains the default."""

from __future__ import annotations

import os
import uuid
from contextvars import ContextVar
from typing import Any

import httpx
from openai import AsyncOpenAI as OpenAIClient

from .agent_attribution import current_agent_attribution

# 网关已承接的渠道（对齐 model-service channels 白名单）；未列出渠道保持直连，按渠道灰度迁移。
MIGRATED_CHANNELS = frozenset({"yinghe", "yseeai", "toapis", "runninghub", "optimizer-gemini", "optimizer-minimax"})

_legacy: ContextVar[bool] = ContextVar("model_gateway_legacy", default=False)
_owner: ContextVar[str] = ContextVar("model_gateway_owner", default="")
_agent: ContextVar[tuple[str, str] | None] = ContextVar("model_gateway_agent", default=None)
_job: ContextVar[str] = ContextVar("model_gateway_job", default="")


def enabled() -> bool:
    return bool(os.getenv("MODEL_GATEWAY_URL", "").strip()) and not _legacy.get()


def routed(channel: str) -> bool:
    return enabled() and channel in MIGRATED_CHANNELS


def base_url() -> str:
    return os.environ["MODEL_GATEWAY_URL"].rstrip("/")


def set_owner(user_id: str) -> None:
    _owner.set(user_id)


def request_headers() -> dict[str, str]:
    key = os.getenv("MODEL_GATEWAY_API_KEY", "")
    user_id = _owner.get()
    if not key or not user_id:
        raise RuntimeError("模型网关缺少内部 API Key 或用户归因，已阻止调用")
    job_id = _job.get()
    # 工单上下文内派生稳定键，崩溃重放由网关按 (client, user, key) 去重；无工单上下文（查询、测试面板）用随机键。
    idem = f"mv-{job_id}" if job_id else "mv-" + uuid.uuid4().hex
    result = {"Authorization": f"Bearer {key}", "X-User-Id": user_id, "Idempotency-Key": idem}
    _origin, name, run = current_agent_attribution()
    if _agent.get() is not None:
        name, run = _agent.get() or ("", "")
    if run:
        result.update({"X-Agent-Name": name or "code-agent", "X-Agent-Run-Id": run, "X-Test-Run-Id": run})
    return result


def route(channel: str) -> tuple[str, dict[str, str]]:
    return base_url() + "/providers/" + channel, request_headers()


async def run_with_context(job: Any, runner: Any) -> Any:
    snapshot = getattr(job, "request", None) or {}
    if not enabled():
        if snapshot.get("_modelGateway") and job.provider_task_id:
            raise RuntimeError("该工单属于模型网关；恢复前须保留 MODEL_GATEWAY_URL 配置")
        return await runner(job)
    from .database import session_factory
    from .models import GenerationJobModel

    async with session_factory() as db:
        row = await db.get(GenerationJobModel, job.id)
        attrs = (row.agent_name or "", row.agent_run_id or "") if row else ("", "")
        if job.kind in {"image", "video"} and not job.provider_task_id:
            job.request = {**snapshot, "_modelGateway": True}
            if row:
                row.request = dict(job.request)
                await db.commit()
            snapshot = job.request
    legacy_token = _legacy.set(bool(job.kind in {"image", "video"} and job.provider_task_id and not snapshot.get("_modelGateway")))
    owner_token = _owner.set(job.user_id or "")
    agent_token = _agent.set(attrs)
    job_token = _job.set(str(job.id or ""))
    try:
        return await runner(job)
    finally:
        _legacy.reset(legacy_token)
        _owner.reset(owner_token)
        _agent.reset(agent_token)
        _job.reset(job_token)


class AsyncOpenAI(OpenAIClient):
    """Route every OpenAI-compatible MV call through the service when opted in."""

    def __init__(self, **kwargs: Any):
        if enabled():

            async def enrich(request: httpx.Request) -> None:
                request.headers.update(request_headers())
                request.headers["Idempotency-Key"] = "llm-" + uuid.uuid4().hex

            kwargs.update(
                base_url=base_url() + "/v1",
                api_key=os.environ.get("MODEL_GATEWAY_API_KEY", ""),
                max_retries=0,
                http_client=httpx.AsyncClient(timeout=kwargs.get("timeout", 300), event_hooks={"request": [enrich]}),
            )
        super().__init__(**kwargs)
