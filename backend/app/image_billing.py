"""Backfill image charges from existing platform jobs without invoking generation."""

import asyncio
import logging
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import or_, select

from .agent_attribution import attribution_context
from .all_in_one import query_task
from .database import session_factory
from .models import GenerationJobModel as Job
from .models import TokenUsageModel as Usage
from .models import utcnow
from .token_usage import add_token_usage

logger = logging.getLogger(__name__)


def settled(bill, *, allow_refund=False):
    if not isinstance(bill, dict) or bill.get("status") not in ({"settled", "refunded"} if allow_refund else {"settled"}):
        return False
    try:
        points = Decimal(str(bill.get("points")))
        return points.is_finite() and points >= 0 and (bill["status"] != "refunded" or points == 0)
    except InvalidOperation:
        return False


def eligible():
    return (
        Job.kind == "image",
        Job.provider == "all-in-one",
        or_(Job.status == "succeeded", (Job.status == "failed") & (Job.phase == "manual_review")),
        Job.provider_task_id.is_not(None),
        Job.provider_task_id != "",
    )


async def refresh_image_bill(db, job):
    task_id = job.provider_task_id
    with attribution_context(job.generation_origin, job.agent_name, job.agent_run_id, job.test_run_id):
        data = await query_task("image", task_id, user_id=job.user_id)
    bill = data.get("billing")
    if data.get("id") != task_id or not settled(bill):
        return "pending"
    # Re-check identity under lock. Manual sync and the worker may arrive together.
    job = await db.scalar(select(Job).where(Job.id == job.id, Job.provider_task_id == task_id, *eligible()).with_for_update().execution_options(populate_existing=True))
    if not job:
        return "skipped"
    result = job.result or {}
    usage = {**(result.get("usage") or {}), "platformBilling": bill}
    job.result = {**result, "usage": usage}
    record = await db.scalar(
        select(Usage)
        .where(Usage.generation_job_id == job.id, Usage.user_id == job.user_id, Usage.operation == "generation_image", Usage.deleted_at.is_(None))
        .order_by(Usage.created_at.desc())
        .limit(1)
    )
    if record:
        record.raw_usage = {**(record.raw_usage or {}), "platformBilling": bill}
    else:
        with attribution_context(job.generation_origin, job.agent_name, job.agent_run_id, job.test_run_id):
            add_token_usage(
                db,
                operation="generation_image",
                provider=job.provider,
                model=result.get("model") or (job.request or {}).get("model", ""),
                usage=usage,
                user_id=job.user_id,
                project_id=job.project_id,
                project_task_id=job.project_task_id,
                storyboard_line_id=job.storyboard_line_id,
                generation_job_id=job.id,
                request_id=task_id,
            )
    return "billing_refreshed"


async def poll_image_bills():
    while True:
        delay = 30
        try:
            async with session_factory() as db:
                now = utcnow()
                billing = Job.result["usage"]["platformBilling"]
                status = billing["status"].as_string()
                job = await db.scalar(
                    select(Job)
                    .where(
                        *eligible(),
                        or_(status.is_(None), status != "settled", billing["points"].as_string().is_(None)),
                        or_(Job.reconciliation_next_at.is_(None), Job.reconciliation_next_at <= now),
                    )
                    .order_by(Job.reconciliation_next_at.asc().nullsfirst(), Job.finished_at.desc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
                if job:
                    job.reconciliation_next_at = now + timedelta(minutes=10)
                    await db.commit()
                    await refresh_image_bill(db, job)
                    await db.commit()
                    delay = 2
        except Exception:
            logger.exception("查询原图片工单结算失败，将重试")
        await asyncio.sleep(delay)
