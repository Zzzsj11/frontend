"""Independent, duplicated financial contract. Amounts are decimal points (1 point = CNY 0.01)."""

import uuid
from datetime import timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import func, select, text

from .db import Client, Job, Ledger, PricingRule, User, now

UNIT = Decimal("0.000001")
ZERO = Decimal(0)


def amount(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or abs(result) > Decimal("1000000000000"):
            raise ValueError()
        return result.quantize(UNIT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise HTTPException(422, "Invalid decimal points") from None


async def lock(db):
    if db.info.get("credit_locked"):
        return
    if db.bind.dialect.name == "postgresql":
        await db.execute(text("SELECT pg_advisory_xact_lock(739215)"))
    else:
        await db.execute(text("BEGIN IMMEDIATE"))
    db.info["credit_locked"] = True


def month():
    return now().astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m")


def entry(db, c, kind, points, operation, actor, reason, job_id=None, evidence=None):
    row = Ledger(
        id=uuid.uuid4().hex,
        client_id=c.id,
        user_id=c.user_id,
        job_id=job_id,
        operation_id=operation,
        kind=kind,
        points=amount(points),
        monthly_after=amount(c.monthly_balance),
        extra_after=amount(c.extra_balance),
        actor=actor,
        reason=reason,
        evidence=evidence or {},
    )
    db.add(row)
    return row


async def reset(db, c):
    current = month()
    if c.billing_month == current:
        return
    previous = amount(c.monthly_balance)
    c.monthly_balance = amount(c.monthly_points)
    c.billing_month = current
    entry(
        db,
        c,
        "monthly_reset",
        c.monthly_balance - previous,
        "month:" + current,
        "system",
        "北京时间自然月额度重置；未用月额度不结转，临时余额及欠费保留",
        evidence={"expired_points": str(previous), "granted_points": str(c.monthly_points), "month": current},
    )
    await db.flush()


async def held(db, cid):
    return amount(await db.scalar(select(func.coalesce(func.sum(Job.reserved_points), 0)).where(Job.client_id == cid)) or 0)


async def monthly_spent(db, *, user_id=None, client_id=None):
    start = (
        now().astimezone(timezone(timedelta(hours=8))).replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    )
    query = select(func.coalesce(-func.sum(Ledger.points), 0)).where(
        Ledger.kind.in_(["task_charge", "reconciliation"]),
        Ledger.created_at >= start,
    )
    query = query.where(Ledger.user_id == user_id) if user_id else query.where(Ledger.client_id == client_id)
    return amount(max(ZERO, amount(await db.scalar(query) or 0)))


async def user_account(db, user):
    # Include reservations and charges from disabled/deleted keys: retiring a key cannot free spent credit.
    reserved = amount(
        await db.scalar(
            select(func.coalesce(func.sum(Job.reserved_points), 0)).where(
                Job.client_id.in_(select(Client.id).where(Client.user_id == user.id)),
            )
        )
        or 0
    )
    spent = await monthly_spent(db, user_id=user.id)
    count, allocated = (
        await db.execute(
            select(func.count(), func.coalesce(func.sum(Client.monthly_points), 0)).where(
                Client.user_id == user.id,
                Client.deleted_at.is_(None),
            )
        )
    ).one()
    return {
        "monthly_points": str(amount(user.monthly_points)),
        "spent_points": str(spent),
        "reserved_points": str(reserved),
        "available_points": str(amount(max(ZERO, amount(user.monthly_points) - spent - reserved))),
        "allocated_points": str(amount(allocated)),
        "key_count": count,
        "key_limit": 10,
        "billing_month": month(),
    }


async def ensure_key_slot(db, user_id):
    count = await db.scalar(select(func.count()).select_from(Client).where(Client.user_id == user_id, Client.deleted_at.is_(None)))
    if count >= 10:
        raise HTTPException(409, "每个账号最多绑定 10 个 Key，请先删除不再使用的 Key")


async def configure_quota(db, c, points, actor):
    if not c.user_id:
        c.billing_enabled = True
        c.monthly_points = amount(points)
        await reset(db, c)
        return
    await reset(db, c)
    previous = amount(c.monthly_points)
    c.billing_enabled = True
    c.monthly_points = amount(points)
    if c.user_id:
        # Adjust allowance by the difference; never reset this month's spending or reservations.
        c.monthly_balance = amount(c.monthly_balance) + c.monthly_points - previous
        entry(
            db,
            c,
            "quota_adjust",
            c.monthly_points - previous,
            "quota:" + uuid.uuid4().hex,
            actor,
            "调整 Key 月上限，保留本月已消费积分",
            evidence={"previous": str(previous), "monthly_points": str(c.monthly_points)},
        )
    await db.flush()


async def account(db, c):
    await reset(db, c)
    reserved = await held(db, c.id)
    available = amount(c.monthly_balance) + amount(c.extra_balance) - reserved
    spent = await monthly_spent(db, client_id=c.id)
    if c.user_id:
        user = await db.get(User, c.user_id)
        owner = await user_account(db, user)
        available = min(available, amount(c.monthly_points) - spent - reserved, amount(owner["available_points"]))
    return {
        "spent_points": str(spent),
        "id": c.id,
        "name": c.name,
        "user_id": c.user_id,
        "key_prefix": c.key_prefix,
        "enabled": c.enabled,
        "billing_enabled": c.billing_enabled,
        "monthly_points": str(c.monthly_points),
        "monthly_balance": str(c.monthly_balance),
        "extra_balance": str(c.extra_balance),
        "reserved_points": str(reserved),
        "available_points": str(amount(max(ZERO, available))),
        "billing_month": c.billing_month,
    }


async def rules(db, mid):
    rows = (
        await db.scalars(
            select(PricingRule)
            .where(PricingRule.model_id == mid, PricingRule.deleted_at.is_(None))
            .order_by(PricingRule.created_at.desc(), PricingRule.id.desc())
        )
    ).all()
    return [{"id": row.id, **row.config} for row in rows]


def dimensions(model, payload):
    meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    params = payload.get("parameters") if isinstance(payload.get("parameters"), dict) else {}
    inp = payload.get("input") or {}
    if not isinstance(inp, dict):
        inp = {}
    refs = payload.get("images") or payload.get("image") or payload.get("image_url") or inp.get("image") or inp.get("images")
    content = payload.get("content") or []
    if isinstance(content, list):
        refs = refs or [c for c in content if isinstance(c, dict) and c.get("type") in {"image_url", "image"}]
    media = inp.get("media") or []
    if isinstance(media, list):
        refs = refs or media
    roles = {
        c.get("role") or c.get("type")
        for c in (content if isinstance(content, list) else []) + (media if isinstance(media, list) else [])
        if isinstance(c, dict)
    }
    if model.kind == "image":
        refs = payload.get("image") or payload.get("images") or payload.get("image_urls") or payload.get("reference_images")
    task = (
        (meta.get("task") or ("reference_to_video" if refs else "text_to_video"))
        if model.provider_model == "gemini-omni-flash-preview"
        else None
    )
    if not task and model.kind == "video":
        if "last_frame" in roles or payload.get("image_tail"):
            task = "first_last_frame"
        elif "reference_image" in roles or "reference_video" in roles or "reference_audio" in roles or payload.get("reference_images"):
            task = "reference_to_video"
        elif "first_frame" in roles:
            task = "image_to_video"
        elif model.provider_model.startswith("veo-") and refs:
            task = "reference_to_video"
    if not task:
        task = (
            "chat"
            if model.kind == "chat"
            else "image_to_image"
            if model.kind == "image" and refs
            else "text_to_image"
            if model.kind == "image"
            else "first_last_frame"
            if payload.get("image_tail")
            else "image_to_video"
            if refs
            else "text_to_video"
        )
    resolution = payload.get("resolution") or params.get("resolution") or meta.get("resolution") or payload.get("size") or ""
    if model.provider_model == "gemini-omni-flash-preview":
        resolution = "720p"
    if model.protocol == "kling":
        resolution = {"std": "720p", "pro": "1080p", "4k": "4k"}.get(payload.get("mode", "pro"), "")
    return {
        "mode": task,
        "resolution": str(resolution).lower(),
        "quality": str(payload.get("quality", "")),
        "sound": str(payload.get("sound", payload.get("generate_audio", params.get("audio", "")))).lower(),
    }


async def rule(db, mid, context=None):
    candidates = await rules(db, mid)
    context = context or {}
    candidates = [r for r in candidates if all(not v or v == "*" or context.get(k) == v for k, v in r.get("selector", {}).items())]
    candidates.sort(key=lambda r: sum(bool(v and v != "*") for v in r.get("selector", {}).values()), reverse=True)
    return candidates[0] if candidates else None


def default_rule(model):
    metric = (
        "输入 / 输出 / 缓存 Token"
        if model.kind == "chat"
        else "图片数量、尺寸、质量及图片 Token"
        if model.kind == "image"
        else "输出 Token"
        if model.protocol == "seedance"
        else "视频秒数、清晰度及生成模式"
    )
    return {
        "confirmed": False,
        "description": f"计价维度：{metric}。渠道返回实际用量 × 对应人民币费率 × 100 = 积分；待配置账户适用费率。",
        "source": "待管理员核实渠道账单/合同",
        "reserve_points": "0",
        "rates": [],
        "actual_cny_path": "",
    }


async def reserve(db, client, job, model):
    route_pricing = (job.routing_snapshot or {}).get("pricing") or {}
    pricing = (
        (route_pricing if route_pricing.get("rates") or route_pricing.get("actual_cny_path") else None)
        or await rule(db, model.id, dimensions(model, job.payload))
        or default_rule(model)
    )
    job.pricing_snapshot = {**pricing, "matched_dimensions": dimensions(model, job.payload)}
    if not client.billing_enabled:  # Legacy system keys remain opt-in; every newly created key defaults to a metered wallet.
        return
    c = await db.get(Client, client.id, populate_existing=True)
    await reset(db, c)
    if not pricing.get("confirmed") or amount(pricing.get("reserve_points", 0)) <= 0:
        raise HTTPException(503, "Model billing not verified; administrator must publish a verified rule and reservation limit")
    points = amount(pricing["reserve_points"])
    available = amount(c.monthly_balance) + amount(c.extra_balance) - await held(db, c.id)
    if available < points:
        raise HTTPException(402, "Insufficient points after active task reservations")
    if c.user_id:
        user = await db.get(User, c.user_id, populate_existing=True)
        if not user or user.deleted_at or not user.enabled:
            raise HTTPException(403, "账号不可用")
        if amount(c.monthly_points) - await monthly_spent(db, client_id=c.id) - await held(db, c.id) < points:
            raise HTTPException(402, "该 Key 的本月积分额度不足")
        owner = await user_account(db, user)
        if amount(owner["available_points"]) < points:
            raise HTTPException(402, "账号本月总积分额度不足")
    job.reserved_points = points
    job.billing_status = "reserved"


def money_from_response(job):
    config = job.pricing_snapshot or {}
    path = config.get("actual_cny_path", "")
    if not config.get("confirmed") or not path:
        return None
    # Explicit administrator-verified path only. Never assume a generic 'cost' is CNY.
    value = {"response": job.provider_response or {}, "usage": job.usage or {}, "result": job.result or {}}
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    if value is None or isinstance(value, bool):
        return None
    try:
        raw = Decimal(str(value))
        if not raw.is_finite() or raw < 0:
            return None
        return amount(raw * 100)
    except (InvalidOperation, HTTPException):
        return None


async def settle(db, job, points, actor, source, operation, evidence):
    c = await db.get(Client, job.client_id, populate_existing=True)
    existing = await db.scalar(select(Ledger).where(Ledger.client_id == c.id, Ledger.operation_id == operation))
    if existing:
        if (
            existing.job_id != job.id
            or existing.evidence.get("charged_points") != str(amount(points))
            or existing.reason != source
            or any(existing.evidence.get(k) != v for k, v in evidence.items())
        ):
            raise HTTPException(409, "Billing operation already used with different data")
        return
    await reset(db, c)
    total = amount(points)
    if total < 0:
        raise HTTPException(422, "Actual charge cannot be negative")
    previously_charged = job.charged_points is not None
    previous = amount(job.charged_points or 0)
    delta = total - previous
    # Do not erase real supplier debt if a reservation was too small; block subsequent submissions instead.
    if delta >= 0:
        monthly = min(max(amount(c.monthly_balance), ZERO), delta)
        c.monthly_balance = amount(c.monthly_balance) - monthly
        c.extra_balance = amount(c.extra_balance) - (delta - monthly)
    else:
        c.extra_balance = amount(c.extra_balance) - delta
    job.charged_points, job.reserved_points, job.billing_status = total, ZERO, "settled"
    entry(
        db,
        c,
        "reconciliation" if previously_charged else "task_charge",
        -delta,
        operation,
        actor,
        source,
        job.id,
        {**evidence, "charged_points": str(total), "previous_points": str(previous)},
    )


def measured_points(job):
    config = job.pricing_snapshot or {}
    if not config.get("confirmed") or not config.get("rates"):
        return None
    total = Decimal(0)
    breakdown = []
    for rate in config["rates"]:
        value = job.usage or {}
        for part in rate["path"].split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is None:
            if rate.get("optional", False):
                value = 0
            else:
                return None
        try:
            quantity = Decimal(str(value))
            # Cache-read tokens may be included in prompt_tokens. Explicit subtraction avoids double charging.
            for subtract in rate.get("subtract", []):
                other = job.usage or {}
                for part in subtract.split("."):
                    other = other.get(part) if isinstance(other, dict) else None
                if other is None:
                    return None
                quantity -= Decimal(str(other))
            if not quantity.is_finite() or quantity < 0:
                return None
            price = Decimal(str(rate["cny"]))
            unit = Decimal(str(rate["unit"]))
            charge = quantity / unit * price * 100
            total += charge
            breakdown.append(
                {
                    "label": rate["label"],
                    "path": rate["path"],
                    "quantity": str(quantity),
                    "unit": str(unit),
                    "cny_per_unit": str(price),
                    "points": str(charge),
                }
            )
        except (InvalidOperation, ZeroDivisionError, TypeError):
            return None
    return amount(total), breakdown


async def automatic(db, job):
    if job.status not in {"succeeded", "failed", "recoverable", "manual_review"} or job.billing_status in {"settled", "usage_priced"}:
        return
    points = money_from_response(job)
    if points is not None:
        await settle(
            db,
            job,
            points,
            "provider",
            "渠道逐请求实付金额 × 100",
            "auto:" + job.id,
            {
                "path": job.pricing_snapshot["actual_cny_path"],
                "provider_task_id": job.provider_id,
                "rule_id": job.pricing_snapshot.get("id"),
            },
        )
    else:
        measured = measured_points(job) if job.status in {"succeeded", "failed"} else None
        if measured is not None:
            points, breakdown = measured
            await settle(
                db,
                job,
                points,
                "system",
                "渠道实际用量 × 费率（估算金额）",
                "usage:" + job.id,
                {"rule_id": job.pricing_snapshot.get("id"), "breakdown": breakdown, "basis": "usage_priced"},
            )
            job.billing_status = "usage_priced"
        else:
            job.billing_status = "pending_reconciliation"


def job_bill(job):
    return {
        "status": job.billing_status,
        "points": str(job.charged_points) if job.charged_points is not None else None,
        "cny": str(amount(job.charged_points) / 100) if job.charged_points is not None else None,
        "reserved_points": str(job.reserved_points),
        "rule": job.pricing_snapshot,
        "note": "1积分 = ¥0.01；预占不是扣费；待核账不等于免费",
    }


def ledger_view(row):
    return {
        k: str(getattr(row, k)) if k in {"points", "monthly_after", "extra_after"} else getattr(row, k)
        for k in (
            "id",
            "client_id",
            "user_id",
            "job_id",
            "kind",
            "points",
            "monthly_after",
            "extra_after",
            "actor",
            "reason",
            "evidence",
            "created_at",
        )
    }
