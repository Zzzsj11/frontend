import hashlib
import secrets
import uuid
from decimal import Decimal

from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .authentication import admin
from .authentication import router as auth_router
from .billing import router_for
from .channel_balances import router_for as channel_router_for
from .credits import amount, job_bill, lock, reset
from .db import Audit, Client, Job, Model, Session, now
from .routes import router_for as routes_router_for

app = FastAPI(title="Model Service Control API", version="1.0.0")
app.include_router(auth_router)


def audit(db, actor, action, target, detail):
    db.add(Audit(id=uuid.uuid4().hex, actor=actor, action=action, target=target, detail=detail))


def client_view(c):
    return {
        "id": c.id,
        "name": c.name,
        "key_prefix": c.key_prefix,
        "enabled": c.enabled,
        "allowed_models": c.allowed_models,
        "concurrency": c.concurrency,
        "require_agent": c.require_agent,
        "user_id": c.user_id,
        "billing_enabled": c.billing_enabled,
    }


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    allowed_models: list[str] = Field(default_factory=list)
    concurrency: int = Field(default=4, ge=1, le=200)
    require_agent: bool = False
    billing_enabled: bool = True
    user_id: str | None = None
    monthly_points: Decimal = Field(default=Decimal(0), ge=0, le=1000000000, decimal_places=6)


class ClientPatch(BaseModel):
    enabled: bool | None = None
    allowed_models: list[str] | None = None
    concurrency: int | None = Field(default=None, ge=1, le=200)
    require_agent: bool | None = None


@app.get("/admin/clients")
async def clients(actor=Depends(admin)):
    async with Session() as db:
        rows = (await db.scalars(select(Client).where(Client.deleted_at.is_(None)).order_by(Client.created_at.desc()))).all()
    return [client_view(c) for c in rows]


@app.post("/admin/clients", status_code=201)
async def create_client(body: ClientCreate, actor=Depends(admin)):
    key = "ms_" + secrets.token_urlsafe(32)
    async with Session.begin() as db:
        await lock(db)
        if body.user_id:
            raise HTTPException(403, "用户 Key 请由账号持有者登录后自行创建")
        c = Client(
            id="client-" + uuid.uuid4().hex,
            key_hash=hashlib.sha256(key.encode()).hexdigest(),
            key_prefix=key[:12],
            enabled=True,
            **body.model_dump(),
        )
        if c.user_id:
            c.billing_enabled = True
        c.monthly_balance = c.extra_balance = amount(0)
        c.billing_month = ""
        db.add(c)
        await db.flush()
        await reset(db, c)
        audit(db, actor, "client.create", c.id, {"name": c.name})
    return {**client_view(c), "api_key": key}


@app.patch("/admin/clients/{cid}")
async def patch_client(cid: str, body: ClientPatch, actor=Depends(admin)):
    async with Session.begin() as db:
        c = await db.get(Client, cid)
        if not c or c.deleted_at:
            raise HTTPException(404)
        changes = body.model_dump(exclude_none=True)
        for k, v in changes.items():
            setattr(c, k, v)
        audit(db, actor, "client.update", cid, changes)
    return client_view(c)


@app.post("/admin/clients/{cid}/rotate")
async def rotate(cid: str, actor=Depends(admin)):
    key = "ms_" + secrets.token_urlsafe(32)
    async with Session.begin() as db:
        c = await db.get(Client, cid)
        if not c or c.deleted_at:
            raise HTTPException(404)
        c.key_hash, c.key_prefix = hashlib.sha256(key.encode()).hexdigest(), key[:12]
        audit(db, actor, "client.rotate", cid, {})
    return {"api_key": key}


@app.delete("/admin/clients/{cid}", status_code=204)
async def delete_client(cid: str, actor=Depends(admin)):
    async with Session.begin() as db:
        c = await db.get(Client, cid)
        if not c or c.deleted_at:
            raise HTTPException(404)
        c.deleted_at, c.enabled = now(), False
        audit(db, actor, "client.delete", cid, {})


@app.get("/admin/models")
async def models(actor=Depends(admin)):
    async with Session() as db:
        rows = (await db.scalars(select(Model).where(Model.deleted_at.is_(None)).order_by(Model.channel, Model.id))).all()
    if any(m.capabilities.get("unified_catalog") for m in rows):
        rows = [m for m in rows if m.capabilities.get("unified_catalog")]
    return [
        {
            "id": m.id,
            "channel": m.channel,
            "provider_model": m.provider_model,
            "kind": m.kind,
            "protocol": m.protocol,
            "enabled": m.enabled,
            "concurrency": m.concurrency,
            "capabilities": m.capabilities,
        }
        for m in rows
    ]


