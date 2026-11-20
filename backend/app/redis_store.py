from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

from .config import settings

if settings.redis_url.startswith("fakeredis://"):
    import fakeredis.aioredis

    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
else:
    from redis.asyncio import Redis

    redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def redis_ok() -> bool:
    try:
        return bool(await redis.ping())
    except Exception:
        return False


async def close_redis() -> None:
    await redis.aclose()


async def reserve_login_attempt(identities: tuple[str, ...], limit: int, seconds: int) -> str | None:
    reservation = uuid.uuid4().hex
    keys = [f"auth:attempts:{identity}" for identity in identities]
    accepted = await redis.eval(
        """
        local now = tonumber(ARGV[1])
        for _, key in ipairs(KEYS) do
            redis.call('ZREMRANGEBYSCORE', key, '-inf', now - tonumber(ARGV[2]))
            if redis.call('ZCARD', key) >= tonumber(ARGV[3]) then return 0 end
        end
        for _, key in ipairs(KEYS) do
            redis.call('ZADD', key, now, ARGV[4])
            redis.call('EXPIRE', key, ARGV[2])
        end
        return 1
    """,
        len(keys),
        *keys,
        time.time(),
        seconds,
        limit,
        reservation,
    )
    return reservation if accepted else None


async def release_login_attempt(identities: tuple[str, ...], reservation: str) -> None:
    async with redis.pipeline(transaction=True) as pipe:
        for identity in identities:
            pipe.zrem(f"auth:attempts:{identity}", reservation)
        await pipe.execute()


_ACQUIRE_PROVIDER_REQUEST_PERMIT = """
local requests_key, cooldown_key = KEYS[1], KEYS[2]
local now, window, limit, token = tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4]
local cooldown_ttl = redis.call('PTTL', cooldown_key)
if cooldown_ttl > 0 then return {-1, cooldown_ttl} end
redis.call('ZREMRANGEBYSCORE', requests_key, '-inf', now-window)
local count = redis.call('ZCARD', requests_key)
if count >= limit then
  local oldest = redis.call('ZRANGE', requests_key, 0, 0, 'WITHSCORES')
  local retry = window
  if #oldest == 2 then retry = math.max(1, window-(now-tonumber(oldest[2]))) end
  return {0, retry}
end
redis.call('ZADD', requests_key, now, token)
redis.call('PEXPIRE', requests_key, window)
return {1, 0}
"""

_SET_PROVIDER_COOLDOWN = """
local current = redis.call('PTTL', KEYS[1])
local requested = tonumber(ARGV[1])
if current < requested then
  redis.call('SET', KEYS[1], '1', 'PX', requested)
  return requested
end
return current
"""


