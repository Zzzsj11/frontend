from __future__ import annotations

import json
import logging
import re
import time
import traceback as traceback_module
import uuid
from datetime import timedelta
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from sqlalchemy import select, update
from starlette.background import BackgroundTask

from .database import session_factory
from .models import ApiErrorLogModel, utcnow

logger = logging.getLogger(__name__)

SENSITIVE_KEYS = {
    "password",
    "current_password",
    "new_password",
    "access_token",
    "refresh_token",
    "token",
    "authorization",
    "cookie",
    "api_key",
    "secret",
    "signature",
    "x-tos-signature",
}
# 键名比较前去掉下划线并小写，使 accessToken / access_token 等写法都能命中
_SENSITIVE_NORMALIZED = {key.replace("_", "") for key in SENSITIVE_KEYS}
_SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(sk[_-])[A-Za-z0-9_-]{12,}"),
    re.compile(r"\b(ms_|yh-)[A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)([?&](?:signature|x-tos-signature|token|access_token|api_key)=)[^&\s]+"),
)


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(r"\1***", redacted)
    return redacted[:2000] + "…" if len(redacted) > 2000 else redacted


def redact_error_text(value: str) -> str:
    """Public boundary for user-visible/persisted background-job errors."""
    return _redact_text(value)


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if key.lower().replace("_", "") in _SENSITIVE_NORMALIZED else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value[:50]]
    if isinstance(value, str):
        return _redact_text(value)
    return value


def redacted_query(request: Request) -> str:
    return urlencode([(k, "***" if k.lower().replace("_", "") in _SENSITIVE_NORMALIZED else _redact_text(v)) for k, v in request.query_params.multi_items()])[:4000]


# Bound incidental client-error writes independently of request cardinality. Repeated
# errors return the first event's tracking code for the rest of the window.
_client_errors: dict[tuple, str] = {}
_window_start = 0.0
_pending_writes = 0
_last_retention = 0.0
_suppressed_errors = 0


def _sample_client_error(request, status, code):
    global _window_start, _suppressed_errors
    now = time.monotonic()
    if now - _window_start >= 60:
        _window_start = now
        if _suppressed_errors:
            logger.info("客户端错误日志合并或限流 %d 条", _suppressed_errors)
        _suppressed_errors = 0
        _client_errors.clear()
    route = getattr(request.scope.get("route"), "path", "<unmatched>")
    key = (request.method, route, status, getattr(request.state, "user_id", None))
    if key in _client_errors:
        _suppressed_errors += 1
        return _client_errors[key]
    if len(_client_errors) >= 256 or _pending_writes >= 32:
        _suppressed_errors += 1
        return "ERR-RATE-LIMITED"
    _client_errors[key] = code
    return None


async def request_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return {"contentType": content_type} if content_type else {}
    try:
        if int(request.headers.get("content-length") or 8193) > 8192:
            return {"truncated": True}
        raw = getattr(request, "_body", b"")
        return _redact(json.loads(raw)) if raw else {}
    except Exception:
        return {"unreadable": True}


async def record_api_error(request: Request, *, status_code: int, error_type: str, message: str, exc: Exception | None = None, payload: dict[str, Any] | None = None) -> str:
    error_code = f"ERR-{uuid.uuid4().hex[:12].upper()}"
    if 400 <= status_code < 500:
        prior = _sample_client_error(request, status_code, error_code)
        if prior is not None:
            return prior
    trace = "" if exc is None else _redact_text("".join(traceback_module.format_list(traceback_module.extract_tb(exc.__traceback__))))
    row = ApiErrorLogModel(
        id=f"apierr-{uuid.uuid4().hex}",
        error_code=error_code,
        user_id=getattr(request.state, "user_id", None),
        method=request.method,
        path=request.url.path,
        query_string=redacted_query(request),
        status_code=status_code,
        error_type=error_type[:160],
        message=_redact_text(message),
        request_payload=payload if payload is not None else await request_payload(request),
        traceback=trace,
        client_ip=request.client.host if request.client else None,
        user_agent=(request.headers.get("user-agent") or "")[:512] or None,
    )

    async def write():
        global _pending_writes
        start = time.monotonic()
        try:
            async with session_factory() as db:
                db.add(row)
                await db.commit()
        except Exception:
            logger.warning("写入 API 错误日志失败", exc_info=True)
        finally:
            _pending_writes -= 1
            elapsed = time.monotonic() - start
            if elapsed > 1:
                logger.warning("写入 API 错误日志耗时 %.2fs", elapsed)

    global _pending_writes
    _pending_writes += 1
    if 400 <= status_code < 500:
        request.state.client_error_write = BackgroundTask(write)
    else:
        await write()
    return error_code


async def expire_client_errors() -> None:
    """Expire sampled client errors after 30 days, in small batches."""
    global _last_retention
    if time.monotonic() - _last_retention < 300:
        return
    _last_retention = time.monotonic()
    now = utcnow()
    async with session_factory() as db:
        old = (
            select(ApiErrorLogModel.id)
            .where(ApiErrorLogModel.deleted_at.is_(None), ApiErrorLogModel.status_code.between(400, 499), ApiErrorLogModel.created_at < now - timedelta(days=30))
            .limit(1000)
        )
        await db.execute(
            update(ApiErrorLogModel)
            .where(ApiErrorLogModel.id.in_(old))
            .values(deleted_at=now, request_payload={}, traceback="", query_string="")
            .execution_options(synchronize_session=False)
        )
        await db.commit()


async def log_background_error(
    *,
    user_id: str | None = None,
    path: str = "",
    status_code: int = 500,
    error_type: str = "LLMError",
    message: str,
    traceback_text: str = "",
    project_id: str | None = None,
    project_task_id: str | None = None,
) -> str:
    """记录后台任务/非 HTTP 路径的 LLM 调用错误，供复盘使用。"""
    error_code = f"ERR-{uuid.uuid4().hex[:12].upper()}"
    try:
        async with session_factory() as db:
            db.add(
                ApiErrorLogModel(
                    id=f"apierr-{uuid.uuid4().hex}",
                    error_code=error_code,
                    user_id=user_id,
                    method="POST",
                    path=path[:4000],
                    query_string="",
                    status_code=status_code,
                    error_type=error_type[:160],
                    message=_redact_text(message),
                    request_payload={"projectId": project_id, "projectTaskId": project_task_id},
                    traceback=_redact_text(traceback_text),
                    client_ip=None,
                    user_agent=None,
                )
            )
            await db.commit()
    except Exception:
        pass
    return error_code
