from __future__ import annotations

import argparse
import asyncio
import logging
import os
import random
import signal
import socket
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import Integer, func, or_, select, update

from .chat import chat_manager
from .config import settings, validate_runtime_security
from .database import close_database, init_database, session_factory
from .domain import _run_material_export, run_storyboard_job
from .jobs import Job, durable_pool_available, jobs
from .models import GenerationJobModel, ProjectTaskModel, WorkerInstanceModel, utcnow
from .providers import ProviderError, generate_image, generate_video, resume_generation, validate_media_job_source
from .redis_store import ExecutionStoreUnavailable, acquire_execution_lease, close_redis, release_execution_lease, wait_for_worker_wakeup
from .schemas import ImageGenerationCreate, VideoGenerationCreate

logger = logging.getLogger("mvagent.worker")
REPLAYABLE_INTERNAL_KINDS = {"ass_outline", "general_outline", "ass_segment_retry", "storyboard_line", "billing_reconcile", "prompt_optimization", "export", "mv_export"}
MAX_INTERNAL_ATTEMPTS = 3
STALE_RECOVERY_INTERVAL_SECONDS = 15


def _claim_priority(model: GenerationJobModel, active_by_task: dict[str, int]) -> tuple[int, object]:
    return active_by_task.get(model.project_task_id, 0), model.created_at


def _job_from_model(model: GenerationJobModel) -> Job:
    return jobs._from_model(model)


def _reject_unsupported_media_job(model: GenerationJobModel) -> bool:
    if model.kind not in {"image", "video"}:
        return False
    try:
        validate_media_job_source(model)
    except ProviderError as exc:
        model.status, model.phase = "failed", "manual_review"
        model.error = str(exc)
        model.finished_at = utcnow()
        model.worker_id = model.heartbeat_at = model.lease_expires_at = None
        return True
    return False


async def _claim(kinds: tuple[str, ...], providers: tuple[str, ...], worker_id: str = "test-worker", queue: str = "") -> Job | None:
    claimed = await _claim_batch(kinds, providers, worker_id, queue, 1)
    return next(iter(claimed), None)


