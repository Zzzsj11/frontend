"""Recovery never submits a model call; persisted leases fence crash/restart races."""

import asyncio
import sqlite3
from unittest.mock import AsyncMock

import pytest
from conftest import TEST_DB
from test_video_submission_recovery import video_submission  # noqa: F401


@pytest.fixture
def recovery(client, video_submission, monkeypatch):  # noqa: F811
    from app import providers, video_metadata
    from app import video_reconciliation as recovery

    body, dispatch, quota, balance = video_submission
    jid = client.post("/api/generations/videos", json=body).json()["id"]
    with sqlite3.connect(TEST_DB) as db:
        db.execute("UPDATE generation_jobs SET status='failed',phase='manual_review',provider='all-in-one',provider_task_id='original-id',lease_expires_at=NULL WHERE id=?", (jid,))
    query = AsyncMock(return_value={"status": "SUCCEEDED"})
    store = AsyncMock(
        return_value={
            "videoUrl": "https://tos.example/original.mp4",
            "coverUrl": "https://tos.example/original.jpg",
            "provider": "all-in-one",
            "providerTaskId": "original-id",
            "duration": 5,
        }
    )
    monkeypatch.setattr(providers, "query_provider_task", query)
    monkeypatch.setattr(providers, "store_provider_result", store)
    monkeypatch.setattr(video_metadata, "probe_video_url", AsyncMock(return_value={}))
    yield recovery, jid, body, query, store
    assert dispatch.await_count == quota.await_count == 1
    assert balance.await_count == 0


def test_automatic_recovery_atomic_and_idempotent(client, recovery):
    module, jid, body, query, store = recovery
    snapshot = client.post("/api/generations/status", json={"ids": [jid]})
    assert snapshot.json()[0]["phase"] == "auto_reconciling"
    assert snapshot.json()[0]["status"] == "running"
    assert not snapshot.json()[0]["retryAllowed"]
    # API retry is blocked before dispatch/quota even with changed parameters.
    retry = client.post("/api/generations/videos", json={**body, "request_id": "retry", "prompt": "changed"})
    assert retry.status_code == 409 and "自动核对" in retry.text

    async def run():
        assert (await module.reconcile_one(jid))["action"] == "recovered"
        assert (await module.reconcile_one(jid))["action"] == "skipped"

    asyncio.run(run())
    assert query.await_count == store.await_count == 1
    query.assert_awaited_with("video", "original-id", "all-in-one")
    with sqlite3.connect(TEST_DB) as db:
        assert db.execute("SELECT status,phase,worker_id FROM generation_jobs WHERE id=?", (jid,)).fetchone() == ("succeeded", "succeeded", None)
        assert db.execute("SELECT count(*) FROM shot_assets WHERE generation_job_id=?", (jid,)).fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM token_usage_records WHERE generation_job_id=?", (jid,)).fetchone()[0] == 1


def test_lease_fences_old_process_and_resumes_after_expiry(client, recovery):
    from app.jobs import JobExpiredError, jobs

    module, jid, _, query, store = recovery

    async def run():
        old = await module.claim(jid)
        assert await module.claim(jid) is None
        with sqlite3.connect(TEST_DB) as db:
            db.execute("UPDATE generation_jobs SET lease_expires_at='2000-01-01' WHERE id=?", (jid,))
        new = await module.claim(jid)
        assert new.worker_id != old.worker_id
        with pytest.raises(JobExpiredError):
            await jobs.finalize_success(old, store.return_value)
        assert (await module.recover(new))["action"] == "recovered"

    asyncio.run(run())
    assert query.await_count == 1


@pytest.mark.parametrize("response", [{"status": "RUNNING"}, {"status": "FAILED"}, RuntimeError("network"), {"status": "SUCCEEDED"}])
def test_pending_and_archive_failure_stay_blocked_and_scheduled(client, recovery, response):
    module, jid, body, query, store = recovery
    if isinstance(response, Exception):
        query.side_effect = response
    else:
        query.return_value = response
    store.side_effect = RuntimeError("archive unavailable")
    asyncio.run(module.reconcile_one(jid))
    with sqlite3.connect(TEST_DB) as db:
        state = db.execute("SELECT status,phase,reconciliation_next_at,worker_id FROM generation_jobs WHERE id=?", (jid,)).fetchone()
        assert state[0:2] == ("failed", "auto_reconciling") and state[2] and state[3] is None
    assert client.post("/api/generations/videos", json={**body, "request_id": "retry"}).status_code == 409


