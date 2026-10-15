"""Shared, task-deduplicated Nano circuit breaker; never resubmit failed jobs."""

from __future__ import annotations

import logging

from sqlalchemy import select

from .image_model_policy import validate_image_selection
from .models import AiModelModel, AiProviderModel
from .redis_store import redis

PRIMARY_MODEL = "nano-banana-2.1-all-in-one"
FALLBACK_MODEL = "seedream-5.0-pro-all-in-one"
FAILURE_LIMIT = 3
COOLDOWN_SECONDS = 2 * 60 * 60
FAILURES_KEY = "image:failover:all-in-one:nano-banana-2.1:failures"
logger = logging.getLogger(__name__)

_RECORD_OUTCOME = """
if not redis.call('SET', KEYS[2], ARGV[1], 'NX', 'EX', ARGV[2]) then return -1 end
if ARGV[1] == 'success' then redis.call('DEL', KEYS[1]); return 0 end
local count = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return count
"""


async def choose_model(model: str) -> str:
    if model != PRIMARY_MODEL:
        return model
    try:
        return FALLBACK_MODEL if int(await redis.get(FAILURES_KEY) or 0) >= FAILURE_LIMIT else model
    except Exception:
        logger.warning("Unable to read image failover state", exc_info=True)
        return model


async def record_outcome(job, *, succeeded: bool) -> None:
    request = job.request or {}
    if job.kind != "image" or request.get("_provider") != "all-in-one" or request.get("model") != PRIMARY_MODEL:
        return
    try:
        count = await redis.eval(_RECORD_OUTCOME, 2, FAILURES_KEY, FAILURES_KEY + ":outcome:" + job.id, "success" if succeeded else "failure", COOLDOWN_SECONDS)
        if count == FAILURE_LIMIT:
            logger.error("Nano failed three consecutive tasks; using Seedream Pro for two hours")
    except Exception:
        logger.warning("Unable to update image failover state", exc_info=True)


async def prepare_request(session, request: dict) -> dict:
    """Freeze the actual model before queue admission so pool, usage and replay agree."""
    if request.get("_provider") != "all-in-one" or await choose_model(request.get("model", "")) != FALLBACK_MODEL or request.get("model") != PRIMARY_MODEL:
        return request
    row = (
        await session.execute(
            select(AiModelModel, AiProviderModel)
            .join(AiProviderModel, AiProviderModel.id == AiModelModel.provider_id)
            .where(
                AiModelModel.code == FALLBACK_MODEL,
                AiModelModel.modality == "image",
                AiModelModel.status == "active",
                AiModelModel.deleted_at.is_(None),
                AiProviderModel.code == "all-in-one",
                AiProviderModel.status == "active",
                AiProviderModel.deleted_at.is_(None),
            )
        )
    ).one_or_none()
    if row is None:
        return {**request, "_imageFailover": {"skipped": "backup_unavailable"}}
    model, _provider = row
    caps = model.capabilities or {}
    # Seedream has no 4K output. Keep the requested ratio/references, record the downgrade.
    resolution = "2K" if request.get("resolution") == "4K" else request.get("resolution", "1K")
    from fastapi import HTTPException

    try:
        validate_image_selection(
            model.code,
            caps,
            size=request.get("size", "16:9"),
            resolution=resolution,
            purpose=request.get("purpose", "scene"),
            images=request.get("images", []),
            quality=request.get("quality", "auto"),
        )
    except HTTPException:
        return {**request, "_imageFailover": {"skipped": "incompatible_backup_capabilities"}}
    return {
        **request,
        "model": model.code,
        "resolution": resolution,
        "_providerModelId": model.provider_model_id,
        "_capabilities": caps,
        "_executionPool": caps.get("executionPool") or "all-in-one:seedream-5.0-pro",
        "_executionConcurrency": caps.get("executionConcurrency") or 5,
        "_imageFailover": {
            "requestedModel": PRIMARY_MODEL,
            "requestedResolution": request.get("resolution", "1K"),
            "failureLimit": FAILURE_LIMIT,
            "cooldownSeconds": COOLDOWN_SECONDS,
        },
    }
