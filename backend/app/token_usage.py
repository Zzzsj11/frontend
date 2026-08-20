from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from .models import LlmCallLogModel, TokenUsageModel


def normalize_usage(value: Any) -> dict[str, Any]:
    if value is None:
        raw: dict[str, Any] = {}
    elif isinstance(value, dict):
        raw = value
    elif hasattr(value, "model_dump"):
        raw = value.model_dump(mode="json")
    else:
        raw = {key: getattr(value, key) for key in dir(value) if not key.startswith("_") and isinstance(getattr(value, key, None), (str, int, float, bool, type(None)))}
    metrics = raw.get("rawUsage") if isinstance(raw.get("rawUsage"), dict) else raw
    input_tokens = int(metrics.get("input_tokens") or metrics.get("inputTokens") or metrics.get("prompt_tokens") or metrics.get("promptTokens") or 0)
    output_tokens = int(metrics.get("output_tokens") or metrics.get("outputTokens") or metrics.get("completion_tokens") or metrics.get("completionTokens") or 0)
    details = metrics.get("prompt_tokens_details") or metrics.get("input_tokens_details") or {}
    cached = int(details.get("cached_tokens") or details.get("cache_read_input_tokens") or metrics.get("cached_input_tokens") or metrics.get("cached_tokens") or 0)
    total = int(metrics.get("total_tokens") or metrics.get("totalTokens") or input_tokens + output_tokens)
    return {"inputTokens": input_tokens, "outputTokens": output_tokens, "cachedInputTokens": cached, "totalTokens": total, "raw": raw}


def add_token_usage(
    db: AsyncSession,
    *,
    operation: str,
    provider: str,
    model: str,
    usage: Any,
    user_id: str | None = None,
    project_id: str | None = None,
    project_task_id: str | None = None,
    storyboard_line_id: str | None = None,
    generation_job_id: str | None = None,
    chat_session_id: str | None = None,
    request_id: str | None = None,
) -> tuple[TokenUsageModel, dict[str, Any]]:
    normalized = normalize_usage(usage)
    item = TokenUsageModel(
        id=f"usage-{uuid.uuid4().hex}",
        user_id=user_id,
        project_id=project_id,
        project_task_id=project_task_id,
        storyboard_line_id=storyboard_line_id,
        generation_job_id=generation_job_id,
        chat_session_id=chat_session_id,
        operation=operation,
        provider=provider,
        model=model,
        request_id=request_id,
        input_tokens=normalized["inputTokens"],
        output_tokens=normalized["outputTokens"],
        cached_input_tokens=normalized["cachedInputTokens"],
        total_tokens=normalized["totalTokens"],
        raw_usage=normalized["raw"],
    )
    db.add(item)
    return item, {key: normalized[key] for key in ("inputTokens", "outputTokens", "cachedInputTokens", "totalTokens")}


def add_llm_call_log(
    db: AsyncSession,
    *,
    operation: str,
    provider: str,
    model: str,
    usage: Any,
    user_id: str | None = None,
    project_id: str | None = None,
    project_task_id: str | None = None,
    storyboard_line_id: str | None = None,
    generation_job_id: str | None = None,
    request_id: str | None = None,
    status: str = "ok",
    error: str = "",
    duration_ms: int = 0,
    request_messages: list[dict[str, Any]] | None = None,
    response_text: str = "",
    prompt_key: str = "",
    prompt_version: int = 0,
) -> LlmCallLogModel:
    """落一条分镜 LLM 调用的全量留痕：请求消息快照、返回原文、耗时与 token 用量。"""
    normalized = normalize_usage(usage)
    item = LlmCallLogModel(
        id=f"llm-{uuid.uuid4().hex}",
        user_id=user_id,
        project_id=project_id,
        project_task_id=project_task_id,
        storyboard_line_id=storyboard_line_id,
        generation_job_id=generation_job_id,
        operation=operation,
        provider=provider,
        model=model,
        request_id=request_id,
        status=status,
        error=error,
        duration_ms=duration_ms,
        input_tokens=normalized["inputTokens"],
        output_tokens=normalized["outputTokens"],
        cached_input_tokens=normalized["cachedInputTokens"],
        total_tokens=normalized["totalTokens"],
        request_messages=request_messages or [],
        response_text=response_text,
        prompt_key=prompt_key,
        prompt_version=prompt_version,
    )
    db.add(item)
    return item
