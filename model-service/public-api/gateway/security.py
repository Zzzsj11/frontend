import hashlib
import re

from fastapi import HTTPException, Request
from sqlalchemy import select

from .db import Client, Session


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def identifier(value: str, field: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:@-]{1,160}", value):
        raise HTTPException(400, f"{field} must be a stable identifier")
    return value


async def authenticate(request: Request) -> Client:
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(401, "API key required")
    async with Session() as db:
        client = await db.scalar(
            select(Client).where(Client.key_hash == digest(auth[7:]), Client.enabled.is_(True), Client.deleted_at.is_(None))
        )
    if not client:
        raise HTTPException(401, "Invalid API key")
    if client.user_id:
        from .db import User

        async with Session() as db:
            user = await db.get(User, client.user_id)
        if not user or not user.enabled or user.deleted_at:
            raise HTTPException(401, "User disabled")
        if user.password_changed_at is None:
            raise HTTPException(403, "首次登录请先修改密码")
        supplied = request.headers.get("x-user-id")
        if supplied and supplied != client.user_id:
            raise HTTPException(403, "Bound API Key cannot override its user")
        request.state.bound_user_id = client.user_id
    return client


def attribution(request: Request, client: Client):
    agent = request.headers.get("x-agent-name", "")
    run = request.headers.get("x-agent-run-id", "")
    test = request.headers.get("x-test-run-id", "")
    if client.require_agent or agent or run or test:
        if agent != "code-agent" or not run or not test:
            raise HTTPException(400, "Agent calls require X-Agent-Name: code-agent, X-Agent-Run-Id and X-Test-Run-Id")
        identifier(run, "X-Agent-Run-Id")
        identifier(test, "X-Test-Run-Id")
    return dict(origin="agent_test" if run else "business", agent_name=agent, agent_run_id=run, test_run_id=test)


def owner(request: Request):
    return getattr(request.state, "bound_user_id", None) or identifier(request.headers.get("x-user-id", ""), "X-User-Id")
