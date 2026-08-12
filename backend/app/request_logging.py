from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint
from starlette.types import Message

from .config import settings
from .database import session_factory
from .error_logging import _redact
from .models import ApiRequestLogModel

# 请求/响应体超过该阈值只记录元信息，避免大对象写库
MAX_BODY_BYTES = 8192


def _replay_request(request: Request, body: bytes) -> Request:
    """BaseHTTPMiddleware 中读完 body 后必须重放 receive channel，否则下游读取为空。"""

    async def receive() -> Message:
        return {"type": "http.request", "body": body, "more_body": False}

    return Request(request.scope, receive)


def _decode_payload(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    if len(raw) > MAX_BODY_BYTES:
        return {"truncated": True, "size": len(raw)}
    try:
        return _redact(json.loads(raw))
    except Exception:
        return {"unreadable": True, "size": len(raw)}


async def api_request_log_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    run_id = request.headers.get("x-test-run-id", "")
    # 轮询/长连接（前端打 X-Polling: 1）：每 2-5 秒刷一次或挂几分钟，
    # 全量记录会产生海量重复数据并污染慢请求统计（SSE 的 duration_ms 等于连接时长）
    if request.headers.get("x-polling") == "1":
        return await call_next(request)
    if not request.url.path.startswith("/api/") or (not run_id and not settings.api_request_log_all):
        return await call_next(request)
    body = await request.body()
    request = _replay_request(request, body)
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = int((time.perf_counter() - start) * 1000)
    content_type = response.headers.get("content-type", "")
    if "application/json" in content_type:
        raw = b"".join([chunk async for chunk in response.body_iterator])
        response_body = _decode_payload(raw)
        logged_response = Response(
            content=raw,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
            background=response.background,
        )
    else:
        # SSE/流式/二进制不缓冲，避免破坏实时传输；只记录响应元信息
        response_body = {"contentType": content_type} if content_type else {}
        logged_response = response
    try:
        async with session_factory() as db:
            db.add(
                ApiRequestLogModel(
                    id=f"apilog-{uuid.uuid4().hex}",
                    run_id=run_id,
                    user_id=getattr(request.state, "user_id", None),
                    method=request.method,
                    path=request.url.path,
                    query_string=request.url.query[:4000],
                    status_code=response.status_code,
                    duration_ms=duration_ms,
                    request_payload=_decode_payload(body),
                    response_body=response_body,
                    client_ip=request.client.host if request.client else None,
                )
            )
            await db.commit()
    except Exception:
        pass
    return logged_response
