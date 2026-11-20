"""Shared text admission across API and storyboard workers."""

import asyncio
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

from sqlalchemy import text

from .config import settings
from .database import session_factory
from .redis_store import ExecutionStoreUnavailable, acquire_execution_lease, acquire_provider_request_permit, release_execution_lease, renew_execution_lease, set_provider_cooldown

_slots = asyncio.Semaphore(settings.text_generation_concurrency)
POOL = "all-in-one-text"
_admitted = ContextVar("text_admitted", default=False)


async def _acquire_text_slot():
    limit = settings.text_generation_concurrency
    if not settings.database_url.startswith("postgresql"):
        return await acquire_execution_lease(POOL, limit, 90)
    owner = uuid.uuid4().hex
    async with session_factory.begin() as db:
        return await db.scalar(
            text("""
            INSERT INTO text_execution_slots (slot,owner,expires_at,created_at,updated_at)
            SELECT i, :owner, now() + interval '90 seconds', now(), now()
            FROM generate_series(1, CAST(:limit AS integer)) AS i
            LEFT JOIN text_execution_slots s ON s.slot = i
            WHERE s.slot IS NULL OR s.expires_at <= now()
            ORDER BY i LIMIT 1
            ON CONFLICT(slot) DO UPDATE SET owner=excluded.owner, expires_at=excluded.expires_at,
               updated_at=excluded.updated_at, deleted_at=NULL
            WHERE text_execution_slots.expires_at <= now()
            RETURNING owner
        """),
            {"limit": limit, "owner": owner},
        )


async def _renew_text_slot(token):
    if not settings.database_url.startswith("postgresql"):
        return await renew_execution_lease(POOL, token, 90)
    async with session_factory.begin() as db:
        return bool(
            await db.scalar(
                text("""
            UPDATE text_execution_slots SET expires_at=now() + interval '90 seconds', updated_at=now()
            WHERE owner=:owner AND expires_at > now() RETURNING slot
        """),
                {"owner": token},
            )
        )


async def _release_text_slot(token):
    if not settings.database_url.startswith("postgresql"):
        await release_execution_lease(POOL, token)
        return
    async with session_factory.begin() as db:
        await db.execute(text("UPDATE text_execution_slots SET expires_at=now(), updated_at=now() WHERE owner=:owner"), {"owner": token})


@asynccontextmanager
async def text_slot():
    if _admitted.get():
        yield
        return
    async with _slots:
        token = None
        heartbeat = None
        context = None
        lease_lost = False
        try:
            async with asyncio.timeout(settings.storyboard_line_timeout_seconds):
                while not token:
                    token = await _acquire_text_slot()
                    if not token:
                        await asyncio.sleep(0.5)
            owner = asyncio.current_task()

            async def renew():
                nonlocal lease_lost
                try:
                    while True:
                        await asyncio.sleep(25)
                        if not await _renew_text_slot(token):
                            break
                except Exception:
                    pass
                lease_lost = True
                owner.cancel()

            heartbeat = asyncio.create_task(renew())
            # 共享滚动窗口和故障冷却，避免多 Worker 同时恢复时形成请求突发。
            while True:
                permit = await acquire_provider_request_permit(POOL, 60)
                if permit is None or permit[0]:
                    break
                await asyncio.sleep(min(permit[1], 2))
            context = _admitted.set(True)
            yield
        except asyncio.CancelledError:
            if lease_lost:
                raise ExecutionStoreUnavailable("文本执行租约失效，请核对原工单") from None
            raise
        finally:
            if context is not None:
                _admitted.reset(context)
            if heartbeat:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            if token:
                await _release_text_slot(token)


async def cooldown():
    await set_provider_cooldown(POOL, 5)