def test_no_platform_id_or_deleted_project_not_claimed(client, recovery):
    module, jid, _, query, _ = recovery
    with sqlite3.connect(TEST_DB) as db:
        db.execute("UPDATE generation_jobs SET provider_task_id=NULL WHERE id=?", (jid,))
    assert asyncio.run(module.claim(jid)) is None
    with sqlite3.connect(TEST_DB) as db:
        db.execute("UPDATE generation_jobs SET provider_task_id='original-id' WHERE id=?", (jid,))
        db.execute("UPDATE projects SET deleted_at=CURRENT_TIMESTAMP WHERE id=(SELECT project_id FROM generation_jobs WHERE id=?)", (jid,))
    assert asyncio.run(module.claim(jid)) is None
    query.assert_not_awaited()


def test_transaction_rolls_back_asset_and_usage_on_billing_failure(client, recovery, monkeypatch):
    from app import video_billing

    module, jid, _, _, _ = recovery
    monkeypatch.setattr(video_billing, "reconcile_video_job", AsyncMock(side_effect=RuntimeError("db interruption")))
    assert asyncio.run(module.reconcile_one(jid))["action"] == "deferred"
    with sqlite3.connect(TEST_DB) as db:
        assert db.execute("SELECT count(*) FROM shot_assets WHERE generation_job_id=?", (jid,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM token_usage_records WHERE generation_job_id=?", (jid,)).fetchone()[0] == 0
        assert db.execute("SELECT status FROM generation_jobs WHERE id=?", (jid,)).fetchone()[0] == "failed"


def test_late_original_is_archived_without_replacing_newer_video(client, recovery):
    from app.database import session_factory
    from app.models import GenerationJobModel, ShotAssetModel

    module, jid, _, _, _ = recovery

    async def run():
        async with session_factory() as db:
            old = await db.get(GenerationJobModel, jid)
            newer = GenerationJobModel(
                id=jid + "-new",
                kind="video",
                status="succeeded",
                user_id=old.user_id,
                project_id=old.project_id,
                project_task_id=old.project_task_id,
                storyboard_line_id=old.storyboard_line_id,
            )
            db.add(newer)
            await db.flush()
            db.add(
                ShotAssetModel(
                    id=jid + "-asset",
                    storyboard_line_id=old.storyboard_line_id,
                    generation_job_id=newer.id,
                    video_url="https://tos.example/new.mp4",
                    duration=3,
                    cover_url="https://tos.example/new.jpg",
                    is_current=True,
                )
            )
            await db.commit()
        assert (await module.reconcile_one(jid))["action"] == "recovered"

    asyncio.run(run())
    with sqlite3.connect(TEST_DB) as db:
        assert db.execute("SELECT is_current FROM shot_assets WHERE generation_job_id=?", (jid,)).fetchone()[0] == 0
        assert db.execute("SELECT is_current FROM shot_assets WHERE id=?", (jid + "-asset",)).fetchone()[0] == 1


def test_late_inline_runner_cannot_write_after_recovery_claim(client, recovery):
    from app.jobs import JobExpiredError, jobs

    module, jid, _, _, store = recovery

    async def run():
        stale = await jobs.get(jid)
        claimed = await module.claim(jid)
        stale.result = store.return_value
        stale.status = "succeeded"
        with pytest.raises(JobExpiredError):
            await jobs._persist_asset(stale)
        await jobs._persist(stale)
        assert (await module.recover(claimed))["action"] == "recovered"
        stale.status = "failed"
        await jobs._persist(stale)
        assert (await jobs.get(jid)).status == "succeeded"

    asyncio.run(run())
