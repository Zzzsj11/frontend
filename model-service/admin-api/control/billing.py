"""Control-plane operations only; no dependency on gateway code or provider credentials."""

import asyncio
import re
import secrets
import uuid
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .credits import (
    account,
    amount,
    configure_quota,
    default_rule,
    entry,
    held,
    ledger_view,
    lock,
    reset,
    rules,
    settle,
    user_account,
)
from .db import Audit, Client, Job, Ledger, Model, PricingRule, Session, User, now
from .passwords import password_hash


def router_for(admin):
    router = APIRouter(prefix="/admin", dependencies=[Depends(admin)])

    @router.get("/users")
    async def users():
        async with Session.begin() as db:
            await lock(db)
            rows = (await db.scalars(select(User).where(User.deleted_at.is_(None)).order_by(User.created_at.desc()).limit(1000))).all()
            return [
                {"id": u.id, "username": u.username, "enabled": u.enabled, "created_at": u.created_at, "quota": await user_account(db, u)}
                for u in rows
            ]

    @router.post("/users", status_code=201)
    async def create_user(body: UserCreate, actor=Depends(admin)):
        password = body.initial_password or secrets.token_urlsafe(18) + "A1"
        hashed = await asyncio.to_thread(password_hash, password)
        async with Session.begin() as db:
            user = User(id="user-" + uuid.uuid4().hex, username=body.username, password_hash=hashed, monthly_points=body.monthly_points)
            db.add(user)
            try:
                await db.flush()
            except IntegrityError:
                raise HTTPException(409, "该企业邮箱账号已存在") from None
            db.add(
                Audit(
                    id=uuid.uuid4().hex,
                    actor=actor,
                    action="user.create",
                    target=user.id,
                    detail={"username": user.username, "monthly_points": str(body.monthly_points)},
                )
            )
        return {"id": user.id, "username": user.username, "initial_password": password}

    @router.post("/users/{uid}/quota")
    async def user_quota(uid: str, body: Quota, actor=Depends(admin)):
        async with Session.begin() as db:
            await lock(db)
            user = await db.get(User, uid)
            if not user or user.deleted_at:
                raise HTTPException(404, "账号不存在")
            previous = str(user.monthly_points)
            user.monthly_points = amount(body.points)
            db.add(
                Audit(
                    id=uuid.uuid4().hex,
                    actor=actor,
                    action="user.quota",
                    target=uid,
                    detail={"previous": previous, "monthly_points": str(body.points), "effect": "immediate"},
                )
            )
            return await user_account(db, user)

    @router.get("/wallets")
    async def wallets():
        async with Session.begin() as db:
            await lock(db)
            rows = (await db.scalars(select(Client).where(Client.deleted_at.is_(None)))).all()
            return [await account(db, c) for c in rows]

    @router.post("/clients/{cid}/bind")
    async def bind(cid: str, body: Binding, actor=Depends(admin)):
        raise HTTPException(403, "用户 Key 由账号持有者创建并自动归属，不能转移绑定")

    @router.post("/clients/{cid}/quota")
    async def quota(cid: str, body: Quota, actor=Depends(admin)):
        async with Session.begin() as db:
            await lock(db)
            c = await db.get(Client, cid)
            if not c or c.deleted_at:
                raise HTTPException(404)
            if c.user_id:
                raise HTTPException(403, "用户 Key 月上限由账号持有者分配")
            # Initialize an unconfigured key in the current month at its first configured allowance.
            previous = str(c.monthly_points)
            await configure_quota(db, c, body.points, actor)
            db.add(
                Audit(
                    id=uuid.uuid4().hex,
                    actor=actor,
                    action="quota.configure",
                    target=cid,
                    detail={
                        "previous": previous,
                        "monthly_points": str(c.monthly_points),
                        "effect": "immediate" if c.user_id else "next_reset",
                    },
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


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    monthly_points: Decimal = Field(default=0, ge=0, le=1000000000, decimal_places=6)
    initial_password: str | None = Field(default=None, min_length=8, max_length=128)

    @field_validator("username")
    @classmethod
    def email(cls, value):
        value = value.lower()
        if not re.fullmatch(r"[a-z0-9_-]+(?:\.[a-z0-9_-]+)*@star-net\.cn", value):
            raise ValueError("仅支持 @star-net.cn 企业邮箱")
        return value

    @field_validator("initial_password")
    @classmethod
    def password(cls, value):
        if value is not None and (not re.search(r"[A-Za-z]", value) or not re.search(r"[0-9]", value)):
            raise ValueError("密码至少 8 位，且包含字母和数字")
        return value
