from __future__ import annotations

import asyncio
import time

import pytest

from app import redis_store


class AtomicRateRedis:
    def __init__(self) -> None:
        self.lock = asyncio.Lock()
        self.requests: dict[str, list[int]] = {}
        self.cooldowns: dict[str, float] = {}

    async def eval(self, script, _key_count, *args):
        if script == redis_store._SET_PROVIDER_COOLDOWN:
            key, requested_ms = args
            async with self.lock:
                requested_until = time.monotonic() + requested_ms / 1000
                self.cooldowns[key] = max(self.cooldowns.get(key, 0), requested_until)
                return requested_ms
        requests_key, cooldown_key, now_ms, window_ms, limit, _token = args
        async with self.lock:
            cooldown_ms = int(max(0, self.cooldowns.get(cooldown_key, 0) - time.monotonic()) * 1000)
            if cooldown_ms > 0:
                return [-1, cooldown_ms]
            active = [value for value in self.requests.get(requests_key, []) if value > now_ms - window_ms]
            if len(active) >= limit:
                return [0, max(1, window_ms - (now_ms - active[0]))]
            active.append(now_ms)
            self.requests[requests_key] = active
            return [1, 0]

    async def pttl(self, key):
        return int(max(-1, self.cooldowns.get(key, 0) - time.monotonic()) * 1000)


@pytest.mark.asyncio
async def test_shared_provider_budget_is_atomic_under_concurrency(monkeypatch) -> None:
    fake_redis = AtomicRateRedis()
    monkeypatch.setattr(redis_store, "redis", fake_redis)
    provider = "test-concurrent-budget"
    results = await asyncio.gather(*(redis_store.acquire_provider_request_permit(provider, 45, 60) for _ in range(80)))

    assert sum(1 for result in results if result and result[0]) == 45
    denied = [result for result in results if result and not result[0]]
    assert len(denied) == 35
    assert all(result[2] == "budget" and result[1] >= 1 for result in denied)


@pytest.mark.asyncio
async def test_shared_provider_cooldown_blocks_all_callers(monkeypatch) -> None:
    fake_redis = AtomicRateRedis()
    monkeypatch.setattr(redis_store, "redis", fake_redis)
    provider = "test-shared-cooldown"
    await redis_store.set_provider_cooldown(provider, 60)

    results = await asyncio.gather(*(redis_store.acquire_provider_request_permit(provider, 45, 60) for _ in range(10)))

    assert all(result and not result[0] and result[2] == "cooldown" for result in results)
    assert all(result[1] >= 59 for result in results if result)
    assert await redis_store.provider_cooldown_remaining(provider) >= 59