async def _claim_batch(kinds, providers, worker_id, queue, free):
    from .jobs import video_occupied
    from .worker_queues import VIDEO_POOLS, pool_column, pool_name, queue_conditions

    row = GenerationJobModel
    scope = queue_conditions(kinds, providers, queue)
    eligible = [*scope, row.status == "queued", or_(row.deleted_at.is_(None), row.kind.in_(("image", "video")) & row.provider_task_id.is_not(None))]
    batch = []
    async with session_factory() as session:
        pg = session.get_bind().dialect.name == "postgresql"
        occupied = {}
        if "video" in kinds and pg:
            await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("mv:video:capacity", 0))))
            pool = pool_column()
            occupied = dict((await session.execute(select(pool, func.count()).where(row.kind == "video", video_occupied()).group_by(pool))).all())
            if queue == "video:other" and len(
                set(await session.scalars(select(pool).where(row.kind == "video", row.status == "queued", row.deleted_at.is_(None), pool.in_(VIDEO_POOLS.values())).distinct()))
            ) == len(VIDEO_POOLS):
                eligible.append(row.provider_task_id.is_not(None) | row.idempotency_key.is_not(None))
            # Recover already admitted work even when no fresh capacity remains.
            resumed = row.provider_task_id.is_not(None) | row.idempotency_key.is_not(None)
            if sum(occupied.values()) >= settings.video_total_slots:
                eligible.append((row.kind != "video") | resumed)
            full = [pool for pool in VIDEO_POOLS.values() if occupied.get(pool, 0) >= settings.video_model_slots]
            if full:
                eligible.append((row.kind != "video") | resumed | pool_column().not_in(full))
        if "mv_export" in kinds:
            if pg:
                await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended("mv:export:render", 0))))
            if await session.scalar(select(row.id).where(row.kind == "mv_export", row.status == "running", row.deleted_at.is_(None)).limit(1)):
                eligible.append(row.kind != "mv_export")
        if pg:
            pool_counts = occupied
            if not queue and any(kind != "video" for kind in kinds):
                # A 1000-row page from a saturated pool must not hide a different model behind it.
                pool = pool_column()
                pool_counts = dict(
                    (await session.execute(select(pool, func.count()).where(row.status == "running", row.request["_executionPool"].as_string().is_not(None)).group_by(pool))).all()
                )
            for name, used in pool_counts.items():
                if name and name not in VIDEO_POOLS.values():
                    eligible.append(
                        (pool_column() != name)
                        | row.provider_task_id.is_not(None)
                        | row.idempotency_key.is_not(None)
                        | (func.coalesce(row.request["_executionConcurrency"].as_integer(), 1000).cast(Integer) > used)
                    )
        # Only lightweight identifiers enter the 1000-row candidate window.
        candidates = (
            await session.execute(select(row.id, row.project_task_id, row.created_at, pool_column().label("pool")).where(*eligible).order_by(row.created_at, row.id).limit(1000))
        ).all()
        tasks = {item.project_task_id for item in candidates if item.project_task_id}
        active = {}
        if tasks:
            active = dict(
                (
                    await session.execute(
                        select(row.project_task_id, func.count())
                        .where(*scope, row.status == "running", row.deleted_at.is_(None), row.project_task_id.in_(tasks))
                        .group_by(row.project_task_id)
                    )
                ).all()
            )
        unavailable = set()
        rendered = False
        leases = []
        try:
            while candidates and len(batch) < min(32, free):
                candidate = min(candidates, key=lambda c: _claim_priority(c, active))
                candidates.remove(candidate)
                if candidate.pool in unavailable:
                    candidates = [c for c in candidates if c.pool != candidate.pool]
                    continue
                model = await session.scalar(select(row).where(row.id == candidate.id, *eligible).with_for_update(skip_locked=True))
                if not model or _reject_unsupported_media_job(model) or (rendered and model.kind == "mv_export"):
                    continue
                pool = pool_name(model.request or {})
                limit = (model.request or {}).get("_executionConcurrency")
                lease = None
                if pg and model.kind == "video":
                    if not (model.provider_task_id or model.idempotency_key):
                        cap = settings.video_model_slots if pool in VIDEO_POOLS.values() else limit
                        if sum(occupied.values()) >= settings.video_total_slots:
                            break
                        if cap and occupied.get(pool, 0) >= int(cap):
                            unavailable.add(pool)
                            continue
                        occupied[pool] = occupied.get(pool, 0) + 1
                elif pool and limit is not None:
                    if pg:
                        available = await durable_pool_available(session, pool, int(limit), model.id)
                    else:
                        try:
                            token = await acquire_execution_lease(pool, max(1, min(1000, int(limit))), max(60, settings.worker_stale_seconds))
                        except ExecutionStoreUnavailable:
                            token = None
                        available = bool(token)
                        if token:
                            lease = (pool, token)
                            leases.append(lease)
                    if not available:
                        unavailable.add(pool)
                        continue
                now = utcnow()
                model.status, model.phase, model.worker_id = "running", "claimed", worker_id
                model.claimed_at = model.heartbeat_at = now
                model.lease_expires_at = now + timedelta(seconds=settings.worker_stale_seconds)
                job = _job_from_model(model)
                job.database_pool_reserved, job.execution_lease = pg, lease
                batch.append(job)
                active[model.project_task_id] = active.get(model.project_task_id, 0) + 1
                rendered |= model.kind == "mv_export"
            await session.commit()
        except BaseException:
            for lease in leases:
                await release_execution_lease(*lease)
            raise
    return batch


