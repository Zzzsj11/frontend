from __future__ import annotations

import json
import time
import uuid
from typing import Any

from fastapi import Request
from starlette.datastructures import Headers

from .config import settings
from .database import session_factory
from .error_logging import _redact, redacted_query
from .models import ApiRequestLogModel

# 请求/响应体超过该阈值只记录元信息，避免大对象写库
MAX_BODY_BYTES = 8192


def _decode_payload(raw: bytes) -> dict[str, Any]:
    if not raw:
        return {}
    if len(raw) > MAX_BODY_BYTES:
        return {"truncated": True, "size": len(raw)}
    try:
        return _redact(json.loads(raw))
    except Exception:
        return {"unreadable": True, "size": len(raw)}


class RequestLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope)
        run_id = request.headers.get("x-test-run-id", "")[:120]
        if request.headers.get("x-polling") == "1" or not request.url.path.startswith("/api/") or (not run_id and not settings.api_request_log_all):
            return await self.app(scope, receive, send)
        start = time.perf_counter()
        incoming, outgoing = bytearray(), bytearray()
        request_type = request.headers.get("content-type", "")
        response_type, status = "", 500
        request_size = response_size = 0

        async def observed_receive():
            nonlocal request_size
            message = await receive()
            chunk = message.get("body", b"")
            request_size += len(chunk)
            if "application/json" in request_type and request_size <= MAX_BODY_BYTES:
                incoming.extend(chunk)
            return message

        async def observed_send(message):
            nonlocal response_type, response_size, status
            if message["type"] == "http.response.start":
                status = message["status"]
                response_type = Headers(raw=message["headers"]).get("content-type", "")
            elif message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                response_size += len(chunk)
                if "application/json" in response_type and response_size <= MAX_BODY_BYTES:
                    outgoing.extend(chunk)
            await send(message)

        await self.app(scope, observed_receive, observed_send)

        def summary(content_type, size, data):
            if "application/json" not in content_type:
                return {"contentType": content_type} if content_type else {}
            if size > MAX_BODY_BYTES:
                return {"truncated": True, "size": size}
            return _decode_payload(bytes(data))

        try:
            async with session_factory() as db:
                db.add(
                    ApiRequestLogModel(
                        id=f"apilog-{uuid.uuid4().hex}",
                        run_id=run_id,
                        user_id=getattr(request.state, "user_id", None),
                        method=request.method,
                        path=request.url.path,
                        query_string=redacted_query(request),
                        status_code=status,
                        duration_ms=int((time.perf_counter() - start) * 1000),
                        request_payload=summary(request_type, request_size, incoming),
                        response_body=summary(response_type, response_size, outgoing),
                        client_ip=request.client.host if request.client else None,
                    )
                )
                await db.commit()
        except Exception:
            pass
