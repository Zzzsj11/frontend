"""Durable, query-only recovery. Never creates or resubmits a provider job."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import or_, select

from .database import session_factory
from .jobs import JobExpiredError, jobs, unverified_video_failure
from .models import GenerationJobModel, ProjectModel, ProjectTaskModel, StoryboardLineModel, utcnow
from .redis_store import cache_job

logger = logging.getLogger(__name__)
LEASE_SECONDS = 180


async def claim(job_id: str | None = None):
    now = utcnow()
    async with session_factory() as db:
        query = (
            select(GenerationJobModel)
            .outerjoin(ProjectModel, GenerationJobModel.project_id == ProjectModel.id)
            .outerjoin(ProjectTaskModel, GenerationJobModel.project_task_id == ProjectTaskModel.id)
            .outerjoin(StoryboardLineModel, GenerationJobModel.storyboard_line_id == StoryboardLineModel.id)
            .where(
                GenerationJobModel.kind == "video",
                GenerationJobModel.provider == "all-in-one",
                GenerationJobModel.status == "failed",
                GenerationJobModel.provider_task_id.is_not(None),
                GenerationJobModel.provider_task_id != "",
                GenerationJobModel.deleted_at.is_(None),
                or_(unverified_video_failure(), GenerationJobModel.phase.in_(("manual_review", "auto_reconciling")), GenerationJobModel.error.contains("核查原任务")),
                or_(GenerationJobModel.lease_expires_at.is_(None), GenerationJobModel.lease_expires_at <= now),
                ProjectModel.deleted_at.is_(None),
                ProjectTaskModel.deleted_at.is_(None),
                StoryboardLineModel.deleted_at.is_(None),
                or_(GenerationJobModel.project_id.is_(None), ProjectModel.user_id == GenerationJobModel.user_id),
                or_(GenerationJobModel.project_task_id.is_(None), ProjectTaskModel.project_id == ProjectModel.id),
                or_(GenerationJobModel.storyboard_line_id.is_(None), StoryboardLineModel.project_task_id == ProjectTaskModel.id),
            )
        )
        if job_id:
            query = query.where(GenerationJobModel.id == job_id)
        else:
            query = query.where(or_(GenerationJobModel.reconciliation_next_at.is_(None), GenerationJobModel.reconciliation_next_at <= now))
        model = await db.scalar(
            query.order_by(GenerationJobModel.reconciliation_next_at.asc().nullsfirst(), GenerationJobModel.created_at)
            .with_for_update(skip_locked=True, of=GenerationJobModel)
            .limit(1)
        )
        if not model:
            return None
        model.worker_id = f"reconcile-{uuid.uuid4().hex}"
        model.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
        model.reconciliation_attempts += 1
        model.phase = "auto_reconciling"
        await db.commit()
        job = jobs._from_model(model)
    await cache_job(job.id, job.public())
    return job


async def heartbeat(job):
    while True:
        await asyncio.sleep(30)
        async with session_factory() as db:
            model = await db.get(GenerationJobModel, job.id, with_for_update=True)
            if not model or model.worker_id != job.worker_id or model.status != "failed":
                return
            model.lease_expires_at = utcnow() + timedelta(seconds=LEASE_SECONDS)
            await db.commit()


async def recover(job):
    from .generation_context import run_with_context
    from .providers import query_provider_task, store_provider_result, validate_media_job_source

    keeper = asyncio.create_task(heartbeat(job))
    detail = "等待平台归档完成，系统将自动恢复原视频"
    try:
        validate_media_job_source(job)

        async def query(original):
            return await query_provider_task(original.kind, original.provider_task_id, original.provider)

        data = await run_with_context(job, query)
        status = str(data.get("status") or "").upper()
        if status in {"SUCCESS", "SUCCEEDED", "COMPLETED", "READY", "SUCCEED"}:
            result = await store_provider_result(job, data)
            await jobs.finalize_success(job, result)
            return {"action": "recovered", "providerStatus": status}
        if status in {"FAILED", "CANCELLED", "CANCELED"}:
            from .all_in_one import confirmed_failure
            from .video_billing import apply_platform_video_bill

            if confirmed_failure(job.provider_task_id, data):
                async with session_factory() as db:
                    model = await db.get(GenerationJobModel, job.id, with_for_update=True)
                    if not model or model.worker_id != job.worker_id or model.deleted_at or model.status != "failed":
                        raise JobExpiredError("核对任务已结束")
                    # Merge accounting before storing the terminal envelope so it can compare
                    # with the previously committed snapshot, including concurrent corrections.
                    await apply_platform_video_bill(db, model.id, job.provider_task_id, data)
                    model.request = {**(model.request or {}), "_providerTerminalResponse": data, "_verifiedFailureTaskId": job.provider_task_id}
                    model.error = f"平台已确认终态 {status}，费用已结算"
                    model.phase = "failed"
                    model.worker_id = model.lease_expires_at = model.reconciliation_next_at = None
                    await db.commit()
                    await cache_job(model.id, jobs._from_model(model).public())
                return {"action": "failed", "providerStatus": status}
        # Do not infer a refund or permit recreation from transient/ambiguous platform states.
        detail = f"原平台任务状态 {status or '未知'}，系统将继续自动核对，不会重复生成"
        return {"action": "waiting", "providerStatus": status}
    except JobExpiredError:
        return {"action": "skipped", "providerStatus": None}
    except Exception:
        logger.exception("original video recovery deferred: job_id=%s provider_task_id=%s", job.id, job.provider_task_id)
        detail = "查询或保存原视频暂未完成，系统将自动重试恢复，不会重复生成"
        return {"action": "deferred", "providerStatus": None}
    finally:
        keeper.cancel()
        await asyncio.gather(keeper, return_exceptions=True)
        async with session_factory() as db:
            model = await db.get(GenerationJobModel, job.id, with_for_update=True)
            if model and model.worker_id == job.worker_id and model.status == "failed":
                model.worker_id, model.lease_expires_at = None, None
                model.reconciliation_next_at = utcnow() + timedelta(seconds=min(900, 30 * 2 ** min(model.reconciliation_attempts, 5)))
                if model.reconciliation_attempts == 8 or model.reconciliation_attempts % 96 == 0:
                    logger.warning("视频核对持续未完成，需要人工检查 job_id=%s attempts=%s", model.id, model.reconciliation_attempts)
                model.error = detail
                await db.commit()
                await cache_job(model.id, jobs._from_model(model).public())


async def reconcile_one(job_id: str):
    job = await claim(job_id)
    return await recover(job) if job else {"action": "skipped", "providerStatus": None}


async def serve():
    async def lane():
        while True:
            try:
                job = await claim()
                if job:
                    await recover(job)
                    continue
            except Exception:
                logger.exception("video reconciliation sweep failed")
            await asyncio.sleep(15)

    from .video_billing import poll_pending_video_bills

    tasks = [asyncio.create_task(lane()) for _ in range(2)]
    tasks.append(asyncio.create_task(poll_pending_video_bills()))
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
