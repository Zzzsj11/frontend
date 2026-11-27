from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import RequestResponseEndpoint

_origin: ContextVar[str] = ContextVar("generation_origin", default="business")
_agent_name: ContextVar[str] = ContextVar("agent_name", default="")
_agent_run_id: ContextVar[str] = ContextVar("agent_run_id", default="")


_test_run: ContextVar[str] = ContextVar("test_run_id", default="")


def current_test_run_id() -> str:
    return _test_run.get()


def current_agent_attribution() -> tuple[str, str, str]:
    return _origin.get(), _agent_name.get(), _agent_run_id.get()


async def agent_attribution_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    explicit_run_id = request.headers.get("x-agent-run-id", "").strip()[:160]
    test_run_id = request.headers.get("x-test-run-id", "").strip()[:160]
    run_id = explicit_run_id or test_run_id
    agent_name = request.headers.get("x-agent-name", "").strip()[:80]
    marked = any(key in request.headers for key in ("x-agent-name", "x-agent-run-id", "x-test-run-id"))
    request.state.agent_headers_incomplete = marked and not (agent_name == "code-agent" and explicit_run_id and test_run_id)
    origin_token = _origin.set("agent_test" if marked else "business")
    name_token = _agent_name.set(agent_name or ("code-agent" if marked else ""))
    test_token = _test_run.set(test_run_id)
    run_token = _agent_run_id.set(run_id)
    try:
        return await call_next(request)
    finally:
        _origin.reset(origin_token)
        _agent_name.reset(name_token)
        _agent_run_id.reset(run_token)
        _test_run.reset(test_token)


async def require_generation_attribution(request: Request) -> None:
    if request.state.agent_headers_incomplete:
        raise HTTPException(422, "Agent 生成请求必须携带 X-Agent-Name: code-agent、X-Agent-Run-Id 和 X-Test-Run-Id")


@contextmanager
def attribution_context(origin: str, name: str, run_id: str, test_run_id: str = ""):
    test_token = _test_run.set(test_run_id)
    tokens = (_origin.set(origin), _agent_name.set(name), _agent_run_id.set(run_id))
    try:
        yield
    finally:
        _origin.reset(tokens[0])
        _agent_name.reset(tokens[1])
        _agent_run_id.reset(tokens[2])
        _test_run.reset(test_token)
