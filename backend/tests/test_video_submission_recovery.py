"""Submission replay must not create another paid video job or consume quota."""

import sqlite3
from unittest.mock import AsyncMock

import pytest
from conftest import TEST_DB


@pytest.fixture
def video_submission(client, monkeypatch):
    from app import main
    from app.jobs import jobs

    dispatch = AsyncMock()
    quota = AsyncMock(return_value=1)
    balance = AsyncMock(return_value={})
    monkeypatch.setattr(jobs, "dispatch", dispatch)
    monkeypatch.setattr(main, "consume_daily_quota", quota)
    monkeypatch.setattr(main, "ensure_video_batch_balance", balance)
    project = client.post("/api/projects", json={"name": "video-replay-test"}).json()
    task = client.post(
        f"/api/projects/{project['id']}/storyboards/general/random",
        json={"genre": "流行歌曲", "empty_shot_count": 1, "character_shot_count": 0, "total_duration": 5, "video_model": "doubao-seedance-2.0-all-in-one"},
    ).json()
    body = {
        "prompt": "公园里的树叶随风摇动",
        "duration": 5,
        "model": "doubao-seedance-2.0-all-in-one",
        "project_task_id": task["taskId"],
        "storyboard_line_id": task["lines"][0]["id"],
        "request_id": "intent-first",
    }
    yield body, dispatch, quota, balance
    client.delete(f"/api/projects/{project['id']}")


def set_status(jid, status):
    with sqlite3.connect(TEST_DB) as db:
        db.execute("UPDATE generation_jobs SET status=? WHERE id=?", (status, jid))


def test_batch_replay_reuses_active_and_finished_job_without_dispatch_or_quota(client, video_submission):
    body, dispatch, quota, balance = video_submission
    first = client.post("/api/generations/videos/batch", json={"items": [body]})
    assert first.status_code == 202, first.text
    jid = first.json()["jobs"][0]["id"]
    for state in ("queued", "succeeded"):
        set_status(jid, state)
        replay = client.post("/api/generations/videos/batch", json={"items": [body]})
        assert replay.status_code == 202, replay.text
        assert replay.json()["jobs"][0]["id"] == jid
    assert dispatch.await_count == quota.await_count == balance.await_count == 1
    conflict = client.post("/api/generations/videos", json={**body, "prompt": "changed input"})
    assert conflict.status_code == 409
    # A deliberate new version after completion is allowed.
    new = client.post("/api/generations/videos", json={**body, "request_id": "intent-new"})
    assert new.status_code == 202 and new.json()["id"] != jid
    assert dispatch.await_count == quota.await_count == 2
    replay_old = client.post("/api/generations/videos", json=body)
    assert replay_old.status_code == 202 and replay_old.json()["id"] == jid
    assert dispatch.await_count == quota.await_count == 2


def test_active_same_parameters_reused_and_different_parameters_conflict(client, video_submission):
    body, dispatch, quota, _ = video_submission
    first = client.post("/api/generations/videos", json=body).json()
    second = client.post("/api/generations/videos", json={**body, "request_id": "another-tab"})
    assert second.status_code == 202 and second.json()["id"] == first["id"]
    conflict = client.post("/api/generations/videos", json={**body, "request_id": "different", "prompt": "another scene"})
    assert conflict.status_code == 409
    assert dispatch.await_count == quota.await_count == 1


def test_latest_intent_controls_restore_without_erasing_older_paid_jobs(client, video_submission):
    body, _, _, _ = video_submission
    old = client.post("/api/generations/videos", json=body).json()["id"]
    set_status(old, "succeeded")
    new = client.post("/api/generations/videos", json={**body, "request_id": "new-version"}).json()["id"]
    set_status(old, "running")  # historical multiple submissions
    active = client.get(f"/api/tasks/{body['project_task_id']}/generations/active").json()
    assert [item["id"] for item in active] == [new]
    set_status(new, "succeeded")
    assert client.get(f"/api/tasks/{body['project_task_id']}/generations/active").json() == []
    with sqlite3.connect(TEST_DB) as db:
        assert db.execute("SELECT status FROM generation_jobs WHERE id=?", (old,)).fetchone()[0] == "running"


def test_uncertain_legacy_timeout_is_not_treated_as_safe_to_resubmit(client, video_submission):
    body, dispatch, quota, _ = video_submission
    jid = client.post("/api/generations/videos", json=body).json()["id"]
    with sqlite3.connect(TEST_DB) as db:
        db.execute(
            "UPDATE generation_jobs SET status='failed',phase='failed',provider_task_id='original-platform-job',error='等待超过2小时，请核查原任务；未重新提交' WHERE id=?", (jid,)
        )
    replay = client.post("/api/generations/videos", json={**body, "request_id": "another-intent"})
    assert replay.status_code == 202 and replay.json()["id"] == jid
    assert replay.json()["phase"] == "manual_review"
    active = client.get(f"/api/tasks/{body['project_task_id']}/generations/active").json()
    assert active[0]["phase"] == "manual_review"
    assert dispatch.await_count == quota.await_count == 1
