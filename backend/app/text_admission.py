"""Shared text admission across API and storyboard workers."""

import asyncio
from contextlib import asynccontextmanager
from contextvars import ContextVar

from .config import settings
from .redis_store import acquire_execution_lease, acquire_provider_request_permit, release_execution_lease, renew_execution_lease, set_provider_cooldown

_slots = asyncio.Semaphore(settings.text_generation_concurrency)
POOL = "all-in-one-text"
_admitted = ContextVar("text_admitted", default=False)


@asynccontextmanager
async def text_slot():
    if _admitted.get():
        yield
        return
    async with _slots:
        token = None
        heartbeat = None
        context = None
        try:
            while not token:
                token = await acquire_execution_lease(POOL, settings.text_generation_concurrency, 90)
                if not token:
                    await asyncio.sleep(0.5)

            async def renew():
                while True:
                    await asyncio.sleep(25)
                    await renew_execution_lease(POOL, token, 90)

            heartbeat = asyncio.create_task(renew())
            # 共享滚动窗口和故障冷却，避免多 Worker 同时恢复时形成请求突发。
            while True:
                permit = await acquire_provider_request_permit(POOL, 60)
                if permit is None or permit[0]:
                    break
                await asyncio.sleep(min(permit[1], 2))
            context = _admitted.set(True)
            yield
        finally:
            if context is not None:
                _admitted.reset(context)
            if heartbeat:
                heartbeat.cancel()
                await asyncio.gather(heartbeat, return_exceptions=True)
            if token:
                await release_execution_lease(POOL, token)


async def cooldown():
    await set_provider_cooldown(POOL, 5)
