"""Exercise credential rotation and open SSE requests on one disposable PostgreSQL database."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import patch
from urllib.parse import quote, urlsplit
from uuid import uuid4

import asyncpg
import httpx
import local_runtime

ROLE = "mv-local@proof"
SECRET = "synthetic-reserved:%@/?#"
ORIGINAL = "synthetic-previous-password"
REPLACEMENT = "synthetic-replacement-password"


async def configure_private_role(env):
    uri = urlsplit(env["DATABASE_URL"])
    assert uri.hostname == "127.0.0.1" and uri.path == "/mv_local_proof"
    conn = await asyncpg.connect(
        host=uri.hostname,
        port=uri.port,
        user=uri.username,
        password=uri.password,
        database="mv_local_proof",
    )
    try:
        await conn.execute(f"""CREATE ROLE "{ROLE}" LOGIN PASSWORD '{SECRET}'""")
        await conn.execute(f'ALTER DATABASE mv_local_proof OWNER TO "{ROLE}"')
    finally:
        await conn.close()
    return {
        **env,
        "DATABASE_URL": "",
        "POSTGRES_USER": ROLE,
        "POSTGRES_PASSWORD": SECRET,
        "POSTGRES_HOST": uri.hostname,
        "POSTGRES_PORT": str(uri.port),
        "POSTGRES_DB": "mv_local_proof",
    }


def bearer(response):
    return {"Authorization": "Bearer " + response.json()["accessToken"]}


async def login(client, username):
    return await client.post(
        "/api/auth/login", json={"username": username, "password": ORIGINAL}
    )


async def waiting_for_user_row(connection):
    async with asyncio.timeout(6):
        while not await connection.fetchval(
            """SELECT EXISTS(SELECT 1 FROM pg_stat_activity
                WHERE datname=current_database() AND pid<>pg_backend_pid()
                  AND wait_event_type='Lock' AND query ILIKE '%FOR%UPDATE%')"""
        ):
            await asyncio.sleep(0.02)


async def assert_rotation_order(app, sessions, observer, first_path, batch_headers):
    from app import main
    from app.auth import hash_password
    from app.models import UserModel

    username = "test-first-" + first_path.split("/")[-1]
    async with sessions.begin() as db:
        db.add(
            UserModel(
                id=username, username=username, password_hash=hash_password(ORIGINAL)
            )
        )
    transport = httpx.ASGITransport(app=app)
    async with (
        httpx.AsyncClient(
            transport=transport, base_url="http://local", headers=batch_headers
        ) as owner,
        httpx.AsyncClient(
            transport=transport, base_url="http://local", headers=batch_headers
        ) as contender,
    ):
        initial = await login(owner, username)
        assert initial.status_code == 200, initial.status_code
        entered, release = asyncio.Event(), asyncio.Event()
        issue = main.issue_tokens

        async def paused_at_issue(user, request, response, db):
            if request.url.path == first_path:
                entered.set()
                await release.wait()
            return await issue(user, request, response, db)

        def change():
            return owner.post(
                "/api/auth/change-password",
                headers=bearer(initial),
                json={"current_password": ORIGINAL, "new_password": REPLACEMENT},
            )

        with patch.object(main, "issue_tokens", paused_at_issue):
            calls = {
                "login": lambda: login(contender, username),
                "change-password": change,
            }
            first = first_path.split("/")[-1]
            second = next(key for key in calls if key != first)
            waiting = {}
            try:
                waiting[first] = asyncio.create_task(calls[first]())
                await asyncio.wait_for(entered.wait(), timeout=6)
                waiting[second] = asyncio.create_task(calls[second]())
                await waiting_for_user_row(observer)
            finally:
                release.set()
                await asyncio.gather(*waiting.values(), return_exceptions=True)
            logged, changed = (
                waiting["login"].result(),
                waiting["change-password"].result(),
            )
        assert changed.status_code == 200, changed.status_code
        assert logged.status_code == (200 if first == "login" else 401), (
            logged.status_code
        )
        if first == "login":
            assert (
                await contender.get("/api/auth/me", headers=bearer(logged))
            ).status_code == 401
            assert (await contender.post("/api/auth/refresh")).status_code == 401
        assert (
            await owner.get("/api/auth/me", headers=bearer(initial))
        ).status_code == 401
        assert (
            await owner.get("/api/auth/me", headers=bearer(changed))
        ).status_code == 200
        active = await observer.fetchval(
            "SELECT count(*) FROM refresh_tokens WHERE user_id=$1 AND deleted_at IS NULL AND revoked_at IS NULL",
            username,
        )
        assert active == 1, active
    return username, bearer(changed)


async def slow_stream(app, path, headers, ready, closed):
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "method": "GET",
        "http_version": "1.1",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "server": ("local", 80),
        "client": ("127.0.0.1", 1234),
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
    }
    first_receive = True

    async def receive():
        nonlocal first_receive
        if first_receive:
            first_receive = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await closed.wait()
        return {"type": "http.disconnect"}

    async def send(event):
        if event["type"] == "http.response.start":
            assert event["status"] == 200, (path, event["status"])
        if event["type"] == "http.response.body" and event.get("body"):
            assert event["body"].startswith(b"data:"), path
            ready.set()
            await closed.wait()

    await app(scope, receive, send)


async def assert_pool_available(app, sessions, user, headers):
    from app.models import (
        ChatSessionModel,
        GenerationJobModel,
        MaterialExportModel,
        ProjectModel,
        ProjectTaskModel,
    )

    async with sessions.begin() as db:
        db.add(ProjectModel(id="project", name="synthetic", user_id=user))
        await db.flush()
        db.add(
            ProjectTaskModel(
                id="task", project_id="project", title="synthetic", status="outlining"
            )
        )
        await db.flush()
        db.add_all(
            [
                ChatSessionModel(id="chat", user_id=user, system_prompt="synthetic"),
                GenerationJobModel(
                    id="job",
                    user_id=user,
                    kind="synthetic",
                    generation_origin="agent_test",
                    agent_name="code-agent",
                    agent_run_id=headers["X-Agent-Run-Id"],
                ),
                MaterialExportModel(id="export", user_id=user, project_task_id="task"),
            ]
        )
    paths = [
        "/api/chat/chat/events",
        "/api/generations/job/events",
        "/api/tasks/task/storyboard-outline/events",
        "/api/material-exports/export/events",
    ] * 2
    ready = [asyncio.Event() for _ in paths]
    closed = asyncio.Event()
    tasks = [
        asyncio.create_task(slow_stream(app, path, headers, signal, closed))
        for path, signal in zip(paths, ready, strict=True)
    ]
    try:
        await asyncio.wait_for(
            asyncio.gather(*(signal.wait() for signal in ready)), timeout=12
        )
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://local",
            headers=headers,
        ) as client:
            async with asyncio.timeout(5):
                for _ in range(6):
                    ordinary = await client.get("/api/auth/me")
                    assert ordinary.status_code == 200, ordinary.status_code
            assert all(not task.done() for task in tasks)
    finally:
        closed.set()
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=8)


async def exercise():
    from app import database
    from app.config import settings
    from app.redis_store import close_redis
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    uri = urlsplit(settings.database_url)
    assert (
        uri.hostname == "127.0.0.1"
        and uri.path == "/mv_local_proof"
        and settings.redis_url == "fakeredis://"
    )
    original_engine = database.engine
    database.engine = create_async_engine(
        settings.database_url, pool_size=2, max_overflow=0, pool_timeout=3
    )
    database.session_factory.configure(bind=database.engine)
    from app.main import app

    conn = await asyncpg.connect(
        host=uri.hostname,
        port=uri.port,
        user=ROLE,
        password=SECRET,
        database="mv_local_proof",
    )
    batch = uuid4().hex
    headers = {
        "X-Agent-Name": "code-agent",
        "X-Agent-Run-Id": batch,
        "X-Test-Run-Id": batch,
    }
    try:
        assert await conn.fetchval("SELECT version_num FROM alembic_version")
        for path in ("/api/auth/login", "/api/auth/change-password"):
            user, auth = await assert_rotation_order(
                app, database.session_factory, conn, path, headers
            )
        print(
            "PASS API-02: both lock orders observed in PostgreSQL, only the changed-password session remains active"
        )
        await assert_pool_available(
            app, database.session_factory, user, {**headers, **auth}
        )
        async with database.session_factory() as db:
            assert await db.scalar(text("SELECT 1")) == 1
        print(
            "PASS API-04: 8 open slow readers across 4 SSE endpoints, pool size 2 with no overflow, 6 normal authenticated reads succeeded"
        )
    finally:
        await conn.close()
        await close_redis()
        await database.close_database()
        await original_engine.dispose()


def main():
    if sys.argv[1:] == ["--inside-private-instance"]:
        asyncio.run(exercise())
        return
    with local_runtime.dependencies(redis=False) as env:
        private = asyncio.run(configure_private_role(env))
        result = local_runtime.run(
            [local_runtime.PYTHON, "-m", "alembic", "upgrade", "head"],
            cwd=local_runtime.ROOT / "backend",
            env=private,
            capture_output=True,
            text=True,
        )
        assert all(
            value not in result.stdout + result.stderr
            for value in (SECRET, quote(SECRET, safe=""))
        )
        print(
            "PASS OPS-02: reserved-character PostgreSQL role and password migrated to Alembic head",
            flush=True,
        )
        local_runtime.run(
            [local_runtime.PYTHON, __file__, "--inside-private-instance"],
            cwd=local_runtime.ROOT,
            env=private,
        )


if __name__ == "__main__":
    main()
