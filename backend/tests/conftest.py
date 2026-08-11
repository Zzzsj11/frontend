from __future__ import annotations

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

    from app.main import app

    with TestClient(app) as test_client:
        # 统一打上测试批次头，每次全量测试的 API 耗时自动入库（管理后台「接口耗时」可见）
        test_client.headers["X-Test-Run-Id"] = f"pytest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
        login = test_client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
        assert login.status_code == 200
        test_client.headers["Authorization"] = f"Bearer {login.json()['accessToken']}"
        yield test_client
    TEST_DB.unlink(missing_ok=True)
