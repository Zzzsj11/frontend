from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable

from sqlalchemy import select

from .database import session_factory
from .models import GenerationJobModel, SceneAssetModel, ShotAssetModel, utcnow
from .redis_store import cache_job, get_cached_job
from .token_usage import add_token_usage

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
    user_id: str | None = None
    project_id: str | None = None
    project_task_id: str | None = None
    storyboard_line_id: str | None = None
    request: dict[str, Any] | None = None

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
        async with session_factory() as session:
            session.add(
                GenerationJobModel(
                    id=job.id, kind=kind, request=request, user_id=user_id, project_id=project_id, project_task_id=project_task_id, storyboard_line_id=storyboard_line_id
                )
            )
            await session.commit()
        await cache_job(job.id, job.public())
        asyncio.create_task(self._run(job, runner))
        return job

    async def _persist(self, job: Job) -> None:
        job.updated_at = time.time()
        async with session_factory() as session:
            model = await session.get(GenerationJobModel, job.id)
            if model:
                model.status, model.progress, model.result, model.error = job.status, job.progress, job.result, job.error
                if job.status == "running" and model.started_at is None:
                    model.started_at = utcnow()
                if job.status in {"succeeded", "failed", "cancelled"}:
                    model.finished_at = utcnow()
                await session.commit()
                job.updated_at = model.updated_at.timestamp()
        await cache_job(job.id, job.public())

    async def update_progress(self, job: Job, progress: int) -> None:
        job.progress = max(job.progress, min(progress, 99))
        await self._persist(job)

    async def _run(self, job: Job, runner: JobRunner) -> None:
        job.status, job.progress = "running", 5
        await self._persist(job)
        try:
            job.result = await runner(job)
            job.progress, job.status = 100, "succeeded"
            await self._persist_asset(job)
        except asyncio.CancelledError:
            job.status = "cancelled"
            raise
        except Exception as exc:
            job.status, job.error = "failed", str(exc)
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
        finally:
            await self._persist(job)

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
            job = Job(
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
            )
        await cache_job(job.id, job.public())
        return job


jobs = JobManager()