async def _recover_stale(kinds: tuple[str, ...], providers: tuple[str, ...], queue: str = "") -> tuple[int, int]:
    """只恢复租约已过期的任务；旧数据回退到 updated_at 判定。"""
    resumed = failed = 0
    threshold = utcnow() - timedelta(seconds=settings.worker_stale_seconds)
    async with session_factory() as session:
        from .export_state import reconcile_export_failures
        from .worker_queues import queue_conditions

        await reconcile_export_failures(session, kinds)
        rows = list(
            (
                await session.execute(
                    select(GenerationJobModel)
                    .where(
                        *queue_conditions(kinds, providers, queue),
                        GenerationJobModel.status == "running",
                        or_(
                            GenerationJobModel.lease_expires_at < utcnow(),
                            GenerationJobModel.lease_expires_at.is_(None) & (GenerationJobModel.updated_at < threshold),
                        ),
                        or_(GenerationJobModel.deleted_at.is_(None), GenerationJobModel.kind.in_(("image", "video"))),
                    )
                    .limit(1000)
                    .with_for_update(skip_locked=True)
                )
            ).scalars()
        )
        for model in rows:
            if _reject_unsupported_media_job(model):
                failed += 1
                continue
            provider = str((model.request or {}).get("_provider") or "internal")
            if providers and provider not in providers:
                continue
            if model.kind in {"export", "mv_export"}:
                from .models import MaterialExportModel

                delivered = await session.get(MaterialExportModel, (model.request or {}).get("export_id", ""), with_for_update=True)
                if delivered and delivered.deleted_at is None and delivered.generation_job_id == model.id and delivered.status == "ready":
                    model.status, model.phase, model.progress = "succeeded", "succeeded", 100
                    model.result = {"exportId": delivered.id, "archiveUrl": delivered.archive_url, "archiveSize": delivered.archive_size}
                    model.finished_at = delivered.finished_at or utcnow()
                    model.worker_id = model.heartbeat_at = model.lease_expires_at = None
                    continue
            if model.deleted_at is not None and not model.provider_task_id:
                model.status = "cancelled"
                model.phase = "manual_review" if model.phase == "submitting_provider" else "cancelled"
                model.finished_at = utcnow()
                failed += 1
            elif model.kind in REPLAYABLE_INTERNAL_KINDS and model.attempt < MAX_INTERNAL_ATTEMPTS:
                model.status = "queued"
                model.phase = "queued"
                model.started_at = None
                model.attempt += 1
                if model.kind in {"export", "mv_export"}:
                    from .models import MaterialExportModel

                    export = await session.get(MaterialExportModel, (model.request or {}).get("export_id", ""))
                    if export and export.deleted_at is None and export.status != "ready":
                        export.status, export.stage = "queued", "任务中断，正在自动恢复"
                resumed += 1
            elif model.provider_task_id:
                model.status = "queued"
                model.phase = "provider_running"
                resumed += 1
            elif (
                (model.phase == "submitting_provider" and model.idempotency_key or model.kind == "video" and model.phase in {"claimed", "executing"} and provider == "all-in-one")
                and model.attempt < MAX_INTERNAL_ATTEMPTS
                and (provider == "all-in-one" or bool((model.request or {}).get("_modelGateway")))
                and model.kind in {"image", "video"}
            ):
                # Only replay suppliers with proven idempotent creation. ToAPIs
                # supports business-ID lookup, but does not promise deduplication.
                model.status = "queued"
                model.phase = "queued"
                model.started_at = None
                model.attempt += 1
                resumed += 1
            else:
                model.status = "failed"
                model.phase = "manual_review" if model.phase == "submitting_provider" else "failed"
                model.error = (
                    "Worker中断且重试次数已耗尽，请重新提交"
                    if model.kind in REPLAYABLE_INTERNAL_KINDS
                    else "Worker在供应商提交窗口中断；当前供应商不支持幂等创建，已停止自动重提，请先人工核对供应商任务"
                    if model.phase == "manual_review"
                    else "Worker中断且供应商任务ID尚未落库，请重新提交"
                )
                model.finished_at = utcnow()
                if model.kind == "chat" and (model.request or {}).get("session_id"):
                    from .models import ChatSessionModel

                    chat_id = model.request["session_id"]
                    chat = await session.get(ChatSessionModel, chat_id, with_for_update=True)
                    if chat and chat.user_id == model.user_id and chat.status == "running":
                        newer = await session.scalar(
                            select(GenerationJobModel.id)
                            .where(
                                GenerationJobModel.kind == "chat",
                                GenerationJobModel.user_id == model.user_id,
                                GenerationJobModel.request["session_id"].as_string() == chat_id,
                                GenerationJobModel.created_at > model.created_at,
                                GenerationJobModel.status.in_(("queued", "running")),
                                GenerationJobModel.deleted_at.is_(None),
                            )
                            .limit(1)
                        )
                        if not newer:
                            chat.status = "idle"
                elif model.kind == "storyboard_line" and model.storyboard_line_id:
                    from .models import StoryboardLineModel

                    line = await session.get(StoryboardLineModel, model.storyboard_line_id)
                    if line and line.deleted_at is None:
                        line.generation_status = "failed"
                        line.generation_error = model.error
                elif model.kind in {"export", "mv_export"}:
                    from .models import MaterialExportModel

                    export = await session.get(MaterialExportModel, (model.request or {}).get("export_id", ""))
                    if export and export.deleted_at is None and export.status != "ready":
                        export.status, export.stage, export.error = "failed", "合成中断，请重试", model.error
                        export.finished_at = utcnow()
                elif model.kind == "prompt_optimization":
                    from .models import PromptOptimizationTaskModel

                    optimization_id = str((model.request or {}).get("optimization_task_id") or "")
                    optimization = await session.get(PromptOptimizationTaskModel, optimization_id) if optimization_id else None
                    if optimization and optimization.deleted_at is None:
                        optimization.status = "failed"
                        optimization.error = model.error
                elif model.kind in REPLAYABLE_INTERNAL_KINDS and model.project_task_id:
                    task = await session.get(ProjectTaskModel, model.project_task_id)
                    if task and task.deleted_at is None:
                        config = dict(task.storyboard_config or {})
                        progress = dict(config.get("outlineProgress") or {})
                        progress.update(error=model.error, jobId=model.id)
                        if model.kind == "ass_segment_retry":
                            progress["phase"] = "segment_retry_failed"
                        else:
                            progress["phase"] = "error"
                            task.status = "outline_failed"
                        config["outlineProgress"] = progress
                        task.storyboard_config = config
                failed += 1
            model.worker_id = None
            model.heartbeat_at = None
            model.lease_expires_at = None
        await session.commit()
    return resumed, failed


