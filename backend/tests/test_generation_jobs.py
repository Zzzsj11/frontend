"""媒体生成任务稳固性：供应商 taskId 落库、重启恢复、轮询容错、后台对账同步"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from conftest import TEST_DB


def _insert_job(
    job_id: str,
    *,
    kind: str = "image",
    status: str = "queued",
    provider_task_id: str | None = None,
    created_at: datetime | None = None,
) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    created = (created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S.%f")
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute(
            "INSERT INTO generation_jobs (id, kind, status, progress, request, attempt, provider, provider_task_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, kind, status, 10, "{}", 1, "yinghe" if provider_task_id else None, provider_task_id, created, now),
        )
        connection.commit()
    finally:
        connection.close()


def _job_row(job_id: str) -> dict:
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone())
    finally:
        connection.close()


async def test_set_provider_task_persists_immediately(client) -> None:
    from app.jobs import jobs as job_manager

    _insert_job("job-provider-task")
    job = await job_manager.get("job-provider-task")
    assert job is not None
    await job_manager.set_provider_task(job, "yinghe", "pt-123", idempotency_key="idem-1")
    row = _job_row("job-provider-task")
    assert row["provider"] == "yinghe"
    assert row["provider_task_id"] == "pt-123"
    assert row["idempotency_key"] == "idem-1"
    cached = await job_manager.get("job-provider-task")
    assert cached is not None and cached.provider_task_id == "pt-123"


class _FakeResponse:
    def __init__(self, payload: dict | None = None, *, boom: bool = False) -> None:
        self._payload = payload or {}
        self._boom = boom

    def raise_for_status(self) -> None:
        if self._boom:
            import httpx

            raise httpx.ConnectError("connection reset")

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)

    async def get(self, _url: str, headers=None) -> _FakeResponse:
        return self._responses.pop(0)


async def test_poll_tolerates_transient_errors_until_limit() -> None:
    from app.jobs import Job
    from app.providers import POLL_MAX_CONSECUTIVE_ERRORS, ProviderError, _poll

    flaky = _FakeClient(
        [
            _FakeResponse(boom=True),
            _FakeResponse(boom=True),
            _FakeResponse({"code": 200, "data": {"status": "SUCCESS", "progress": 100}}),
        ]
    )
    data = await _poll(flaky, "http://provider", {}, Job(id="job-poll-ok", kind="image"), timeout_seconds=60, interval_seconds=0)
    assert data["status"] == "SUCCESS"

    failing = _FakeClient([_FakeResponse(boom=True) for _ in range(POLL_MAX_CONSECUTIVE_ERRORS + 1)])
    with pytest.raises(ProviderError, match="连续失败"):
        await _poll(failing, "http://provider", {}, Job(id="job-poll-bad", kind="image"), timeout_seconds=60, interval_seconds=0)


async def test_recover_stale_jobs_resumes_recent_and_fails_orphans(client) -> None:
    from app.jobs import jobs as job_manager

    # 清场：前序测试遗留的活跃任务先收编，避免干扰精确断言
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute("UPDATE generation_jobs SET status = 'failed' WHERE status IN ('queued', 'running')")
        connection.commit()
    finally:
        connection.close()

    _insert_job("job-orphan", status="running")
    _insert_job("job-expired", status="running", provider_task_id="pt-old", created_at=datetime.now(timezone.utc) - timedelta(hours=3))
    _insert_job("job-resumable", status="running", provider_task_id="pt-new")

    resumed: list[str] = []

    async def fake_runner(job) -> dict:
        resumed.append(job.id)
        return {"ok": True}

    result = await job_manager.recover_stale_jobs(fake_runner)
    assert result == {"resumed": 1, "failed": 2}
    for _ in range(100):
        if _job_row("job-resumable")["status"] == "succeeded":
            break
        await asyncio.sleep(0.05)
    assert resumed == ["job-resumable"]
    assert _job_row("job-resumable")["status"] == "succeeded"
    assert "中断" in _job_row("job-orphan")["error"]
    assert "过期" in _job_row("job-expired")["error"]


def test_admin_jobs_collects_tasks_with_filters_and_pagination(client) -> None:
    _insert_job("job-admin-img", kind="image", status="failed", provider_task_id="pt-img-1")
    _insert_job("job-admin-vid", kind="video", status="succeeded", provider_task_id="pt-vid-1")

    listed = client.get("/api/admin/jobs")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 2
    item = next(row for row in body["items"] if row["id"] == "job-admin-img")
    assert item["providerTaskId"] == "pt-img-1"
    assert item["provider"] == "yinghe"
    assert "stale" in item and "durationSeconds" in item

    by_kind = client.get("/api/admin/jobs?kind=video").json()
    assert all(row["kind"] == "video" for row in by_kind["items"])
    by_status = client.get("/api/admin/jobs?status=failed").json()
    assert all(row["status"] == "failed" for row in by_status["items"])
    by_query = client.get("/api/admin/jobs?q=pt-vid-1").json()
    assert [row["id"] for row in by_query["items"]] == ["job-admin-vid"]
    first_page = client.get("/api/admin/jobs?page=1&page_size=1").json()
    assert len(first_page["items"]) == 1 and first_page["total"] == first_page["total"]


def test_admin_job_sync_requires_provider_task_id(client) -> None:
    _insert_job("job-sync-no-task", status="failed")
    response = client.post("/api/admin/jobs/job-sync-no-task/sync")
    assert response.status_code == 422


def test_admin_job_sync_marks_failed_from_provider(client, monkeypatch) -> None:
    from app import admin

    _insert_job("job-sync-fail", status="running", provider_task_id="pt-fail")

    async def fake_query(kind: str, task_id: str) -> dict:
        return {"status": "FAILED", "failReason": "内容审核未通过"}

    monkeypatch.setattr(admin, "query_provider_task", fake_query)
    response = client.post("/api/admin/jobs/job-sync-fail/sync")
    assert response.status_code == 200
    assert response.json()["action"] == "failed"
    row = _job_row("job-sync-fail")
    assert row["status"] == "failed"
    assert "内容审核未通过" in row["error"]


def test_admin_job_sync_recovers_success_result(client, monkeypatch) -> None:
    from app import admin

    _insert_job("job-sync-recover", status="running", provider_task_id="pt-success")

    async def fake_query(kind: str, task_id: str) -> dict:
        return {"status": "SUCCESS", "progress": 100}

    async def fake_store(job, data: dict) -> dict:
        return {"provider": "yinghe", "providerTaskId": job.provider_task_id, "urls": ["https://cdn.example.com/a.png"], "usage": {}}

    monkeypatch.setattr(admin, "query_provider_task", fake_query)
    monkeypatch.setattr(admin, "store_provider_result", fake_store)
    response = client.post("/api/admin/jobs/job-sync-recover/sync")
    assert response.status_code == 200
    assert response.json()["action"] == "recovered"
    row = _job_row("job-sync-recover")
    assert row["status"] == "succeeded"
    assert row["progress"] == 100


def test_admin_job_sync_resumes_orphan_running_at_provider(client, monkeypatch) -> None:
    from types import SimpleNamespace

    from app import admin

    _insert_job("job-sync-resume", status="running", provider_task_id="pt-running")

    async def fake_query(kind: str, task_id: str) -> dict:
        return {"status": "RUNNING", "progress": 40}

    class FakeManager:
        def is_active(self, _job_id: str) -> bool:
            return False

        async def resume_one(self, job_id: str, _runner) -> object:
            return SimpleNamespace(id=job_id)

    monkeypatch.setattr(admin, "query_provider_task", fake_query)
    monkeypatch.setattr(admin, "job_manager", FakeManager())
    response = client.post("/api/admin/jobs/job-sync-resume/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "resumed"
    assert body["providerStatus"] == "RUNNING"
