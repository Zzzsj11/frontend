"""管理端只有余额快照和兑换配置，不持有供应商凭据。"""

import uuid
from datetime import timedelta, timezone
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, select

from .db import Audit, ChannelAccount, Session, now

AUTOMATIC = {"yinghe", "yseeai", "toapis"}


def text(value):
    return format(Decimal(str(value)), "f") if value is not None else None


def view(row):
    snapshot = row.snapshot or {}
    balance = snapshot.get("balance")
    rate = Decimal(1) if row.currency == "CNY" else Decimal(str(row.usd_cny)) if row.currency == "USD" else None
    if row.currency == "POINTS" and row.points_per_unit:
        rate = (Decimal(str(row.usd_cny)) if row.points_currency == "USD" else Decimal(1)) / Decimal(str(row.points_per_unit))
    currency = row.currency
    if row.channel == "toapis":
        # 供应商积分与平台用户积分是不同单位；旧美元快照不可当作积分。
        currency = "POINTS"
        balance = snapshot.get("remain_credits")
        rate = Decimal("35") / Decimal("1000")
    queried = row.queried_at.replace(tzinfo=timezone.utc) if row.queried_at else None
    return {
        "id": row.id,
        "channel": row.channel,
        "name": row.name,
        "currency": currency,
        "usd_cny": text(row.usd_cny),
        "points_per_unit": text(row.points_per_unit),
        "points_currency": row.points_currency,
        "balance": balance,
        "cny_balance": text(Decimal(balance) * rate) if balance is not None and rate is not None else None,
        "key_masked": snapshot.get("key_masked"),
        "quota": snapshot.get("quota"),
        "quota_error": snapshot.get("quota_error"),
        "source": snapshot.get("source"),
        "queried_at": row.queried_at,
        "attempted_at": row.attempted_at,
        "stale": bool(queried and (now() - queried).total_seconds() > 600) or bool(row.error),
        "error": row.error,
        "automatic": row.channel in AUTOMATIC,
        "conversion_pending": rate is None,
    }


class Policy(BaseModel):
    currency: Literal["CNY", "USD", "POINTS", "UNKNOWN"]
    usd_cny: Decimal = Field(default=Decimal("6.9"), gt=0, le=10000, decimal_places=8)
    points_per_unit: Decimal | None = Field(default=None, gt=0, le=1000000000000, decimal_places=8)
    points_currency: Literal["CNY", "USD"] = "CNY"


class ManualBalance(BaseModel):
    balance: Decimal = Field(ge=-1000000000000, le=1000000000000, decimal_places=8)
    note: str = Field(min_length=1, max_length=500)


def router_for(admin):
    router = APIRouter(prefix="/admin/channel-balances", dependencies=[Depends(admin)])

    async def get(db, account_id):
        row = await db.get(ChannelAccount, account_id, with_for_update=True)
        if not row or row.deleted_at:
            raise HTTPException(404, "渠道账户不存在")
        return row

    def audit(db, actor, action, row, detail):
        db.add(Audit(id=uuid.uuid4().hex, actor=actor, action=action, target=row.id, detail=detail))

    @router.get("")
    async def listing():
        async with Session() as db:
            rows = (
                await db.scalars(
                    select(ChannelAccount)
                    .where(ChannelAccount.deleted_at.is_(None))
                    .order_by(
                        case({"yinghe": 0, "yseeai": 1, "runninghub": 2}, value=ChannelAccount.channel, else_=3),
                        ChannelAccount.id,
                    )
                )
            ).all()
            return [view(row) for row in rows]

    @router.patch("/{account_id}")
    async def policy(account_id: str, body: Policy, actor=Depends(admin)):
        async with Session.begin() as db:
            row = await get(db, account_id)
            fixed = {"yinghe": "CNY", "yseeai": "USD", "toapis": "POINTS"}.get(row.channel)
            if fixed and body.currency != fixed:
                raise HTTPException(422, "该自动查询渠道的原币种已确认，不能改写")
            before = {k: str(getattr(row, k)) for k in Policy.model_fields}
            if row.currency != body.currency:
                row.snapshot, row.queried_at = {}, None
            for key, value in body.model_dump().items():
                setattr(row, key, value)
            audit(db, actor, "channel.policy", row, {"before": before, "after": body.model_dump(mode="json")})
            return view(row)

    @router.post("/{account_id}/refresh", status_code=202)
    async def refresh(account_id: str, actor=Depends(admin)):
        async with Session.begin() as db:
            row = await get(db, account_id)
            if row.channel not in AUTOMATIC:
                raise HTTPException(409, "该渠道尚无已验证查询接口，请录入余额快照")
            earliest = row.attempted_at.replace(tzinfo=timezone.utc) + timedelta(seconds=60) if row.attempted_at else now()
            row.next_check_at = max(now(), earliest)
            audit(db, actor, "channel.refresh", row, {})
            return {"scheduled_at": row.next_check_at}

    @router.post("/{account_id}/manual")
    async def manual(account_id: str, body: ManualBalance, actor=Depends(admin)):
        async with Session.begin() as db:
            row = await get(db, account_id)
            if row.channel in AUTOMATIC:
                raise HTTPException(409, "自动查询渠道不能用人工余额覆盖")
            if row.currency == "UNKNOWN":
                raise HTTPException(422, "请先确认余额币种")
            audit(
                db,
                actor,
                "channel.manual_balance",
                row,
                {"before": row.snapshot, "after": body.model_dump(mode="json"), "currency": row.currency},
            )
            row.snapshot = {"balance": text(body.balance), "source": "manual", "note": body.note}
            row.queried_at, row.error = now(), None
            return view(row)

    return router
