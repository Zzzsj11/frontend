"""Keep export UI records consistent with durable job terminal states."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import GenerationJobModel, MaterialExportModel, utcnow


async def sync_export_failure(session: AsyncSession, job: GenerationJobModel) -> None:
    if job.kind not in {"export", "mv_export"} or job.status not in {"failed", "cancelled"}:
        return
    export = await session.get(MaterialExportModel, (job.request or {}).get("export_id", ""))
    if export and export.deleted_at is None and export.generation_job_id == job.id and export.user_id == job.user_id and export.status in {"queued", "running"}:
        export.status = "failed"
        export.stage = "导出中断，请重试"
        export.error = job.error or "导出任务已中断，请重新导出"
        export.finished_at = job.finished_at or utcnow()


async def reconcile_export_failures(session: AsyncSession, kinds: tuple[str, ...]) -> None:
    export_kinds = set(kinds) & {"export", "mv_export"}
    if not export_kinds:
        return
    rows = await session.execute(
        select(GenerationJobModel)
        .join(MaterialExportModel, MaterialExportModel.generation_job_id == GenerationJobModel.id)
        .where(
            GenerationJobModel.kind.in_(export_kinds),
            GenerationJobModel.status.in_(("failed", "cancelled")),
            GenerationJobModel.deleted_at.is_(None),
            MaterialExportModel.deleted_at.is_(None),
            MaterialExportModel.status.in_(("queued", "running")),
        )
        .with_for_update(skip_locked=True)
    )
    for job in rows.scalars():
        await sync_export_failure(session, job)
