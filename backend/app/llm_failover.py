"""Per-channel circuit breaker for the primary text model."""

from __future__ import annotations

import logging

from .config import settings
from .redis_store import redis

PRIMARY_MODEL = "gpt-6.1-sol"
FALLBACK_MODEL = "gpt-6-sol"
FAILURE_LIMIT = 5
COOLDOWN_SECONDS = 2 * 60 * 60
TEXT_CHANNELS = frozenset({"yseeai", "toapis", "all-in-one"})
logger = logging.getLogger("mvagent.llm_failover")

_RECORD_FAILURE = """
local count = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
return count
"""


def applies(model: str) -> bool:
    return settings.llm_channel in TEXT_CHANNELS and model == PRIMARY_MODEL + ("-all-in-one" if settings.llm_channel == "all-in-one" else "")


def failures_key() -> str:
    return f"llm:failover:{settings.llm_channel}:{PRIMARY_MODEL}:failures"


async def choose_model(model: str) -> str:
    if not applies(model):
        return model
    try:
        failures = int(await redis.get(failures_key()) or 0)
    except Exception:
        logger.warning("Unable to read text-model failover state", exc_info=True)
        return model
    return FALLBACK_MODEL + ("-all-in-one" if settings.llm_channel == "all-in-one" else "") if failures >= FAILURE_LIMIT else model


async def record_success(model: str) -> None:
    if not applies(model):
        return
    try:
        await redis.delete(failures_key())
    except Exception:
        logger.warning("Unable to reset text-model failover state", exc_info=True)


async def record_failure(model: str) -> None:
    if not applies(model):
        return
    try:
        failures = int(await redis.eval(_RECORD_FAILURE, 1, failures_key(), COOLDOWN_SECONDS))
        if failures == FAILURE_LIMIT:
            logger.error("%s primary text model failed five consecutive calls; switching to %s for %s seconds", settings.llm_channel, FALLBACK_MODEL, COOLDOWN_SECONDS)
    except Exception:
        logger.warning("Unable to update text-model failover state", exc_info=True)
