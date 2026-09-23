"""Control-plane operations only; no dependency on gateway code or provider credentials."""

import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from .credits import account, amount, default_rule, entry, held, ledger_view, lock, reset, rules, settle
from .db import Audit, Client, Job, Ledger, Model, PricingRule, Session, User, now


def router_for(admin):
    router = APIRouter(prefix="/admin", dependencies=[Depends(admin)])

    @router.get("/users")
    async def users():
        async with Session() as db:
            rows = (await db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.created_at.desc()).limit(1000))).all()
        return [{"id": u.id, "username": u.username, "enabled": u.enabled, "created_at": u.created_at} for u in rows]

    @router.get("/wallets")
    async def wallets():
        async with Session.begin() as db:
            await lock(db)
            rows = (await db.scalars(select(Client).where(Client.deleted_at.is_(None)))).all()
            return [await account(db, c) for c in rows]

    @router.post("/clients/{cid}/bind")
    async def bind(cid: str, body: Binding, actor=Depends(admin)):
        async with Session.begin() as db:
            await lock(db)
            c = await db.get(Client, cid)
            user = await db.get(User, body.user_id)
            if not c or c.deleted_at or not user or user.deleted_at or not user.enabled:
                raise HTTPException(404)
            if c.user_id == user.id:
                return {"ok": True}
            if c.user_id or await db.scalar(select(func.count()).select_from(Job).where(Job.client_id == cid)):
                raise HTTPException(409, "Only unused, unbound keys can be bound; ownership cannot be transferred")
            c.user_id = user.id
            c.billing_enabled = True
            # Associate the unused key's previous balance entries with its first and permanent owner.
            records = (await db.scalars(select(Ledger).where(Ledger.client_id == cid))).all()
            for row in records:
                row.user_id = user.id
            db.add(Audit(id=uuid.uuid4().hex, actor=actor, action="client.bind", target=cid, detail={"user_id": user.id}))
        return {"ok": True}

    @router.post("/clients/{cid}/quota")
    async def quota(cid: str, body: Quota, actor=Depends(admin)):
        async with Session.begin() as db:
            await lock(db)
            c = await db.get(Client, cid)
            if not c or c.deleted_at:
                raise HTTPException(404)
            # Initialize an unconfigured key in the current month at its first configured allowance.
            previous = str(c.monthly_points)
            c.billing_enabled = True
            c.monthly_points = amount(body.points)
            await reset(db, c)
            db.add(
                Audit(
                    id=uuid.uuid4().hex,
                    actor=actor,
                    action="quota.configure",
                    target=cid,
                    detail={"previous": previous, "monthly_points": str(c.monthly_points), "effect": "next_reset"},
                )
            )
            return await account(db, c)

    @router.post("/clients/{cid}/adjust")
    async def adjust(cid: str, body: Adjustment, actor=Depends(admin)):
        async with Session.begin() as db:
            await lock(db)
            c = await db.get(Client, cid)
            if not c or c.deleted_at:
                raise HTTPException(404)
            points = amount(body.points)
            if not points:
                raise HTTPException(422, "Adjustment must be nonzero")
            existing = await db.scalar(select(Ledger).where(Ledger.client_id == cid, Ledger.operation_id == "adjust:" + body.operation_id))
            if existing:
                if amount(existing.points) != points or existing.reason != body.reason:
                    raise HTTPException(409, "Operation ID conflict")
                return ledger_view(existing)
            await reset(db, c)
            if points < 0 and amount(c.monthly_balance) + amount(c.extra_balance) - await held(db, cid) + points < 0:
                raise HTTPException(409, "Deduction would consume reserved points or overdraw the key")
            c.billing_enabled = True
            c.extra_balance = amount(c.extra_balance) + points
            row = entry(db, c, "manual_credit" if points > 0 else "manual_debit", points, "adjust:" + body.operation_id, actor, body.reason)
            await db.flush()
            return ledger_view(row)

    @router.get("/ledger")
    async def ledger(client_id: str = "", kind: str = "", page: int = 1):
        query = select(Ledger).where(Ledger.deleted_at.is_(None))
        if client_id:
            query = query.where(Ledger.client_id == client_id)
        if kind:
            query = query.where(Ledger.kind == kind)
        async with Session() as db:
            total = await db.scalar(select(func.count()).select_from(query.subquery()))
            rows = (await db.scalars(query.order_by(Ledger.created_at.desc()).offset((max(1, page) - 1) * 50).limit(50))).all()
        return {"total": total, "items": [ledger_view(r) for r in rows]}

    @router.get("/pricing")
    async def pricing():
        async with Session() as db:
            models = (await db.scalars(select(Model).where(Model.deleted_at.is_(None)).order_by(Model.id))).all()
            return [{"model": m.id, "rules": await rules(db, m.id) or [default_rule(m)]} for m in models]

    @router.post("/pricing/{mid}")
    async def publish(mid: str, body: PriceConfig, actor=Depends(admin)):
        config = body.model_dump(mode="json")
        config["selector"] = {k: v for k, v in config["selector"].items() if v and v != "*"}
        if config["confirmed"] and (not config["rates"] and not config["actual_cny_path"]):
            raise HTTPException(422, "At least one usage rate or verified CNY field is required")
        if config["confirmed"] and amount(config["reserve_points"]) <= 0:
            raise HTTPException(422, "Verified rules require positive reservation points")
        async with Session.begin() as db:
            await lock(db)
            model = await db.get(Model, mid)
            if not model or model.deleted_at:
                raise HTTPException(404)
            prior = (await db.scalars(select(PricingRule).where(PricingRule.model_id == mid, PricingRule.deleted_at.is_(None)))).all()
            for old in prior:
                if old.config.get("selector", {}) == config["selector"]:
                    old.deleted_at = now()
                else:
                    # Reject equally-specific overlapping selectors: billing must be deterministic.
                    a, b = old.config.get("selector", {}), config["selector"]
                    if len(a) == len(b) and all(k not in b or b[k] == v for k, v in a.items()):
                        raise HTTPException(409, "Rule overlaps another rule at the same priority; refine its selectors")
            row = PricingRule(id="price-" + uuid.uuid4().hex, model_id=mid, config=config, actor=actor)
            db.add(row)
            db.add(Audit(id=uuid.uuid4().hex, actor=actor, action="pricing.publish", target=mid, detail={"rule_id": row.id, **config}))
        return {"id": row.id, **config}

    @router.post("/jobs/{jid}/reconcile")
    async def reconcile(jid: str, body: Reconcile, actor=Depends(admin)):
        async with Session.begin() as db:
            await lock(db)
            j = await db.get(Job, jid)
            if not j:
                raise HTTPException(404)
            if j.status not in {"succeeded", "failed", "manual_review", "recoverable"}:
                raise HTTPException(409, "Wait for provider completion before reconciliation")
            await settle(
                db,
                j,
                Decimal(str(body.actual_cny)) * 100,
                actor,
                body.reason,
                "statement:" + body.operation_id,
                {"statement_reference": body.reference, "actual_cny": str(body.actual_cny)},
            )
        return {"ok": True}

    return router


