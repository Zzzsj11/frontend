import asyncio
from datetime import timedelta

import pytest
from test_mv_export import export_case as export_case

from app.database import session_factory
from app.jobs import jobs
from app.models import GenerationJobModel, MaterialExportModel, utcnow
from app.worker import _recover_stale


@pytest.mark.parametrize("kind,endpoint", [("export", "material-exports"), ("mv_export", "video-exports")])
@pytest.mark.parametrize("terminal", ["failed", "cancelled"])
def test_terminal_job_repairs_stuck_export_and_allows_retry(client, export_case, kind, endpoint, terminal):
    headers, task_id = export_case
    created = client.post(f"/api/tasks/{task_id}/{endpoint}", headers=headers).json()

    async def run():
        async with session_factory() as db:
            model = await db.get(GenerationJobModel, created["jobId"])
            model.status, model.error = terminal, "database temporarily unavailable"
            export = await db.get(MaterialExportModel, created["id"])
            export.status, export.progress = "running", 88
            await db.commit()
        # Periodic recovery also reconciles jobs that already failed before restart.
        await _recover_stale((kind,), ())
        await _recover_stale((kind,), ())

    asyncio.run(run())
    result = client.get(f"/api/material-exports/{created['id']}", headers=headers).json()
    assert result["status"] == "failed"
    assert result["error"] == "database temporarily unavailable"
    retry = client.post(f"/api/tasks/{task_id}/{endpoint}", headers=headers)
    assert retry.status_code == 202, retry.text
    assert retry.json()["id"] != created["id"]


def test_failure_persistence_updates_export_in_same_transaction(client, export_case):
    headers, task_id = export_case
    created = client.post(f"/api/tasks/{task_id}/material-exports", headers=headers).json()

    async def run():
        async with session_factory() as db:
            job = jobs._from_model(await db.get(GenerationJobModel, created["jobId"]))
        job.status, job.phase, job.error = "failed", "failed", "upload interrupted"
        await jobs._persist(job)

    asyncio.run(run())
    result = client.get(f"/api/material-exports/{created['id']}", headers=headers).json()
    assert result["status"] == "failed"
    assert result["error"] == "upload interrupted"


def test_material_export_replays_only_expired_lease_and_stops_after_limit(client, export_case):
    headers, task_id = export_case
    created = client.post(f"/api/tasks/{task_id}/material-exports", headers=headers).json()

    async def run():
        for attempt, expired, expected in [(1, False, (0, 0)), (1, True, (1, 0)), (3, True, (0, 1))]:
            async with session_factory() as db:
                model = await db.get(GenerationJobModel, created["jobId"])
                model.status, model.attempt = "running", attempt
                model.lease_expires_at = utcnow() + timedelta(seconds=-10 if expired else 300)
                export = await db.get(MaterialExportModel, created["id"])
                export.status = "running"
                await db.commit()
            assert await _recover_stale(("export",), ()) == expected
        async with session_factory() as db:
            export = await db.get(MaterialExportModel, created["id"])
            assert export.status == "failed"
            assert export.finished_at is not None

    asyncio.run(run())
