from __future__ import annotations

import json
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


async def login_attempt_count(key: str) -> int:
    return int(await redis.get(f"auth:login:{key}") or 0)


async def record_login_failure(key: str, window_seconds: int) -> int:
    """Increment a fixed-window login counter without storing raw usernames."""
    count = int(await redis.incr(f"auth:login:{key}"))
    if count == 1:
        await redis.expire(f"auth:login:{key}", window_seconds)
    return count


async def clear_login_attempts(key: str) -> None:
    await redis.delete(f"auth:login:{key}")


async def cache_job(job_id: str, snapshot: dict[str, Any]) -> None:
    await redis.set(f"job:{job_id}", json.dumps(snapshot, ensure_ascii=False), ex=7 * 24 * 3600)
    await redis.publish(f"job-events:{job_id}", json.dumps(snapshot, ensure_ascii=False))


async def notify_worker(kind: str) -> None:
    """Best-effort wakeup only; PostgreSQL remains the durable queue."""
    try:
        await redis.publish("worker:wakeup", kind)
    except Exception:
        # A temporary Redis outage must not lose a database-backed job.
        return


async def get_cached_job(job_id: str) -> dict[str, Any] | None:
    raw = await redis.get(f"job:{job_id}")
    return json.loads(raw) if raw else None


async def append_chat_event(session_id: str, event_type: str, data: dict[str, Any]) -> dict[str, Any]:
    seq = int(await redis.incr(f"chat:{session_id}:seq"))
    event = {"seq": seq, "type": event_type, "data": data}
    key = f"chat:{session_id}:events"
    await redis.rpush(key, json.dumps(event, ensure_ascii=False))
    await redis.ltrim(key, -2000, -1)
    await redis.expire(key, 30 * 24 * 3600)
    await redis.publish(f"chat-events:{session_id}", json.dumps(event, ensure_ascii=False))
    return event


async def chat_events_after(session_id: str, after: int) -> list[dict[str, Any]]:
    rows = await redis.lrange(f"chat:{session_id}:events", 0, -1)
    return [event for raw in rows if (event := json.loads(raw))["seq"] > after]