def _runner(job: Job):
    request = dict(job.request or {})
    public_request = {key: value for key, value in request.items() if not key.startswith("_")}
    if job.provider_task_id:
        return resume_generation
    if job.kind == "image":
        payload = ImageGenerationCreate.model_validate(public_request)
        return lambda item: generate_image(payload, item)
    if job.kind == "video":
        payload = VideoGenerationCreate.model_validate(public_request)
        return lambda item: generate_video(payload, item)
    if job.kind == "mv_export":
        from .mv_export import run_video_export

        return lambda item: run_video_export(str(request.get("export_id") or ""), item)
    if job.kind == "export":
        export_id = str(request.get("export_id") or "")
        return lambda item: _run_material_export(export_id, item)
    if job.kind == "chat":
        session_id = str(request.get("session_id") or "")
        return lambda item: chat_manager.run_persisted(session_id, item)
    if job.kind == "billing_reconcile":
        from .video_billing import run_video_billing_reconciliation

        return run_video_billing_reconciliation
    if job.kind == "prompt_optimization":
        from .creative import run_prompt_optimization_job

        return run_prompt_optimization_job
    if job.kind in REPLAYABLE_INTERNAL_KINDS:
        return run_storyboard_job
    raise RuntimeError(f"unsupported worker job kind: {job.kind}")