class Binding(BaseModel):
    user_id: str


class Quota(BaseModel):
    points: Decimal = Field(ge=0, le=1000000000, decimal_places=6)


class Adjustment(BaseModel):
    points: Decimal = Field(ge=-1000000000, le=1000000000, decimal_places=6)
    reason: str = Field(min_length=3, max_length=500)
    operation_id: str = Field(min_length=8, max_length=160)


class Selector(BaseModel):
    mode: Literal[
        "",
        "*",
        "chat",
        "text_to_image",
        "image_to_image",
        "text_to_video",
        "image_to_video",
        "reference_to_video",
        "first_last_frame",
        "edit",
    ] = ""
    resolution: str = Field(default="", max_length=30, pattern=r"^[a-z0-9*x_-]*$")
    quality: str = Field(default="", max_length=30)
    sound: str = Field(default="", max_length=20)


class Rate(BaseModel):
    label: str = Field(min_length=1, max_length=100)
    path: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.]{0,150}$")
    unit: Decimal = Field(gt=0, le=1000000000)
    cny: Decimal = Field(ge=0, le=1000000, decimal_places=10)
    optional: bool = False
    subtract: list[str] = Field(default_factory=list, max_length=10)


class PriceConfig(BaseModel):
    selector: Selector = Field(default_factory=Selector)
    description: str = Field(min_length=5, max_length=2000)
    source: str = Field(min_length=3, max_length=1000)
    confirmed: bool = False
    reserve_points: Decimal = Field(ge=0, le=1000000000, decimal_places=6)
    rates: list[Rate] = Field(default_factory=list, max_length=20)
    actual_cny_path: str = Field(default="", pattern=r"^(?:(?:usage|response|result)\.[A-Za-z0-9_.]{1,150})?$")


class Reconcile(BaseModel):
    actual_cny: Decimal = Field(ge=0, le=10000000, decimal_places=8)
    operation_id: str = Field(min_length=8, max_length=160)
    reason: str = Field(min_length=3, max_length=500)
    reference: str = Field(min_length=3, max_length=500)
