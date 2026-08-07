from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from .database import session_factory
from .models import GenerationJobModel
from .redis_store import cache_job, get_cached_job


JobRunner = Callable[["Job"], Awaitable[dict[str, Any]]]


def _timestamp(value: datetime | float) -> float:
    return value if isinstance(value, float) else value.timestamp()


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
        }


class JobManager:
    async def create(self, kind: str, request: dict[str, Any], runner: JobRunner) -> Job:
        now = time.time()
        job = Job(id=f"job-{uuid.uuid4().hex}", kind=kind, created_at=now, updated_at=now)
        async with session_factory() as session:
            session.add(GenerationJobModel(id=job.id, kind=kind, request=request))
            await session.commit()
        await cache_job(job.id, job.public())
        asyncio.create_task(self._run(job, runner))
        return job

    async def _persist(self, job: Job) -> None:
        job.updated_at = time.time()
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job.id)
            if model:
                model.status = job.status
                model.progress = job.progress
                model.result = job.result
                model.error = job.error
                await session.commit()
                job.updated_at = model.updated_at.timestamp()
        await cache_job(job.id, job.public())

    async def update_progress(self, job: Job, progress: int) -> None:
        job.progress = max(job.progress, min(progress, 99))
        await self._persist(job)

    async def _run(self, job: Job, runner: JobRunner) -> None:
        job.status = "running"
        job.progress = 5
        await self._persist(job)
        try:
            job.result = await runner(job)
            job.progress = 100
            job.status = "succeeded"
        except asyncio.CancelledError:
            job.status = "cancelled"
            raise
        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
        finally:
            await self._persist(job)

    async def get(self, job_id: str) -> Job | None:
        cached = await get_cached_job(job_id)
        if cached:
            return Job(**cached)
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job_id)
            if not model:
                return None
            job = Job(
                id=model.id,
                kind=model.kind,
                status=model.status,
                progress=model.progress,
                result=model.result,
                error=model.error,
                created_at=_timestamp(model.created_at),
                updated_at=_timestamp(model.updated_at),
            )
        await cache_job(job.id, job.public())
        return job


jobs = JobManager()

