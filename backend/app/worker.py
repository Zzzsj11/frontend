from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import timedelta

from sqlalchemy import select

from .chat import chat_manager
from .config import settings, validate_runtime_security
from .database import close_database, init_database, session_factory
from .domain import _run_material_export, run_storyboard_job
from .jobs import Job, jobs
from .models import GenerationJobModel, ProjectTaskModel, utcnow
from .providers import generate_image, generate_video, resume_generation
from .redis_store import close_redis
from .schemas import ImageGenerationCreate, VideoGenerationCreate

logger = logging.getLogger("mvagent.worker")
REPLAYABLE_INTERNAL_KINDS = {"ass_outline", "general_outline", "ass_segment_retry"}
MAX_INTERNAL_ATTEMPTS = 3


def _job_from_model(model: GenerationJobModel) -> Job:
    return jobs._from_model(model)


async def _claim(kinds: tuple[str, ...], providers: tuple[str, ...]) -> Job | None:
    async with session_factory() as session:
        query = (
            select(GenerationJobModel)
            .where(
                GenerationJobModel.kind.in_(kinds),
                GenerationJobModel.status == "queued",
                GenerationJobModel.deleted_at.is_(None),
            )
            .order_by(GenerationJobModel.created_at)
            .with_for_update(skip_locked=True)
            .limit(20)
        )
        rows = list((await session.execute(query)).scalars())
        model = next(
            (row for row in rows if not providers or str((row.request or {}).get("_provider") or "internal") in providers),
            None,
        )
        if model is None:
            return None
        # Claim ownership without starting the execution clock. A model-level
        # semaphore (for example H3=2) may still keep this job waiting; the
        # JobManager writes started_at only after that final execution slot is acquired.
        model.status = "running"
        await session.commit()
        return _job_from_model(model)


async def _recover_stale(kinds: tuple[str, ...], providers: tuple[str, ...]) -> tuple[int, int]:
    """Recover jobs whose former worker stopped heartbeating through progress updates."""
    resumed = failed = 0
    threshold = utcnow() - timedelta(seconds=settings.worker_stale_seconds)
    async with session_factory() as session:
        rows = list(
            (
                await session.execute(
                    select(GenerationJobModel).where(
                        GenerationJobModel.kind.in_(kinds),
                        GenerationJobModel.status == "running",
                        GenerationJobModel.updated_at < threshold,
                        GenerationJobModel.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )
        for model in rows:
            provider = str((model.request or {}).get("_provider") or "internal")
            if providers and provider not in providers:
                continue
            if model.kind in REPLAYABLE_INTERNAL_KINDS and model.attempt < MAX_INTERNAL_ATTEMPTS:
                model.status = "queued"
                model.started_at = None
                model.attempt += 1
                resumed += 1
            elif model.provider_task_id:
                model.status = "queued"
                resumed += 1
            else:
                model.status = "failed"
                model.error = "Worker中断且重试次数已耗尽，请重新提交" if model.kind in REPLAYABLE_INTERNAL_KINDS else "Worker中断且供应商任务ID尚未落库，请重新提交"
                model.finished_at = utcnow()
                if model.kind in REPLAYABLE_INTERNAL_KINDS and model.project_task_id:
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
    if job.kind == "export":
        export_id = str(request.get("export_id") or "")
        return lambda item: _run_material_export(export_id, item)
    if job.kind == "chat":
        session_id = str(request.get("session_id") or "")
        return lambda item: chat_manager.run_persisted(session_id, item)
    if job.kind in REPLAYABLE_INTERNAL_KINDS:
        return run_storyboard_job
    raise RuntimeError(f"unsupported worker job kind: {job.kind}")


async def serve(kinds: tuple[str, ...], providers: tuple[str, ...], concurrency: int) -> None:
    validate_runtime_security()
    await init_database()
    resumed, failed = await _recover_stale(kinds, providers)
    if resumed or failed:
        logger.warning("recovered stale jobs: resumed=%s failed=%s", resumed, failed)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(name, stop.set)
    slots = asyncio.Semaphore(concurrency)
    active: set[asyncio.Task] = set()

    async def execute(job: Job) -> None:
        async with slots:
            heartbeat_interval = max(5.0, min(30.0, settings.worker_stale_seconds / 3))

            async def heartbeat() -> None:
                while True:
                    await asyncio.sleep(heartbeat_interval)
                    await jobs.heartbeat(job)
                    if job.kind in REPLAYABLE_INTERNAL_KINDS and job.project_task_id:
                        async with session_factory() as session:
                            task = await session.get(ProjectTaskModel, job.project_task_id)
                            if task and task.deleted_at is None:
                                config = dict(task.storyboard_config or {})
                                progress = dict(config.get("outlineProgress") or {})
                                progress.update(heartbeatAt=utcnow().isoformat(), jobId=job.id)
                                config["outlineProgress"] = progress
                                task.storyboard_config = config
                                await session.commit()

            heartbeat_task = asyncio.create_task(heartbeat())
            try:
                await jobs.run_claimed(job, _runner(job))
            finally:
                heartbeat_task.cancel()
                await asyncio.gather(heartbeat_task, return_exceptions=True)

    try:
        while not stop.is_set():
            if len(active) < concurrency:
                job = await _claim(kinds, providers)
                if job:
                    task = asyncio.create_task(execute(job))
                    active.add(task)
                    task.add_done_callback(active.discard)
                    continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                pass
    finally:
        if active:
            await asyncio.gather(*active, return_exceptions=True)
        await close_redis()
        await close_database()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kinds", default="image,video")
    parser.add_argument("--providers", default="")
    parser.add_argument("--concurrency", type=int, default=1)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(
        serve(
            tuple(value for value in args.kinds.split(",") if value),
            tuple(value for value in args.providers.split(",") if value),
            max(1, args.concurrency),
        )
    )


if __name__ == "__main__":
    main()
