from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

TEST_DB = Path("/tmp/mv-agent-backend-test.sqlite3")
TEST_DB.unlink(missing_ok=True)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["REDIS_URL"] = "fakeredis://"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.database import engine
    from app.models import Base

    async def create_test_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    # SQLite is an isolated test database; deployed databases remain Alembic-only.
    asyncio.run(create_test_schema())
    from app.main import app

    with TestClient(app) as test_client:
        # 统一打上测试批次头，每次全量测试的 API 耗时自动入库（管理后台「接口耗时」可见）
        test_client.headers["X-Test-Run-Id"] = f"pytest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        login = test_client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
        assert login.status_code == 200
        test_client.headers["Authorization"] = f"Bearer {login.json()['accessToken']}"
        changed = test_client.post(
            "/api/auth/change-password",
            json={"current_password": "123456", "new_password": "secure-admin-123"},
        )
        assert changed.status_code == 200
        test_client.headers["Authorization"] = f"Bearer {changed.json()['accessToken']}"
        yield test_client
    TEST_DB.unlink(missing_ok=True)
