from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .database import session_factory
from .models import GenerationJobModel, SceneAssetModel, ShotAssetModel, utcnow
from .redis_store import cache_job, get_cached_job, notify_worker
from .token_usage import add_token_usage

JobRunner = Callable[["Job"], Awaitable[dict[str, Any]]]

# 重启后可续跑挽回的窗口：供应商任务保留期内、本机协程丢失的僵尸任务重新挂轮询
RECOVERY_WINDOW_SECONDS = 2 * 3600


def _timestamp(value: datetime | float) -> float:
    if isinstance(value, float):
        return value
    # SQLite 读出的 naive 时间按 UTC 解释（生产 PostgreSQL 读出本就走 aware）
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


@dataclass
class Job:
    id: str
    kind: str
    status: str = "queued"
    progress: int = 0
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: float = 0
    updated_at: float = 0
    user_id: str | None = None
    project_id: str | None = None
    project_task_id: str | None = None
    storyboard_line_id: str | None = None
    request: dict[str, Any] | None = None
    provider: str | None = None
    provider_task_id: str | None = None
    idempotency_key: str | None = None

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "status": self.status,
            "progress": self.progress,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "provider": self.provider,
            "provider_task_id": self.provider_task_id,
            "idempotency_key": self.idempotency_key,
        }


