from __future__ import annotations

import argparse
import asyncio
import logging
import signal
from datetime import timedelta

from sqlalchemy import select

from .config import settings, validate_runtime_security
from .database import close_database, init_database, session_factory
from .domain import _run_material_export
from .jobs import Job, jobs
from .models import GenerationJobModel, utcnow
from .providers import generate_image, generate_video, resume_generation
from .redis_store import close_redis
from .schemas import ImageGenerationCreate, VideoGenerationCreate

logger = logging.getLogger("mvagent.worker")


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
        model.status = "running"
        model.started_at = model.started_at or utcnow()
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
            if model.provider_task_id:
                model.status = "queued"
                resumed += 1
            else:
                model.status = "failed"
                model.error = "Worker中断且供应商任务ID尚未落库，请重新提交"
                model.finished_at = utcnow()
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
            await jobs.run_claimed(job, _runner(job))

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
