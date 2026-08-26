from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GenerationJobModel, TokenUsageModel, VideoBillingRecordModel, VideoPricingRuleModel

TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}
ZERO = Decimal("0")
YINGHE_SD20_DISCOUNT_RATE = Decimal("0.83")
PPIO_SD20_DISCOUNT_RATE = Decimal("0.80")
PPIO_H3_DISCOUNT_RATE = Decimal("0.85")


def video_discount_rate(*, model: str, provider: str) -> Decimal:
    if model == "doubao-seedance-2.0" and provider == "yinghe":
        return YINGHE_SD20_DISCOUNT_RATE
    if model == "doubao-seedance-2.0-ppio" and provider == "ppio":
        return PPIO_SD20_DISCOUNT_RATE
    if model == "minimax-h3-ppio" and provider == "ppio":
        return PPIO_H3_DISCOUNT_RATE
    return Decimal("1")


def video_discount_label(*, model: str, provider: str) -> str:
    rate = video_discount_rate(model=model, provider=provider)
    if rate == YINGHE_SD20_DISCOUNT_RATE:
        return "英和 83 折"
    if rate == PPIO_SD20_DISCOUNT_RATE:
        return "PPIO 8 折"
    if rate == PPIO_H3_DISCOUNT_RATE:
        return "PPIO 85 折"
    return ""


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except (ValueError, TypeError):
        return ZERO


def _usage_metrics(raw: dict[str, Any]) -> dict[str, Any]:
    nested = raw.get("rawUsage")
    return nested if isinstance(nested, dict) else raw


def _model_provider(job: GenerationJobModel, usage: TokenUsageModel | None) -> tuple[str, str]:
    request = job.request or {}
    result = job.result or {}
    model = str((usage.model if usage else "") or result.get("model") or request.get("model") or "")
    provider = str((usage.provider if usage else "") or result.get("provider") or job.provider or request.get("_provider") or "")
    if model == "minimax-h3" and provider == "yinghe":
        provider = "yinghe-h3"
    return model, provider


async def _price_rule(db: AsyncSession, *, model: str, provider: str, resolution: str, at: datetime) -> VideoPricingRuleModel | None:
    rules = list(
        (
            await db.execute(
                select(VideoPricingRuleModel)
                .where(
                    VideoPricingRuleModel.model == model,
                    VideoPricingRuleModel.resolution == resolution,
                    VideoPricingRuleModel.status == "active",
                    VideoPricingRuleModel.deleted_at.is_(None),
                    VideoPricingRuleModel.effective_at <= at,
                )
                .order_by(VideoPricingRuleModel.effective_at.desc())
            )
        ).scalars()
    )
    return next((rule for rule in rules if (not rule.provider or rule.provider == provider) and (rule.expires_at is None or rule.expires_at > at)), None)


async def reconcile_video_job(db: AsyncSession, job: GenerationJobModel) -> VideoBillingRecordModel | None:
    # 财务事实不随项目软删除消失；否则测试清理或用户删项目会造成历史成本漏账。
    if job.kind != "video" or job.status not in TERMINAL_STATUSES:
        return None
    usage = (
        await db.execute(
            select(TokenUsageModel)
            .where(
                TokenUsageModel.generation_job_id == job.id,
            )
            .order_by(TokenUsageModel.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    raw_usage = dict(usage.raw_usage or {}) if usage else dict((job.result or {}).get("usage") or {})
    metrics = _usage_metrics(raw_usage)
    model, provider = _model_provider(job, usage)
    resolution = str((job.request or {}).get("resolution") or "720p")
    completed_at = job.finished_at or job.updated_at or job.created_at or datetime.now(timezone.utc)
    failed = job.status != "succeeded"
    billing_status = "no_usage"
    usage_type = ""
    usage_unit = ""
    quantity = ZERO
    amount = ZERO
    rule = None

    if provider == "runninghub" or model == "minimax-h3-runninghub":
        billing_status = "excluded"
        usage_type = "runninghub_coins"
        usage_unit = "RH币"
        quantity = _decimal(metrics.get("consumeCoins"))
    elif model in {"doubao-seedance-2.0", "doubao-seedance-2.0-ppio"}:
        usage_type = "completion_tokens"
        usage_unit = "Token"
        quantity = _decimal((usage.output_tokens if usage else 0) or metrics.get("completion_tokens") or metrics.get("completionTokens"))
        if quantity > 0:
            rule = await _price_rule(db, model=model, provider=provider, resolution=resolution, at=completed_at)
            billing_status = "priced" if rule else "unpriced"
    elif (model == "minimax-h3" and provider == "yinghe-h3") or (model == "minimax-h3-ppio" and provider == "ppio"):
        usage_type = "output_seconds"
        usage_unit = "秒"
        quantity = _decimal(metrics.get("output_seconds") or metrics.get("outputSeconds"))
        if quantity > 0:
            rule = await _price_rule(db, model=model, provider=provider, resolution=resolution, at=completed_at)
            billing_status = "priced" if rule else "unpriced"
    else:
        billing_status = "unpriced"

    if rule and billing_status == "priced":
        discount_rate = video_discount_rate(model=model, provider=provider)
        applied_unit_price = (_decimal(rule.unit_price) * discount_rate).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
        amount = (quantity / _decimal(rule.unit_size) * applied_unit_price).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
    else:
        applied_unit_price = ZERO

    record = (await db.execute(select(VideoBillingRecordModel).where(VideoBillingRecordModel.generation_job_id == job.id))).scalar_one_or_none()
    if record is None:
        record = VideoBillingRecordModel(id=f"vbill-{uuid.uuid4().hex}", generation_job_id=job.id)
        db.add(record)
    record.user_id = job.user_id
    record.project_id = job.project_id
    record.project_task_id = job.project_task_id
    record.storyboard_line_id = job.storyboard_line_id
    record.pricing_rule_id = rule.id if rule else None
    record.provider = provider
    record.model = model
    record.resolution = resolution
    record.generation_status = job.status
    record.is_failed = failed
    record.billing_status = billing_status
    record.usage_type = usage_type
    record.usage_quantity = quantity
    record.usage_unit = usage_unit
    record.unit_price = applied_unit_price
    record.amount = amount
    record.currency = rule.currency if rule else "CNY"
    record.raw_usage = raw_usage
    record.completed_at = completed_at
    record.deleted_at = None
    return record


async def reconcile_video_billing(db: AsyncSession, job_ids: list[str] | None = None) -> dict[str, int]:
    query = select(GenerationJobModel).where(
        GenerationJobModel.kind == "video",
        GenerationJobModel.status.in_(TERMINAL_STATUSES),
    )
    if job_ids:
        query = query.where(GenerationJobModel.id.in_(job_ids))
    jobs = list((await db.execute(query.order_by(GenerationJobModel.created_at))).scalars())
    counts = {"processed": 0, "priced": 0, "failed": 0, "excluded": 0, "unpriced": 0, "noUsage": 0}
    for job in jobs:
        record = await reconcile_video_job(db, job)
        if not record:
            continue
        counts["processed"] += 1
        if record.is_failed:
            counts["failed"] += 1
        key = {"priced": "priced", "excluded": "excluded", "unpriced": "unpriced", "no_usage": "noUsage"}[record.billing_status]
        counts[key] += 1
    await db.flush()
    return counts
