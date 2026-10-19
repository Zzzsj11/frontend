from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

import pytest

TEST_DB_DIR = Path(tempfile.mkdtemp(prefix="mv-agent-backend-test-"))
TEST_DB = TEST_DB_DIR / "database.sqlite3"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB}"
os.environ["REDIS_URL"] = "fakeredis://"
# Unit tests must never inherit paid text credentials or a routing channel from .env.
os.environ["LLM_CHANNEL"] = ""
os.environ["LLM_API_KEY"] = "test-only-llm-key"
os.environ["ALL_IN_ONE_API_KEY"] = "test-only-all-in-one-key"
os.environ["AIGC_TOKEN"] = "test-only-shared-provider-key"
os.environ["GENERAL_OUTLINE_LLM_MODEL"] = ""
os.environ["VIDEO_MODEL"] = "doubao-seedance-2.0-all-in-one"


@pytest.fixture(scope="session")
def client():
    import dataclasses

    from fastapi.testclient import TestClient

    from app.auth import hash_password
    from app.database import engine, session_factory
    from app.models import AdminRoleModel, Base, UserAdminRoleModel, UserModel

    async def create_test_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        # Explicit fixture-only identity; the application never creates default users.
        async with session_factory() as db:
            admin = UserModel(id=f"user-{uuid4().hex}", username="admin", password_hash=hash_password("123456"), role="admin", must_change_password=True)
            db.add(admin)
            db.add(AdminRoleModel(id="admin-role-super", code="super_admin", name="超级管理员", description="测试角色"))
            await db.flush()
            db.add(UserAdminRoleModel(id=f"uar-super-{admin.id}", user_id=admin.id, role_id="admin-role-super"))
            await db.commit()

    # SQLite is an isolated test database; deployed databases remain Alembic-only.
    asyncio.run(create_test_schema())
    from app import main

    main.settings = dataclasses.replace(main.settings, toapis_api_key="test-only-toapis-key")
    app = main.app

    with TestClient(app) as test_client:
        # 统一打上测试批次头，每次全量测试的 API 耗时自动入库（管理后台「接口耗时」可见）
        run_id = f"pytest-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}-{uuid4().hex[:12]}"
        test_client.headers.update({"X-Test-Run-Id": run_id, "X-Agent-Name": "code-agent", "X-Agent-Run-Id": run_id})
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
    shutil.rmtree(TEST_DB_DIR, ignore_errors=True)
