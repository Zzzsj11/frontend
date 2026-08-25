from __future__ import annotations

from contextvars import ContextVar

from fastapi import Request, Response
from starlette.middleware.base import RequestResponseEndpoint

_origin: ContextVar[str] = ContextVar("generation_origin", default="business")
_agent_name: ContextVar[str] = ContextVar("agent_name", default="")
_agent_run_id: ContextVar[str] = ContextVar("agent_run_id", default="")


def current_agent_attribution() -> tuple[str, str, str]:
    return _origin.get(), _agent_name.get(), _agent_run_id.get()


async def agent_attribution_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    explicit_run_id = request.headers.get("x-agent-run-id", "").strip()[:160]
    test_run_id = request.headers.get("x-test-run-id", "").strip()[:160]
    run_id = explicit_run_id or test_run_id
    agent_name = request.headers.get("x-agent-name", "").strip()[:80]
    if run_id and not agent_name:
        agent_name = "code-agent"
    origin_token = _origin.set("agent_test" if run_id else "business")
    name_token = _agent_name.set(agent_name if run_id else "")
    run_token = _agent_run_id.set(run_id)
    try:
        return await call_next(request)
    finally:
        _origin.reset(origin_token)
        _agent_name.reset(name_token)
        _agent_run_id.reset(run_token)