class JobManager:
    def __init__(self, execution_slots: dict[str, asyncio.Semaphore] | None = None) -> None:
        # 本进程内活跃协程的 job id：对账/恢复时防止重复挂轮询
        self._active: set[str] = set()
        # 受理上限与实际供应商调用并发分离：超出槽位的任务保持 queued。
        self._execution_slots = execution_slots or {}
        # 模型注册中心可为每个模型声明独立执行池和并发上限。任务创建时把能力
        # 快照写进 request，保证模型配置后续变化不会改变已排队任务的调度语义。
        self._model_execution_slots: dict[str, tuple[int, asyncio.Semaphore]] = {}

    def _execution_slot(self, job: Job) -> asyncio.Semaphore | None:
        request = job.request or {}
        pool = str(request.get("_executionPool") or "").strip()
        raw_limit = request.get("_executionConcurrency")
        if pool and raw_limit is not None:
            limit = max(1, min(1000, int(raw_limit)))
            configured = self._model_execution_slots.get(pool)
            if configured is None:
                configured = (limit, asyncio.Semaphore(limit))
                self._model_execution_slots[pool] = configured
            return configured[1]
        return self._execution_slots.get(job.kind)

    async def create(
        self,
        kind: str,
        request: dict[str, Any],
        runner: JobRunner,
        *,
        user_id: str,
        project_id: str | None = None,
        project_task_id: str | None = None,
        storyboard_line_id: str | None = None,
    ) -> Job:
        async with session_factory() as session:
            job = await self.enqueue(
                session,
                kind,
                request,
                user_id=user_id,
                project_id=project_id,
                project_task_id=project_task_id,
                storyboard_line_id=storyboard_line_id,
            )
            await session.commit()
        await self.dispatch(job, runner)
        return job

    async def enqueue(
        self,
        session: AsyncSession,
        kind: str,
        request: dict[str, Any],
        *,
        user_id: str,
        project_id: str | None = None,
        project_task_id: str | None = None,
        storyboard_line_id: str | None = None,
    ) -> Job:
        """Add a replayable job to the caller's transaction without dispatching it."""
        now = time.time()
        job = Job(
            id=f"job-{uuid.uuid4().hex}",
            kind=kind,
            created_at=now,
            updated_at=now,
            user_id=user_id,
            project_id=project_id,
            project_task_id=project_task_id,
            storyboard_line_id=storyboard_line_id,
            request=request,
        )
        session.add(
            GenerationJobModel(
                id=job.id, kind=kind, request=request, user_id=user_id, project_id=project_id, project_task_id=project_task_id, storyboard_line_id=storyboard_line_id
            )
        )
        await session.flush()
        return job

    async def dispatch(self, job: Job, runner: JobRunner) -> None:
        """Dispatch only after the transaction that created the job has committed."""
        await cache_job(job.id, job.public())
        if settings.job_execution_mode == "worker":
            await notify_worker(job.kind)
        else:
            asyncio.create_task(self._run(job, runner))

    async def run_claimed(self, job: Job, runner: JobRunner) -> None:
        """Execute a job atomically claimed by an external worker."""
        await self._run(job, runner)

    async def _persist(self, job: Job) -> None:
        job.updated_at = time.time()
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job.id)
            if model:
                model.status, model.progress, model.result, model.error = job.status, job.progress, job.result, job.error
                model.provider, model.provider_task_id = job.provider, job.provider_task_id
                if job.idempotency_key:
                    model.idempotency_key = job.idempotency_key
                if job.status == "running" and model.started_at is None:
                    model.started_at = utcnow()
                if job.status in {"succeeded", "failed", "cancelled"}:
                    model.finished_at = utcnow()
                await session.commit()
                job.updated_at = model.updated_at.timestamp()
        await cache_job(job.id, job.public())

    async def update_progress(self, job: Job, progress: int) -> None:
        # Progress doubles as the durable worker heartbeat. PostgreSQL remains
        # authoritative when Redis or the worker process disappears.
        job.progress = max(job.progress, min(progress, 99))
        job.updated_at = time.time()
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job.id)
            if model and model.status == "running":
                model.progress = job.progress
                model.updated_at = utcnow()
                await session.commit()
        await cache_job(job.id, job.public())

    async def heartbeat(self, job: Job) -> None:
        """Refresh a running job lease without changing its visible progress."""
        await self.update_progress(job, job.progress)

    async def _run(self, job: Job, runner: JobRunner) -> None:
        self._active.add(job.id)
        slots = self._execution_slot(job)
        try:
            if slots:
                async with slots:
                    await self._execute(job, runner)
            else:
                await self._execute(job, runner)
        except asyncio.CancelledError:
            job.status = "cancelled"
            raise
        finally:
            self._active.discard(job.id)
            await self._persist(job)

    async def _execute(self, job: Job, runner: JobRunner) -> None:
        """拿到执行槽位后才进入 running，供应商调用完成前一直占用槽位。"""
        job.status, job.progress = "running", 5
        await self._persist(job)
        try:
            job.result = await runner(job)
            job.progress, job.status = 100, "succeeded"
            await self._persist_asset(job)
        except Exception as exc:
            job.status, job.error = "failed", str(exc)[:2000]
            async with session_factory() as session:
                add_token_usage(
                    session,
                    operation=f"generation_{job.kind}_failed",
                    provider=str(getattr(exc, "provider", "")),
                    model=str((job.request or {}).get("model") or ""),
                    usage=getattr(exc, "usage", {}),
                    user_id=job.user_id,
                    project_id=job.project_id,
                    project_task_id=job.project_task_id,
                    storyboard_line_id=job.storyboard_line_id,
                    generation_job_id=job.id,
                    request_id=getattr(exc, "request_id", None),
                )
                await session.commit()

    async def _persist_asset(self, job: Job) -> None:
        if not job.result:
            return
        async with session_factory() as session:
            if job.kind in {"image", "video"}:
                add_token_usage(
                    session,
                    operation=f"generation_{job.kind}",
                    provider=str(job.result.get("provider") or ""),
                    model=str(job.result.get("model") or (job.request or {}).get("model") or ""),
                    usage=job.result.get("usage"),
                    user_id=job.user_id,
                    project_id=job.project_id,
                    project_task_id=job.project_task_id,
                    storyboard_line_id=job.storyboard_line_id,
                    generation_job_id=job.id,
                    request_id=job.result.get("providerTaskId"),
                )
            if job.storyboard_line_id and job.kind == "image" and job.result.get("urls"):
                current = (
                    (
                        await session.execute(
                            select(SceneAssetModel).where(
                                SceneAssetModel.storyboard_line_id == job.storyboard_line_id, SceneAssetModel.deleted_at.is_(None), SceneAssetModel.is_current.is_(True)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for item in current:
                    item.is_current = False
                thumbnails = job.result.get("thumbnailUrls") or []
                session.add(
                    SceneAssetModel(
                        id=f"scene-{uuid.uuid4().hex}",
                        storyboard_line_id=job.storyboard_line_id,
                        generation_job_id=job.id,
                        image_url=job.result["urls"][0],
                        image_thumbnail_url=thumbnails[0] if thumbnails else None,
                        prompt=str((job.request or {}).get("prompt") or ""),
                        is_current=True,
                    )
                )
            elif job.storyboard_line_id and job.kind == "video" and job.result.get("videoUrl"):
                current = (
                    (
                        await session.execute(
                            select(ShotAssetModel).where(
                                ShotAssetModel.storyboard_line_id == job.storyboard_line_id, ShotAssetModel.deleted_at.is_(None), ShotAssetModel.is_current.is_(True)
                            )
                        )
                    )
                    .scalars()
                    .all()
                )
                for item in current:
                    item.is_current = False
                request = job.request or {}
                session.add(
                    ShotAssetModel(
                        id=f"shot-{uuid.uuid4().hex}",
                        storyboard_line_id=job.storyboard_line_id,
                        generation_job_id=job.id,
                        cover_url=job.result["coverUrl"],
                        cover_thumbnail_url=job.result.get("coverThumbnailUrl"),
                        video_url=job.result["videoUrl"],
                        duration=float(job.result.get("duration") or 0),
                        resolution=str(request.get("resolution") or "720p"),
                        ratio=str(job.result.get("ratio") or request.get("ratio") or "16:9"),
                        prompt=str(request.get("prompt") or ""),
                        is_current=True,
                    )
                )
            await session.commit()

    async def set_provider_task(self, job: Job, provider: str, task_id: str, *, idempotency_key: str | None = None) -> None:
        """供应商 taskId 即时落库：重启恢复与后台对账都依赖它，成功失败都要保留"""
        job.provider, job.provider_task_id = provider, task_id
        if idempotency_key:
            job.idempotency_key = idempotency_key
        job.updated_at = time.time()
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job.id)
            if model:
                model.provider, model.provider_task_id = job.provider, job.provider_task_id
                model.idempotency_key = job.idempotency_key
                await session.commit()
        await cache_job(job.id, job.public())

    def is_active(self, job_id: str) -> bool:
        return job_id in self._active

    def _from_model(self, model: GenerationJobModel) -> Job:
        return Job(
            id=model.id,
            kind=model.kind,
            status=model.status,
            progress=model.progress,
            result=model.result,
            error=model.error,
            created_at=_timestamp(model.created_at),
            updated_at=_timestamp(model.updated_at),
            user_id=model.user_id,
            project_id=model.project_id,
            project_task_id=model.project_task_id,
            storyboard_line_id=model.storyboard_line_id,
            request=model.request,
            provider=model.provider,
            provider_task_id=model.provider_task_id,
            idempotency_key=model.idempotency_key,
        )

    async def recover_stale_jobs(self, runner: JobRunner) -> dict[str, int]:
        """重启后恢复媒体生成任务：内存协程已丢，有供应商 taskId 且未过期的续跑轮询挽回结果，其余判败"""
        now = time.time()
        to_resume: list[Job] = []
        stale_failed: list[Job] = []
        async with session_factory() as session:
            rows = (
                (
                    await session.execute(
                        select(GenerationJobModel).where(
                            GenerationJobModel.kind.in_(("image", "video")),
                            GenerationJobModel.status.in_(("queued", "running")),
                            GenerationJobModel.deleted_at.is_(None),
                        )
                    )
                )
                .scalars()
                .all()
            )
            for model in rows:
                age = now - _timestamp(model.created_at)
                if model.provider_task_id and age <= RECOVERY_WINDOW_SECONDS:
                    to_resume.append(self._from_model(model))
                    continue
                model.status = "failed"
                model.error = "生成任务已过期，请重新生成" if model.provider_task_id else "服务重启导致任务中断，请重新生成"
                model.finished_at = utcnow()
                stale_failed.append(self._from_model(model))
            await session.commit()
        for job in [*stale_failed, *to_resume]:
            await cache_job(job.id, job.public())
        for job in to_resume:
            asyncio.create_task(self._run(job, runner))
        return {"resumed": len(to_resume), "failed": len(stale_failed)}

    async def resume_one(self, job_id: str, runner: JobRunner) -> Job | None:
        """对账发现供应商仍在执行而本机无活跃协程时，重新挂起轮询（不重复提交任务）"""
        if job_id in self._active:
            return None
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job_id)
            if not model or model.deleted_at is not None or model.status not in {"queued", "running"} or not model.provider_task_id:
                return None
            job = self._from_model(model)
        await cache_job(job.id, job.public())
        asyncio.create_task(self._run(job, runner))
        return job

    async def finalize_success(self, job: Job, result: dict[str, Any]) -> Job:
        """对账确认供应商已成功：补写资产与终态"""
        if job.status != "succeeded":
            job.result = result
            job.progress, job.status = 100, "succeeded"
            await self._persist_asset(job)
            await self._persist(job)
        return job

    async def finalize_failure(self, job: Job, error: str) -> Job:
        if job.status != "failed":
            job.status, job.error = "failed", error[:2000]
            await self._persist(job)
        return job

    async def get(self, job_id: str, user_id: str | None = None) -> Job | None:
        cached = await get_cached_job(job_id)
        if cached:
            async with session_factory() as session:
                model = await session.get(GenerationJobModel, job_id)
                if not model or model.deleted_at is not None or (user_id is not None and model.user_id != user_id):
                    return None
            return Job(
                **cached,
                user_id=model.user_id,
                project_id=model.project_id,
                project_task_id=model.project_task_id,
                storyboard_line_id=model.storyboard_line_id,
                request=model.request,
            )
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job_id)
            if not model or model.deleted_at is not None or (user_id is not None and model.user_id != user_id):
                return None
            job = self._from_model(model)
        await cache_job(job.id, job.public())
        return job


_provider_generation_slots = asyncio.Semaphore(settings.provider_generation_worker_concurrency)
jobs = JobManager({"image": _provider_generation_slots, "video": _provider_generation_slots})
