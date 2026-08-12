from __future__ import annotations

import json
import traceback as traceback_module
import uuid
from typing import Any

from fastapi import Request

from .database import session_factory
from .models import ApiErrorLogModel

SENSITIVE_KEYS = {"password", "current_password", "new_password", "access_token", "refresh_token", "token", "authorization", "cookie"}
# 键名比较前去掉下划线并小写，使 accessToken / access_token 等写法都能命中
_SENSITIVE_NORMALIZED = {key.replace("_", "") for key in SENSITIVE_KEYS}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: ("***" if key.lower().replace("_", "") in _SENSITIVE_NORMALIZED else _redact(item)) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value[:50]]
    if isinstance(value, str) and len(value) > 2000:
        return value[:2000] + "…"
    return value


async def request_payload(request: Request) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" not in content_type:
        return {"contentType": content_type} if content_type else {}
    try:
        raw = await request.body()
        return _redact(json.loads(raw)) if raw else {}
    except Exception:
        return {"unreadable": True}


async def record_api_error(request: Request, *, status_code: int, error_type: str, message: str, exc: Exception | None = None, payload: dict[str, Any] | None = None) -> str:
    error_code = f"ERR-{uuid.uuid4().hex[:12].upper()}"
    trace = "" if exc is None else "".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__))[-12000:]
    try:
        async with session_factory() as db:
            db.add(
                ApiErrorLogModel(
                    id=f"apierr-{uuid.uuid4().hex}",
                    error_code=error_code,
                    user_id=getattr(request.state, "user_id", None),
                    method=request.method,
                    path=request.url.path,
                    query_string=request.url.query[:4000],
                    status_code=status_code,
                    error_type=error_type[:160],
                    message=message[:4000],
                    request_payload=payload if payload is not None else await request_payload(request),
                    traceback=trace,
                    client_ip=request.client.host if request.client else None,
                    user_agent=(request.headers.get("user-agent") or "")[:512] or None,
                )
            )
            await db.commit()
    except Exception:
        pass
    return error_code


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
                    message=message[:4000],
                    request_payload={"projectId": project_id, "projectTaskId": project_task_id},
                    traceback=traceback_text[:12000],
                    client_ip=None,
                    user_agent=None,
                )
            )
            await db.commit()
    except Exception:
        pass
    return error_code