class ModelPatch(BaseModel):
    enabled: bool | None = None
    concurrency: int | None = Field(default=None, ge=1, le=200)


@app.patch("/admin/models/{mid}")
async def patch_model(mid: str, body: ModelPatch, actor=Depends(admin)):
    async with Session.begin() as db:
        m = await db.get(Model, mid)
        if not m or m.deleted_at:
            raise HTTPException(404)
        changes = body.model_dump(exclude_none=True)
        for k, v in changes.items():
            setattr(m, k, v)
        audit(db, actor, "model.update", mid, changes)
    return {"ok": True}


def job_view(j):
    return {
        "id": j.id,
        "client_id": j.client_id,
        "user_id": j.user_id,
        "model": j.model_id,
        "kind": j.kind,
        "route_id": j.route_id,
        "supplier": (j.routing_snapshot or {}).get("supplier", j.channel),
        "status": j.status,
        "provider_task_id": j.provider_id,
        "origin": j.origin,
        "agent_name": j.agent_name,
        "agent_run_id": j.agent_run_id,
        "test_run_id": j.test_run_id,
        "usage": j.usage,
        "billing": job_bill(j),
        "error": j.error,
        "created_at": j.created_at.isoformat(),
    }


@app.get("/admin/jobs")
async def jobs(
    status: str | None = None,
    origin: str | None = None,
    client_id: str | None = None,
    agent_run_id: str | None = None,
    page: int = 1,
    limit: int = 50,
    actor=Depends(admin),
):
    limit = max(1, min(limit, 200))
    query = select(Job).where(Job.deleted_at.is_(None))
    for field, value in [("status", status), ("origin", origin), ("client_id", client_id), ("agent_run_id", agent_run_id)]:
        if value:
            query = query.where(getattr(Job, field) == value)
    async with Session() as db:
        count = await db.scalar(select(func.count()).select_from(query.subquery()))
        rows = (await db.scalars(query.order_by(Job.created_at.desc()).offset((max(page, 1) - 1) * limit).limit(limit))).all()
    return {"total": count, "items": [job_view(j) for j in rows]}


@app.get("/admin/jobs/{jid}")
async def detail(jid: str, actor=Depends(admin)):
    async with Session() as db:
        j = await db.get(Job, jid)
        if not j or j.deleted_at:
            raise HTTPException(404)
    # Payload deliberately excluded: reference Base64 and user prompts are private data.
    return {**job_view(j), "result": j.result, "attempts": j.attempts}


@app.post("/admin/jobs/{jid}/recover")
async def recover(jid: str, actor=Depends(admin)):
    async with Session.begin() as db:
        j = await db.get(Job, jid, with_for_update=True)
        if not j or j.deleted_at:
            raise HTTPException(404)
        if j.status != "recoverable" or not j.provider_id:
            raise HTTPException(409, "Only existing provider tasks can resume; this operation never submits generation")
        j.status, j.error = "queued", None
        audit(db, actor, "job.recover", jid, {"provider_id": j.provider_id})
    return {"ok": True}


@app.get("/admin/overview")
async def overview(actor=Depends(admin)):
    async with Session() as db:
        rows = (
            await db.execute(select(Job.status, Job.origin, func.count()).where(Job.deleted_at.is_(None)).group_by(Job.status, Job.origin))
        ).all()
    return {
        "counts": [{"status": s, "origin": o, "count": c} for s, o, c in rows],
        "billing_note": "Raw provider usage; missing monetary price is not free usage",
    }


@app.get("/admin/audits")
async def audits(actor=Depends(admin)):
    async with Session() as db:
        rows = (await db.scalars(select(Audit).where(Audit.deleted_at.is_(None)).order_by(Audit.created_at.desc()).limit(100))).all()
    return [
        {"id": r.id, "actor": r.actor, "action": r.action, "target": r.target, "detail": r.detail, "created_at": r.created_at.isoformat()}
        for r in rows
    ]


@app.get("/health")
async def health():
    async with Session() as db:
        await db.execute(select(Model.id).limit(1))
    return {"ok": True}


app.include_router(router_for(admin))


app.include_router(channel_router_for(admin))


app.include_router(routes_router_for(admin))
