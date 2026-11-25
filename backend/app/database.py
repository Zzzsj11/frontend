from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .config import settings

pool_options = {}
if settings.database_url.startswith("postgresql"):
    pool_options = {"pool_size": max(1, int(os.getenv("DB_POOL_SIZE", "5"))), "max_overflow": max(0, int(os.getenv("DB_POOL_OVERFLOW", "2")))}
engine = create_async_engine(settings.database_url, pool_pre_ping=True, **pool_options)
session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def init_database() -> None:
    # Database schema is exclusively managed by Alembic in docker-entrypoint.sh.
    from sqlalchemy import text

    async with engine.connect() as connection:
        await connection.execute(text("SELECT 1"))


async def close_database() -> None:
    await engine.dispose()


async def database_session() -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session


async def database_ok() -> bool:
    from sqlalchemy import text

    try:
        async with session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
