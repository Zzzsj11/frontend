from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_repeated_system_initialization_never_creates_user_accounts(monkeypatch):
    from app import seed
    from app.models import AdminRoleModel, Base, UserModel

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        monkeypatch.setattr(seed, "session_factory", factory)
        await seed.seed_system_data()
        await seed.seed_system_data()
        async with factory() as db:
            assert await db.scalar(select(func.count()).select_from(UserModel)) == 0
            assert await db.scalar(select(func.count()).select_from(AdminRoleModel)) >= 2
    finally:
        await engine.dispose()
