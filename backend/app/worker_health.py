"""容器健康检查：确认本容器实际 Worker 的数据库心跳仍在推进。"""

from __future__ import annotations

import asyncio
import socket
from datetime import timedelta

from sqlalchemy import select

from .config import settings
from .database import close_database, session_factory
from .models import WorkerInstanceModel, utcnow


async def healthy() -> bool:
    async with session_factory() as session:
        instance = await session.scalar(
            select(WorkerInstanceModel.id)
            .where(
                WorkerInstanceModel.hostname == socket.gethostname(),
                WorkerInstanceModel.status == "running",
                WorkerInstanceModel.deleted_at.is_(None),
                WorkerInstanceModel.last_heartbeat_at > utcnow() - timedelta(seconds=max(45, settings.worker_stale_seconds)),
            )
            .limit(1)
        )
        return bool(instance)


async def main() -> bool:
    try:
        return await healthy()
    finally:
        await close_database()


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(main()) else 1)