async def serve(kinds: tuple[str, ...], providers: tuple[str, ...], concurrency: int, queue: str = "") -> None:
    validate_runtime_security()
    await init_database()
    worker_id = f"worker-{socket.gethostname()}-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    version = os.getenv("RELEASE_VERSION", "development")
    async with session_factory() as session:
        session.add(
            WorkerInstanceModel(
                id=worker_id,
                hostname=socket.gethostname(),
                pid=os.getpid(),
                version=version,
                kinds=list(kinds),
                providers=list(providers),
                status="running",
                active_job_count=0,
            )
        )
        await session.commit()
    resumed, failed = await _recover_stale(kinds, providers, queue)
    if resumed or failed:
        logger.warning("recovered stale jobs: resumed=%s failed=%s", resumed, failed)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    active: set[asyncio.Task] = set()
    owned = {}

    async def renew_leases():
        while True:
            await asyncio.sleep(max(5, min(30, settings.worker_stale_seconds / 3)))
            ids = list(owned)
            for start in range(0, len(ids), 128):
                chunk = ids[start : start + 128]
                now = utcnow()
                try:
                    async with session_factory.begin() as db:
                        renewed = set(
                            await db.scalars(
                                update(GenerationJobModel)
                                .where(GenerationJobModel.id.in_(chunk), GenerationJobModel.worker_id == worker_id, GenerationJobModel.status == "running")
                                .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=settings.worker_stale_seconds))
                                .returning(GenerationJobModel.id)
                            )
                        )
                    # A terminal row may still be completing billing in its owning task.
                    missing = set(chunk) - renewed
                    if missing:
                        async with session_factory() as db:
                            lost = await db.scalars(
                                select(GenerationJobModel.id).where(
                                    GenerationJobModel.id.in_(missing),
                                    GenerationJobModel.status.in_(("queued", "running")),
                                    GenerationJobModel.worker_id.is_distinct_from(worker_id),
                                )
                            )
                            for jid in lost:
                                if jid in owned:
                                    owned[jid].cancel()
                except Exception:
                    logger.exception("工单批量续租失败，将重试")

    async def update_instance(status: str | None = None) -> None:
        async with session_factory() as session:
            instance = await session.get(WorkerInstanceModel, worker_id)
            if not instance:
                return
            now = utcnow()
            instance.last_heartbeat_at = now
            instance.active_job_count = len(active)
            if status:
                instance.status = status
                if status == "draining" and not instance.draining_at:
                    instance.draining_at = now
                if status == "drained":
                    instance.stopped_at = now
            await session.commit()

    async def instance_heartbeat() -> None:
        while True:
            try:
                await update_instance()
            except Exception:
                logger.exception("Worker 实例心跳失败，将重试")
            await asyncio.sleep(max(5.0, min(15.0, settings.worker_stale_seconds / 3)))

    instance_heartbeat_task = asyncio.create_task(instance_heartbeat())

    lease_task = asyncio.create_task(renew_leases())

    async def execute(job):
        try:
            await jobs.run_claimed(job, _runner(job))
        finally:
            owned.pop(job.id, None)

    from . import all_in_one
    from .image_billing import poll_image_bills
    from .redis_store import notify_worker
    from .worker_queues import VIDEO_QUEUES

    poll_client = httpx.AsyncClient(timeout=60, limits=httpx.Limits(max_connections=320, max_keepalive_connections=256))
    traffic_token = all_in_one._video_traffic.set(all_in_one.VideoTraffic())
    client_token = all_in_one._poll_client.set(poll_client)
    queues = (queue,) if queue else tuple(q for k in kinds for q in (VIDEO_QUEUES if k == "video" else (k,)))
    local_ready = asyncio.Event()

    def completed(task):
        active.discard(task)
        local_ready.set()

    billing_task = asyncio.create_task(poll_image_bills()) if "image" in kinds and (not providers or "all-in-one" in providers) else None

    async def recover_expired():
        while True:
            await asyncio.sleep(STALE_RECOVERY_INTERVAL_SECONDS * random.uniform(0.9, 1.1))
            try:
                resumed, _ = await _recover_stale(kinds, providers, queue)
                if resumed:
                    local_ready.set()
            except Exception:
                logger.exception("过期工单巡检失败，将重试")

    recovery_task = asyncio.create_task(recover_expired())
    try:
        while not stop.is_set():
            local_ready.clear()
            if len(active) < concurrency:
                try:
                    if concurrency == 1:
                        job = await _claim(kinds, providers, worker_id, queue)
                        batch = [job] if job else []
                    else:
                        batch = await _claim_batch(kinds, providers, worker_id, queue, concurrency - len(active))
                except Exception:
                    logger.exception("领取工单失败，将重试")
                    await asyncio.sleep(max(0.05, min(5.0, settings.worker_poll_seconds)))
                    batch = []
                for job in batch:
                    task = asyncio.create_task(execute(job))
                    owned[job.id] = task
                    active.add(task)
                    task.add_done_callback(completed)
                if batch:
                    if len(batch) == 32 or len(active) == concurrency:
                        from .worker_queues import queue_for

                        for target in {queue_for(job.kind, job.request) for job in batch}:
                            await notify_worker(target)
                    continue
            timeout = settings.worker_poll_seconds + random.uniform(1, 10)
            waiting = {asyncio.create_task(stop.wait()), asyncio.create_task(local_ready.wait())}
            if len(active) < concurrency:
                waiting.add(asyncio.create_task(wait_for_worker_wakeup(timeout, queues)))
            _, pending = await asyncio.wait(waiting, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
            for item in pending:
                item.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
    finally:
        recovery_task.cancel()
        await asyncio.gather(recovery_task, return_exceptions=True)
        if billing_task:
            billing_task.cancel()
            await asyncio.gather(billing_task, return_exceptions=True)
        await update_instance("draining")
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        lease_task.cancel()
        await asyncio.gather(lease_task, return_exceptions=True)
        await update_instance("drained")
        instance_heartbeat_task.cancel()
        await asyncio.gather(instance_heartbeat_task, return_exceptions=True)
        await close_redis()
        all_in_one._video_traffic.reset(traffic_token)
        all_in_one._poll_client.reset(client_token)
        await poll_client.aclose()
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kinds", default="image,video")
    parser.add_argument("--video-queue", choices=("video:wan", "video:seedance", "video:other"), default="")
    parser.add_argument("--providers", default="")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        serve(
            tuple(value for value in args.kinds.split(",") if value),
            tuple(value for value in args.providers.split(",") if value),
            max(1, args.concurrency),
            args.video_queue,
        )
    )


if __name__ == "__main__":
    main()