async def acquire_provider_request_permit(provider: str, limit: int, window_seconds: int = 60) -> tuple[bool, int, str] | None:
    """Acquire a shared rolling-window supplier API permit.

    ``None`` means Redis is unavailable and lets the caller use its local
    safety fallback. A denied permit reports whether a supplier cooldown or
    the application's own request budget caused the denial.
    """
    now_ms = int(time.time() * 1000)
    window_ms = max(1, window_seconds) * 1000
    try:
        result = await redis.eval(
            _ACQUIRE_PROVIDER_REQUEST_PERMIT,
            2,
            f"provider-rate:{provider}:requests",
            f"provider-rate:{provider}:cooldown",
            now_ms,
            window_ms,
            max(1, limit),
            uuid.uuid4().hex,
        )
        status, retry_ms = int(result[0]), int(result[1])
        if status == 1:
            return True, 0, "ok"
        return False, max(1, (retry_ms + 999) // 1000), "cooldown" if status == -1 else "budget"
    except Exception:
        return None


async def set_provider_cooldown(provider: str, seconds: int) -> None:
    """Share a real supplier 429 cooldown across all API processes."""
    try:
        await redis.eval(_SET_PROVIDER_COOLDOWN, 1, f"provider-rate:{provider}:cooldown", max(1, seconds) * 1000)
    except Exception:
        return


async def provider_cooldown_remaining(provider: str) -> int | None:
    """Return shared cooldown seconds, zero when clear, or None without Redis."""
    try:
        ttl_ms = int(await redis.pttl(f"provider-rate:{provider}:cooldown"))
        return max(0, (ttl_ms + 999) // 1000)
    except Exception:
        return None


async def cache_job(job_id: str, snapshot: dict[str, Any]) -> None:
    try:
        await redis.set(f"job:{job_id}", json.dumps({key: value for key, value in snapshot.items() if key != "retryAllowed"}, ensure_ascii=False), ex=7 * 24 * 3600)
        await redis.publish(f"job-events:{job_id}", json.dumps(snapshot, ensure_ascii=False))
    except Exception:
        # PostgreSQL is the job source of truth. Cache/event loss may increase
        # polling latency but must never fail a durable submission or runner.
        return


async def notify_worker(kind: str) -> None:
    """Best-effort wakeup only; PostgreSQL remains the durable queue."""
    try:
        await redis.publish("worker:wakeup", kind)
    except Exception:
        # A temporary Redis outage must not lose a database-backed job.
        return


async def wait_for_worker_wakeup(timeout_seconds: float) -> None:
    """Wait for a best-effort wakeup, falling back to the caller's poll timeout."""
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe("worker:wakeup")
        # ``get_message(ignore_subscribe_messages=True)`` may consume the
        # subscription acknowledgement and return immediately instead of
        # waiting for ``timeout``.  Workers then spin on an empty queue and can
        # consume an entire CPU core.  ``listen`` blocks for the next Pub/Sub
        # event; the timeout preserves PostgreSQL polling as the durable
        # fallback when no notification arrives.
        async with asyncio.timeout(max(0.0, timeout_seconds)):
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    return
    except TimeoutError:
        return
    except Exception:
        # Redis 不可达时仍保持数据库轮询间隔，避免空转抢占 CPU。
        await asyncio.sleep(max(0.05, min(5.0, timeout_seconds)))
        return
    finally:
        try:
            await pubsub.aclose()
        except Exception:
            pass


_ACQUIRE_POOL_LEASE = """
local key, now, expires, limit, token = KEYS[1], tonumber(ARGV[1]), tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4]
redis.call('ZREMRANGEBYSCORE', key, '-inf', now)
if redis.call('ZCARD', key) >= limit then return 0 end
redis.call('ZADD', key, expires, token)
redis.call('EXPIRE', key, math.max(1, math.ceil((expires-now)/1000)))
return 1
"""


class ExecutionStoreUnavailable(RuntimeError):
    """Capacity is unknown because the coordination store could not be queried."""


async def acquire_execution_lease(pool: str, limit: int, ttl_seconds: int) -> str | None:
    """Atomically acquire a cross-process model execution slot in Redis."""
    token = uuid.uuid4().hex
    now_ms = int(time.time() * 1000)
    try:
        acquired = await redis.eval(
            _ACQUIRE_POOL_LEASE,
            1,
            f"execution-pool:{pool}",
            now_ms,
            now_ms + ttl_seconds * 1000,
            limit,
            token,
        )
        return token if int(acquired or 0) == 1 else None
    except Exception as exc:
        raise ExecutionStoreUnavailable(f"执行池 {pool} 的 Redis 租约服务不可用") from exc


_RENEW_POOL_LEASE = """
local key, token, expires, ttl = KEYS[1], ARGV[1], ARGV[2], tonumber(ARGV[3])
if not redis.call('ZSCORE', key, token) then return 0 end
redis.call('ZADD', key, 'XX', expires, token)
redis.call('EXPIRE', key, math.max(1, ttl))
return 1
"""


async def renew_execution_lease(pool: str, token: str, ttl_seconds: int) -> bool:
    try:
        renewed = await redis.eval(_RENEW_POOL_LEASE, 1, f"execution-pool:{pool}", token, int(time.time() * 1000) + ttl_seconds * 1000, ttl_seconds)
        return bool(renewed)
    except Exception as exc:
        raise ExecutionStoreUnavailable(f"执行池 {pool} 续租失败") from exc


async def release_execution_lease(pool: str, token: str) -> None:
    try:
        await redis.zrem(f"execution-pool:{pool}", token)
    except Exception:
        return


async def get_cached_job(job_id: str) -> dict[str, Any] | None:
    try:
        raw = await redis.get(f"job:{job_id}")
    except Exception:
        return None
    return json.loads(raw) if raw else None


async def append_chat_event(session_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    raw = await redis.eval(
        """
        local seq = redis.call('INCR', KEYS[1])
        local event = cjson.encode({seq=seq, type=ARGV[1], data=cjson.decode(ARGV[2])})
        redis.call('RPUSH', KEYS[2], event)
        redis.call('LTRIM', KEYS[2], -2000, -1)
        redis.call('EXPIRE', KEYS[2], 2592000)
        redis.call('PUBLISH', KEYS[3], event)
        return event
    """,
        3,
        f"chat:{session_id}:seq",
        f"chat:{session_id}:events",
        f"chat-events:{session_id}",
        event_type,
        json.dumps(data, ensure_ascii=False),
    )
    return json.loads(raw)


async def chat_events_after(session_id: str, after: int) -> list[dict[str, Any]]:
    rows = await redis.eval(
        """
        local latest = tonumber(redis.call('GET', KEYS[1]) or '0')
        local count = math.min(2000, latest - tonumber(ARGV[1]))
        if count <= 0 then return {} end
        return redis.call('LRANGE', KEYS[2], -count, -1)
    """,
        2,
        f"chat:{session_id}:seq",
        f"chat:{session_id}:events",
        max(0, after),
    )
    return [event for raw in rows if (event := json.loads(raw))["seq"] > after]
