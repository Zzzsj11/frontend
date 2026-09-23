"""Select before submission, then freeze the route. Never retry generation on another supplier."""

from types import SimpleNamespace

from fastapi import HTTPException
from sqlalchemy import select

from .channels import config
from .db import Job, ModelRoute
from .security import owner


async def resolve(db, model, request, client):
    if not model or not model.capabilities.get("unified_catalog"):
        return model, None
    existing = await db.scalar(
        select(Job).where(
            Job.client_id == client.id,
            Job.user_id == owner(request),
            Job.idempotency_key == request.headers.get("idempotency-key", ""),
            Job.model_id == model.id,
        )
    )
    if existing and existing.routing_snapshot:
        route = SimpleNamespace(**existing.routing_snapshot, model_id=model.id, enabled=True)
        effective = SimpleNamespace(
            id=model.id,
            enabled=model.enabled,
            deleted_at=model.deleted_at,
            kind=model.kind,
            channel=route.channel,
            provider_model=route.provider_model,
            protocol=route.protocol,
            capabilities={**model.capabilities, **route.capabilities},
        )
        return effective, route
    cached = getattr(request.state, "model_route", None)
    if cached and cached.model_id == model.id:
        routes = [cached]
    else:
        routes = list(
            (
                await db.scalars(
                    select(ModelRoute)
                    .where(ModelRoute.model_id == model.id, ModelRoute.deleted_at.is_(None))
                    .order_by(ModelRoute.priority, ModelRoute.id)
                )
            ).all()
        )
    forced = request.headers.get("x-test-supplier")
    if forced and not (client.require_agent and request.headers.get("x-agent-name") == "code-agent"):
        raise HTTPException(403, "Supplier override is restricted to attributed acceptance clients")
    for route in routes:
        if forced and route.supplier != forced:
            continue
        if (not route.enabled or route.verification != "passed") and not (forced and client.require_agent):
            continue
        try:
            config(route.channel)
        except ValueError:
            continue
        request.state.model_route = route
        effective = SimpleNamespace(
            id=model.id,
            enabled=model.enabled,
            deleted_at=model.deleted_at,
            kind=model.kind,
            channel=route.channel,
            provider_model=route.provider_model,
            protocol=route.protocol,
            capabilities={**model.capabilities, **route.capabilities},
        )
        return effective, route
    raise HTTPException(503, "No verified supplier route available for this model")


def snapshot(route):
    if not route:
        return {}
    return {
        "id": route.id,
        "supplier": route.supplier,
        "channel": route.channel,
        "provider_model": route.provider_model,
        "protocol": route.protocol,
        "capabilities": route.capabilities,
        "pricing": route.pricing,
        "concurrency": route.concurrency,
    }
