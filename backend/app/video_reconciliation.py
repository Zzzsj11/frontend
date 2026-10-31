"""Durable, query-only recovery. Never creates or resubmits a provider job."""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import timedelta

from sqlalchemy import or_, select

from .database import session_factory
from .jobs import JobExpiredError, jobs
from .models import GenerationJobModel, ProjectModel, ProjectTaskModel, StoryboardLineModel, utcnow
from .redis_store import cache_job

logger = logging.getLogger(__name__)
LEASE_SECONDS = 180


async def claim(job_id: str | None = None):
    now = utcnow()
    async with session_factory() as db:
        query = (
            select(GenerationJobModel)
            .join(ProjectModel, GenerationJobModel.project_id == ProjectModel.id)
            .join(ProjectTaskModel, GenerationJobModel.project_task_id == ProjectTaskModel.id)
            .join(StoryboardLineModel, GenerationJobModel.storyboard_line_id == StoryboardLineModel.id)
            .where(
                GenerationJobModel.kind == "video",
                GenerationJobModel.provider == "all-in-one",
                GenerationJobModel.status == "failed",
                GenerationJobModel.provider_task_id.is_not(None),
                GenerationJobModel.provider_task_id != "",
                GenerationJobModel.deleted_at.is_(None),
                or_(GenerationJobModel.phase.in_(("manual_review", "auto_reconciling")), GenerationJobModel.error.contains("核查原任务")),
                or_(GenerationJobModel.lease_expires_at.is_(None), GenerationJobModel.lease_expires_at <= now),
                ProjectModel.deleted_at.is_(None),
                ProjectTaskModel.deleted_at.is_(None),
                StoryboardLineModel.deleted_at.is_(None),
                ProjectModel.user_id == GenerationJobModel.user_id,
                ProjectTaskModel.project_id == ProjectModel.id,
                StoryboardLineModel.project_task_id == ProjectTaskModel.id,
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
    from .model_gateway import run_with_context
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

    tasks = [asyncio.create_task(lane()) for _ in range(2)]
    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
