"""媒体生成任务稳固性：供应商 taskId 落库、重启恢复、轮询容错、后台对账同步"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from conftest import TEST_DB


def test_job_manager_keeps_excess_provider_calls_queued(monkeypatch) -> None:
    from app.jobs import Job, JobManager

    async def scenario() -> None:
        manager = JobManager({"video": asyncio.Semaphore(2)})
        persisted: list[tuple[str, str]] = []
        releases = [asyncio.Event() for _ in range(3)]
        started: list[str] = []

        async def fake_persist(job: Job) -> None:
            persisted.append((job.id, job.status))

        async def fake_persist_asset(_job: Job) -> None:
            return None

        monkeypatch.setattr(manager, "_persist", fake_persist)
        monkeypatch.setattr(manager, "_persist_asset", fake_persist_asset)

        jobs = [Job(id=f"queued-{index}", kind="video") for index in range(3)]

        def runner(index: int):
            async def run(job: Job) -> dict:
                started.append(job.id)
                await releases[index].wait()
                return {"videoUrl": f"/{job.id}.mp4"}

            return run

        tasks = [asyncio.create_task(manager._run(job, runner(index))) for index, job in enumerate(jobs)]
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert started == ["queued-0", "queued-1"]
        assert [job.status for job in jobs] == ["running", "running", "queued"]

        releases[0].set()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert started == ["queued-0", "queued-1", "queued-2"]
        assert jobs[2].status == "running"

        releases[1].set()
        releases[2].set()
        await asyncio.gather(*tasks)
        assert all(job.status == "succeeded" for job in jobs)
        assert ("queued-2", "queued") not in persisted

    asyncio.run(scenario())


def test_job_manager_applies_independent_model_execution_pools(monkeypatch) -> None:
    from app.jobs import Job, JobManager

    async def scenario() -> None:
        manager = JobManager()
        releases = {name: asyncio.Event() for name in ("h3", "seedance")}
        started: list[str] = []

        async def fake_persist(_job: Job) -> None:
            return None

        async def fake_persist_asset(_job: Job) -> None:
            return None

        monkeypatch.setattr(manager, "_persist", fake_persist)
        monkeypatch.setattr(manager, "_persist_asset", fake_persist_asset)

        async def runner(job: Job) -> dict:
            pool = str((job.request or {})["_executionPool"])
            started.append(job.id)
            await releases[pool].wait()
            return {"videoUrl": f"/{job.id}.mp4"}

        jobs = [Job(id=f"h3-{index}", kind="video", request={"_executionPool": "h3", "_executionConcurrency": 2}) for index in range(3)] + [
            Job(id=f"seedance-{index}", kind="video", request={"_executionPool": "seedance", "_executionConcurrency": 4}) for index in range(3)
        ]
        tasks = [asyncio.create_task(manager._run(job, runner)) for job in jobs]
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert started[:2] == ["h3-0", "h3-1"]
        assert "h3-2" not in started
        assert {"seedance-0", "seedance-1", "seedance-2"}.issubset(started)

        releases["h3"].set()
        releases["seedance"].set()
        await asyncio.gather(*tasks)
        assert "h3-2" in started

    asyncio.run(scenario())


def test_model_execution_pool_is_shared_across_job_managers(monkeypatch) -> None:
    from app import jobs as jobs_module
    from app.jobs import Job, JobManager

    async def scenario() -> None:
        held: set[str] = set()
        serial = 0

        async def acquire(_pool: str, limit: int, _ttl: int) -> str | None:
            nonlocal serial
            if len(held) >= limit:
                return None
            serial += 1
            token = f"lease-{serial}"
            held.add(token)
            return token

        async def release(_pool: str, token: str) -> None:
            held.discard(token)

        async def renew(_pool: str, _token: str, _ttl: int) -> None:
            return None

        monkeypatch.setattr(jobs_module, "acquire_execution_lease", acquire)
        monkeypatch.setattr(jobs_module, "release_execution_lease", release)
        monkeypatch.setattr(jobs_module, "renew_execution_lease", renew)
        managers = [JobManager(), JobManager()]
        for manager in managers:
            monkeypatch.setattr(manager, "_persist", lambda _job: asyncio.sleep(0))
            monkeypatch.setattr(manager, "_persist_asset", lambda _job: asyncio.sleep(0))
        gate = asyncio.Event()
        started: list[str] = []

        async def runner(job: Job) -> dict:
            started.append(job.id)
            await gate.wait()
            return {}

        request = {"_executionPool": "shared", "_executionConcurrency": 1}
        tasks = [
            asyncio.create_task(managers[0]._run(Job(id="one", kind="video", request=request), runner)),
            asyncio.create_task(managers[1]._run(Job(id="two", kind="video", request=request), runner)),
        ]
        await asyncio.sleep(0.05)
        assert len(started) == 1
        gate.set()
        await asyncio.gather(*tasks)
        assert sorted(started) == ["one", "two"]

    asyncio.run(scenario())


def test_uncertain_provider_submission_requires_manual_review(monkeypatch) -> None:
    from app import jobs as jobs_module
    from app.jobs import Job, JobManager

    async def scenario() -> None:
        manager = JobManager()

        async def fake_persist(_job: Job) -> None:
            return None

        monkeypatch.setattr(manager, "_persist", fake_persist)
        monkeypatch.setattr(jobs_module, "add_token_usage", lambda *_args, **_kwargs: None)

        async def uncertain(job: Job) -> dict:
            job.phase = "submitting_provider"
            raise TimeoutError("response lost")

        job = Job(id="uncertain-provider", kind="video")
        await manager._run(job, uncertain)
        assert job.status == "failed"
        assert job.phase == "manual_review"
        assert "不支持幂等重提" in (job.error or "")

    asyncio.run(scenario())


def test_definite_provider_rejection_is_not_marked_for_manual_review(monkeypatch) -> None:
    from app import jobs as jobs_module
    from app.jobs import Job, JobManager
    from app.providers import ProviderRejectedError

    async def scenario() -> None:
        manager = JobManager()

        async def fake_persist(_job: Job) -> None:
            return None

        monkeypatch.setattr(manager, "_persist", fake_persist)
        monkeypatch.setattr(jobs_module, "add_token_usage", lambda *_args, **_kwargs: None)

        async def rejected(job: Job) -> dict:
            job.phase = "submitting_provider"
            raise ProviderRejectedError("额度已用尽")

        job = Job(id="rejected-provider", kind="image")
        await manager._run(job, rejected)
        assert job.status == "failed"
        assert job.phase == "failed"
        assert job.error == "额度已用尽"

    asyncio.run(scenario())


def test_external_worker_reconstructs_media_request(monkeypatch) -> None:
    from app import worker
    from app.jobs import Job

    captured = {}

    async def fake_generate(request, job):
        captured.update(request.model_dump())
        return {"job": job.id}

    monkeypatch.setattr(worker, "generate_image", fake_generate)
    job = Job(
        id="job-worker-image",
        kind="image",
        request={"prompt": "测试画面", "model": "image-model", "_provider": "yinghe", "_executionPool": "images"},
    )
    result = asyncio.run(worker._runner(job)(job))

    assert result == {"job": "job-worker-image"}
    assert captured["prompt"] == "测试画面"
    assert captured["model"] == "image-model"
    assert "_provider" not in captured


def test_external_worker_dispatches_chat_session(monkeypatch) -> None:
    from app import worker
    from app.jobs import Job

    async def fake_run(session_id, job):
        return {"sessionId": session_id, "jobId": job.id}

    monkeypatch.setattr(worker.chat_manager, "run_persisted", fake_run)
    job = Job(id="job-worker-chat", kind="chat", request={"session_id": "chat-123"})

    assert asyncio.run(worker._runner(job)(job)) == {"sessionId": "chat-123", "jobId": "job-worker-chat"}


def test_nested_provider_usage_is_normalized() -> None:
    from app.token_usage import normalize_usage

    normalized = normalize_usage({"taskId": "image-task", "rawUsage": {"input_tokens": 7, "output_tokens": 3072, "cached_tokens": 3, "images": 1}})

    assert normalized["inputTokens"] == 7
    assert normalized["outputTokens"] == 3072
    assert normalized["cachedInputTokens"] == 3
    assert normalized["totalTokens"] == 3079


def test_job_cache_is_best_effort_when_redis_is_unavailable(monkeypatch) -> None:
    from app import redis_store

    class BrokenRedis:
        async def set(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

        async def get(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

        async def publish(self, *_args, **_kwargs):
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(redis_store, "redis", BrokenRedis())

    async def scenario() -> None:
        await redis_store.cache_job("job-offline", {"status": "queued"})
        await redis_store.notify_worker("ass_outline")
        assert await redis_store.get_cached_job("job-offline") is None

    asyncio.run(scenario())


def test_worker_wakeup_wait_blocks_until_poll_timeout(monkeypatch) -> None:
    from app import redis_store

    class IdlePubSub:
        async def subscribe(self, *_channels):
            return None

        async def listen(self):
            yield {"type": "subscribe"}
            await asyncio.Event().wait()

        async def aclose(self):
            return None

    class IdleRedis:
        def pubsub(self):
            return IdlePubSub()

    monkeypatch.setattr(redis_store, "redis", IdleRedis())

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        started = loop.time()
        await redis_store.wait_for_worker_wakeup(0.03)
        assert loop.time() - started >= 0.02

    asyncio.run(scenario())


def test_h3_video_provider_archives_output(monkeypatch) -> None:
    from app import providers
    from app.jobs import Job
    from app.schemas import VideoGenerationCreate

    async def scenario() -> dict:
        submitted = {}

        async def fake_submit(**kwargs):
            submitted.update(kwargs)
            return {"taskId": "rh-h3-1", "status": "RUNNING"}

        async def fake_upload(_content: bytes, _filename: str):
            return {"fileName": "openapi/first-frame.png"}

        class FakeResponse:
            content = b"image"

            def raise_for_status(self):
                return None

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *_args):
                return None

            async def get(self, _url):
                return FakeResponse()

        async def fake_query(_task_id: str):
            return {
                "taskId": "rh-h3-1",
                "status": "SUCCESS",
                "results": [{"url": "https://rh.test/h3.mp4", "outputType": "mp4"}],
                "usage": {"consumeCoins": "12"},
            }

        async def fake_set_provider_task(job, provider, task_id, **_kwargs):
            job.provider, job.provider_task_id = provider, task_id

        async def fake_mark_provider_submitting(job):
            job.phase = "submitting_provider"

        async def fake_progress(_job, _progress):
            return None

        async def fake_import(_url, _prefix, _filename):
            return "https://tos.test/h3.mp4"

        async def fake_cover(_url, _task_id, _user_id):
            return "https://tos.test/h3.jpg", "https://tos.test/h3-thumb.jpg"

        monkeypatch.setattr(providers, "runninghub_submit_first_frame_task", fake_submit)
        monkeypatch.setattr(providers, "runninghub_upload_media", fake_upload)
        monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
        monkeypatch.setattr(providers, "runninghub_query_task", fake_query)
        monkeypatch.setattr(providers.jobs, "set_provider_task", fake_set_provider_task)
        monkeypatch.setattr(providers.jobs, "mark_provider_submitting", fake_mark_provider_submitting)
        monkeypatch.setattr(providers.jobs, "update_progress", fake_progress)
        monkeypatch.setattr(providers, "import_remote", fake_import)
        monkeypatch.setattr(providers, "_video_first_frame", fake_cover)
        monkeypatch.setattr(providers, "H3_POLL_INTERVAL_SECONDS", 0)
        request = VideoGenerationCreate(
            prompt="故宫舞蹈",
            duration=5,
            ratio="16:9",
            resolution="720p",
            image_urls=["https://tos.test/person.jpg"],
            model="minimax-h3-runninghub",
        )
        job = Job(
            id="job-h3",
            kind="video",
            user_id="user-1",
            request={
                "model": "minimax-h3-runninghub",
                "duration": 5,
                "ratio": "16:9",
                "image_urls": ["https://tos.test/person.jpg"],
                "_provider": "runninghub",
            },
        )
        result = await providers.generate_video(request, job)
        assert submitted["image"] == "openapi/first-frame.png"
        assert submitted["megapixels"] == 0.9
        return result

    result = asyncio.run(scenario())
    assert result["provider"] == "runninghub"
    assert result["videoUrl"] == "https://tos.test/h3.mp4"
    assert result["usage"] == {"consumeCoins": "12"}
    assert result["generationMode"] == "first_frame"


def _insert_job(
    job_id: str,
    *,
    kind: str = "image",
    status: str = "queued",
    provider_task_id: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> None:
    now = (updated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S.%f")
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


def test_provider_poll_scheduler_spreads_200_tasks_over_30_ticks() -> None:
    from app.jobs import Job
    from app.providers import ProviderPollScheduler, _poll_batch_size, _ScheduledPoll

    async def scenario() -> None:
        scheduler = ProviderPollScheduler(coverage_seconds=30)
        loop = asyncio.get_running_loop()
        for index in range(200):
            job = Job(id=f"provider-{index}", kind="video")
            scheduler._entries[job.id] = _ScheduledPoll(job, "https://provider.test", {}, float("inf"), loop.create_future())
            scheduler._queue.append(job.id)

        assert _poll_batch_size(200, 30) == 7
        batches = [scheduler._take_batch() for _ in range(30)]
        assert [len(batch) for batch in batches[:28]] == [7] * 28
        assert len(batches[28]) == 200 - 7 * 28
        assert len(batches[29]) == 0
        assert len({entry.job.id for batch in batches for entry in batch}) == 200

    asyncio.run(scenario())


def test_gpt_image_timeout_is_ten_minutes_and_survives_worker_restart(monkeypatch) -> None:
    from app import providers
    from app.jobs import Job

    assert providers.IMAGE_POLL_TIMEOUT_SECONDS == 600
    monkeypatch.setattr(providers.time, "time", lambda: 1_000.0)
    fresh = Job(id="image-fresh", kind="image", provider_submitted_at=700.0)
    expired = Job(id="image-expired", kind="image", provider_submitted_at=399.0)

    assert providers._remaining_provider_timeout(fresh, providers.IMAGE_POLL_TIMEOUT_SECONDS) == 300.0
    assert providers._remaining_provider_timeout(expired, providers.IMAGE_POLL_TIMEOUT_SECONDS) == 0.0


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


async def test_worker_requeues_replayable_storyboard_job_with_bounded_attempts(client) -> None:
    from app.worker import _recover_stale

    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    _insert_job("job-ass-replay", kind="ass_outline", status="running", updated_at=stale)

    resumed, failed = await _recover_stale(("ass_outline",), ())

    assert (resumed, failed) == (1, 0)
    row = _job_row("job-ass-replay")
    assert row["status"] == "queued"
    assert row["attempt"] == 2

    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute("UPDATE generation_jobs SET status = 'running', attempt = 3, updated_at = ? WHERE id = ?", (stale.strftime("%Y-%m-%d %H:%M:%S.%f"), "job-ass-replay"))
        connection.commit()
    finally:
        connection.close()

    resumed, failed = await _recover_stale(("ass_outline",), ())
    assert (resumed, failed) == (0, 1)
    row = _job_row("job-ass-replay")
    assert row["status"] == "failed"
    assert "重试次数" in row["error"]


async def test_worker_claim_records_owner_and_lease(client) -> None:
    from app.worker import _claim

    _insert_job("job-lease-claim", kind="chat")
    claimed = await _claim(("chat",), (), "worker-test-owner")
    assert claimed is not None and claimed.id == "job-lease-claim"
    row = _job_row("job-lease-claim")
    assert row["worker_id"] == "worker-test-owner"
    assert row["phase"] == "claimed"
    assert row["claimed_at"] and row["heartbeat_at"] and row["lease_expires_at"]


def test_worker_claim_priority_balances_active_jobs_across_project_tasks() -> None:
    from types import SimpleNamespace

    from app.worker import _claim_priority

    now = datetime.now(timezone.utc)
    busy = SimpleNamespace(project_task_id="task-busy", created_at=now - timedelta(minutes=1))
    idle = SimpleNamespace(project_task_id="task-idle", created_at=now)

    selected = min([busy, idle], key=lambda row: _claim_priority(row, {"task-busy": 4}))

    assert selected is idle


async def test_worker_recovers_idempotent_submit_but_not_legacy_uncertain_submit(client) -> None:
    from app.worker import _recover_stale

    stale = datetime.now(timezone.utc) - timedelta(minutes=10)
    future = datetime.now(timezone.utc) + timedelta(minutes=2)
    _insert_job("job-live-lease", kind="video", status="running", updated_at=stale)
    _insert_job("job-uncertain-submit", kind="video", status="running", updated_at=stale)
    _insert_job("job-idempotent-image", kind="image", status="running", updated_at=stale)
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute(
            "UPDATE generation_jobs SET lease_expires_at = ?, worker_id = ? WHERE id = ?",
            (future.strftime("%Y-%m-%d %H:%M:%S.%f"), "worker-live", "job-live-lease"),
        )
        connection.execute(
            "UPDATE generation_jobs SET phase = 'submitting_provider', lease_expires_at = ? WHERE id = ?",
            (stale.strftime("%Y-%m-%d %H:%M:%S.%f"), "job-uncertain-submit"),
        )
        connection.execute(
            "UPDATE generation_jobs SET phase = 'submitting_provider', idempotency_key = ?, lease_expires_at = ? WHERE id = ?",
            ("job-idempotent-image:image", stale.strftime("%Y-%m-%d %H:%M:%S.%f"), "job-idempotent-image"),
        )
        connection.commit()
    finally:
        connection.close()

    resumed, failed = await _recover_stale(("image", "video"), ())
    assert (resumed, failed) == (1, 1)
    assert _job_row("job-live-lease")["status"] == "running"
    uncertain = _job_row("job-uncertain-submit")
    assert uncertain["status"] == "failed"
    assert uncertain["phase"] == "manual_review"
    assert "不支持幂等创建" in uncertain["error"]
    replayable = _job_row("job-idempotent-image")
    assert replayable["status"] == "queued"
    assert replayable["phase"] == "queued"
    assert replayable["attempt"] == 2


async def test_recover_stale_storyboard_jobs_marked_failed(client) -> None:
    from app.seed import recover_stale_storyboard_generation

    stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    _insert_job("job-sb-stale", kind="storyboard_line", status="running", created_at=stale_time, updated_at=stale_time)
    _insert_job("job-sb-fresh", kind="storyboard_line", status="running")

    project = client.post("/api/projects", json={"name": "stale-outline-project"}).json()
    task = client.post(
        f"/api/projects/{project['id']}/tasks",
        json={"title": "stale outline", "storyboard_type": "general"},
    ).json()
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute(
            "UPDATE project_tasks SET status = 'outlining', storyboard_config = ?, updated_at = ? WHERE id = ?",
            ('{"outlineProgress":{"phase":"generating","shotsDone":0,"shotsTotal":21}}', stale_time.strftime("%Y-%m-%d %H:%M:%S.%f"), task["id"]),
        )
        connection.commit()
    finally:
        connection.close()

    await recover_stale_storyboard_generation()

    stale_row = _job_row("job-sb-stale")
    assert stale_row["status"] == "failed"
    assert "中断" in stale_row["error"]
    assert _job_row("job-sb-fresh")["status"] == "running"
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        outline = dict(connection.execute("SELECT status, storyboard_config FROM project_tasks WHERE id = ?", (task["id"],)).fetchone())
    finally:
        connection.close()
    assert outline["status"] == "outline_failed"
    assert "大纲生成进程已中断" in json.loads(outline["storyboard_config"])["outlineProgress"]["error"]


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

    async def fake_query(kind: str, task_id: str, provider: str | None = None) -> dict:
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

    async def fake_query(kind: str, task_id: str, provider: str | None = None) -> dict:
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

    async def fake_query(kind: str, task_id: str, provider: str | None = None) -> dict:
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


# ---------- 单用户并发上限（429）与供应商错误友好翻译 ----------


def _insert_owned_job(job_id: str, *, user_id: str, kind: str = "image", status: str = "queued", deleted: bool = False) -> None:
    """带属主的任务插入：_check_concurrency 按 user_id + kind + 活跃状态计数。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute(
            "INSERT INTO generation_jobs (id, kind, status, progress, request, attempt, user_id, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, kind, status, 10, "{}", 1, user_id, now, now, now if deleted else None),
        )
        connection.commit()
    finally:
        connection.close()


def _fail_active_jobs() -> None:
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute("UPDATE generation_jobs SET status = 'failed' WHERE status IN ('queued', 'running')")
        connection.commit()
    finally:
        connection.close()


def test_generation_concurrency_limit_returns_429(client, monkeypatch) -> None:
    from app import main

    user = client.get("/api/auth/me").json()
    # 清场：前序测试遗留的活跃任务先收编，保证计数精确
    _fail_active_jobs()

    async def fake_image(payload, job) -> dict:
        return {"urls": ["https://tos.test/images/ok.png"]}

    async def fake_video(payload, job) -> dict:
        return {"videoUrl": "https://tos.test/videos/ok.mp4", "coverUrl": "https://tos.test/images/ok.png", "duration": 5}

    monkeypatch.setattr(main, "generate_image", fake_image)
    monkeypatch.setattr(main, "generate_video", fake_video)

    try:
        # 上限 200：占满活跃图片任务后，第 201 个被拒（429 在消耗配额之前）
        for index in range(200):
            _insert_owned_job(f"job-conc-img-{index}", user_id=user["id"], kind="image")
        blocked = client.post("/api/generations/images", json={"prompt": "concurrency"})
        assert blocked.status_code == 429
        assert "图片" in blocked.json()["detail"] and "200" in blocked.json()["detail"]

        # 终态与软删除不占额度：一条转 failed、一条软删后可再各进一条
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = 'job-conc-img-0'")
            connection.execute("UPDATE generation_jobs SET deleted_at = datetime('now') WHERE id = 'job-conc-img-1'")
            connection.commit()
        finally:
            connection.close()
        assert client.post("/api/generations/images", json={"prompt": "after-terminal"}).status_code == 202
        assert client.post("/api/generations/images", json={"prompt": "after-soft-delete"}).status_code == 202

        # 类型独立：图片占满不影响视频提交
        assert client.post("/api/generations/videos", json={"prompt": "v", "duration": 5}).status_code == 202

        # 用户隔离：其它用户占满图片额度不影响当前用户
        for index in range(200):
            _insert_owned_job(f"job-conc-other-{index}", user_id="user-not-admin", kind="image")
        assert client.post("/api/generations/images", json={"prompt": "isolation"}).status_code == 202
    finally:
        _fail_active_jobs()
        # 本测试成功提交的请求消耗了 admin 的当日配额，清除避免挤占后续配额断言
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute("DELETE FROM daily_usage_quotas WHERE user_id = ? AND category IN ('image', 'video')", (user["id"],))
            connection.commit()
        finally:
            connection.close()


def test_generation_status_batch_is_owned_and_returns_many_jobs(client) -> None:
    user = client.get("/api/auth/me").json()
    _insert_owned_job("job-batch-one", user_id=user["id"], status="running")
    _insert_owned_job("job-batch-two", user_id=user["id"], kind="video", status="succeeded")
    _insert_owned_job("job-batch-other", user_id="user-not-admin", status="running")

    response = client.post(
        "/api/generations/status",
        json={"ids": ["job-batch-one", "job-batch-two", "job-batch-other"]},
    )
    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {"job-batch-one", "job-batch-two"}
    observed = client.post("/api/generations/observed", json={"ids": ["job-batch-one", "job-batch-two", "job-batch-other"]})
    assert observed.status_code == 200
    assert observed.json()["observed"] == 1
    connection = sqlite3.connect(TEST_DB)
    try:
        own = connection.execute("SELECT first_result_observed_at FROM generation_jobs WHERE id = 'job-batch-two'").fetchone()[0]
        other = connection.execute("SELECT first_result_observed_at FROM generation_jobs WHERE id = 'job-batch-other'").fetchone()[0]
    finally:
        connection.close()
    assert own is not None
    assert other is None


def test_raise_for_status_translates_aigc_error_codes() -> None:
    import httpx

    from app.providers import ProviderError, _raise_for_status

    def make_response(status: int, payload: dict | None) -> httpx.Response:
        request = httpx.Request("POST", "https://provider.test/tasks")
        if payload is None:
            return httpx.Response(status, content=b"<html>bad gateway</html>", request=request)
        return httpx.Response(status, json=payload, request=request)

    # 命中映射：额度耗尽翻译为可执行的友好提示
    with pytest.raises(ProviderError, match="视频生成额度已用尽"):
        _raise_for_status(make_response(400, {"code": 500, "msg": "task failed", "data": {"code": "VID-4030"}}))
    with pytest.raises(ProviderError, match="图片生成额度已用尽"):
        _raise_for_status(make_response(403, {"msg": "denied", "data": {"code": "IMG-4030"}}))
    # 未命中映射：透传供应商 msg
    with pytest.raises(ProviderError, match="内容审核未通过"):
        _raise_for_status(make_response(400, {"msg": "内容审核未通过", "data": {"code": "VID-9999"}}))
    # body 非 JSON：回退为 HTTP 状态错误描述
    with pytest.raises(ProviderError):
        _raise_for_status(make_response(502, None))
    # 2xx 正常返回不抛错
    _raise_for_status(make_response(200, {"code": 200, "data": {}}))


def test_translate_provider_error_english_to_chinese() -> None:
    from app.providers import translate_provider_error

    # 真实人物合规拦截：翻译为中文，并保留请求 ID 便于排查
    translated = translate_provider_error(
        "The request failed because the input image 'content[1]' 'content[2]' may contain real person. Request id: 0217865195574823472b452131530d7d1d28285be3fe78b7e1984"
    )
    assert "疑似包含真实人物" in translated
    assert "请求ID：0217865195574823472b452131530d7d1d28285be3fe78b7e1984" in translated
    # 大小写不敏感
    assert "疑似包含真实人物" in translate_provider_error("image MAY CONTAIN REAL PERSON")
    # 内容合规拦截
    assert "安全合规校验" in translate_provider_error("Content violated our usage policy, request rejected")
    # 密钥问题
    assert "接口密钥无效" in translate_provider_error("Invalid API key")
    # 无请求 ID 的英文消息，不带中文前缀，原样返回
    assert translate_provider_error("unknown provider hiccup") == "unknown provider hiccup"
    # 中文消息透传，不做二次包装
    assert translate_provider_error("内容审核未通过") == "内容审核未通过"
    # 空消息透传
    assert translate_provider_error("") == ""


def test_poll_translates_fail_reason() -> None:
    """视频任务 FAILED 的 failReason 为英文时，落到 job.error 前应翻译为中文。"""
    import httpx

    from app.jobs import Job
    from app.providers import ProviderError, _poll

    async def scenario() -> str:
        calls = {"n": 0}

        class FakeClient:
            async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(
                        200,
                        json={"code": 200, "data": {"status": "RUNNING", "progress": 50}},
                        request=httpx.Request("GET", url),
                    )
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": {
                            "status": "FAILED",
                            "failReason": "The request failed because the input image 'content[1]' may contain real person. Request id: abc123456789",
                        },
                    },
                    request=httpx.Request("GET", url),
                )

        job = Job(id="poll-translate-test", kind="video", user_id="u1", request={})
        try:
            await _poll(FakeClient(), "https://provider.test/tasks/t1", {}, job, timeout_seconds=3600, interval_seconds=0.01)
        except ProviderError as exc:
            return str(exc)
        raise AssertionError("expected ProviderError")

    import asyncio

    message = asyncio.run(scenario())
    assert "疑似包含真实人物" in message
    assert "请求ID：abc123456789" in message


def _fake_asset_client(detail_responses: list[str]) -> type:
    """构造虚拟资产接口的假客户端：create 固定返回 asset-test-1，detail 按序返回状态。"""
    import httpx

    class FakeAssetClient:
        def __init__(self, *args, **kwargs):
            self._detail_states = list(detail_responses)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url: str, headers=None, json=None) -> httpx.Response:
            request = httpx.Request("POST", url)
            if url.endswith("/v3/assets"):
                return httpx.Response(200, json={"code": 200, "data": {"id": "asset-test-1", "status": "Processing"}}, request=request)
            status = self._detail_states.pop(0) if self._detail_states else "Active"
            payload = {"code": 200, "data": {"id": "asset-test-1", "status": status}}
            if status in {"Rejected", "Failed"}:
                payload["data"]["errorMessage"] = "face check rejected"
            return httpx.Response(200, json=payload, request=request)

    return FakeAssetClient


def test_poll_translates_seedance_error() -> None:
    """V3 Seedance 报文（无 code 包装）：failed 时从 error.message 取失败原因并翻译为中文。"""
    import httpx

    from app.jobs import Job
    from app.providers import ProviderError, _poll

    async def scenario() -> str:
        calls = {"n": 0}

        class FakeClient:
            async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(200, json={"id": "cgt-1", "status": "running"}, request=httpx.Request("GET", url))
                return httpx.Response(
                    200,
                    json={
                        "id": "cgt-1",
                        "status": "failed",
                        "error": {"message": "The request failed because the input image 'content[1]' may contain real person. Request id: def987654321"},
                    },
                    request=httpx.Request("GET", url),
                )

        job = Job(id="poll-v3-translate-test", kind="video", user_id="u1", request={})
        try:
            await _poll(FakeClient(), "https://provider.test/v3/video/tasks/cgt-1", {}, job, timeout_seconds=3600, interval_seconds=0.01)
        except ProviderError as exc:
            return str(exc)
        raise AssertionError("expected ProviderError")

    import asyncio

    message = asyncio.run(scenario())
    assert "疑似包含真实人物" in message
    assert "请求ID：def987654321" in message


async def test_generate_image_uses_stable_job_idempotency_key(client, monkeypatch) -> None:
    import httpx

    from app import providers
    from app.schemas import ImageGenerationCreate

    class FakeImageClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url: str, headers=None, json=None) -> httpx.Response:
            assert url.endswith("/image/generation/tasks")
            assert headers["Idempotency-Key"] == "job-image-idem:image"
            return httpx.Response(200, json={"code": 200, "data": {"taskId": "image-task-1", "status": "queued"}}, request=httpx.Request("POST", url))

        async def get(self, url: str, headers=None) -> httpx.Response:
            assert headers["Idempotency-Key"] == "job-image-idem:image"
            return httpx.Response(
                200,
                json={"code": 200, "data": {"status": "SUCCESS", "resultUrls": ["https://upstream.test/image.png"]}},
                request=httpx.Request("GET", url),
            )

    async def fake_import_remote_image(url, prefix):
        return (f"https://tos.test/{prefix}/image.png", f"https://tos.test/{prefix}/thumb.png")

    monkeypatch.setattr(providers, "_image_config", lambda: ("https://api-aigc.test", {"Authorization": "Bearer test", "Idempotency-Key": "random"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeImageClient)
    monkeypatch.setattr(providers, "import_remote_image", fake_import_remote_image)

    _insert_job("job-image-idem", kind="image")
    from app.jobs import jobs as job_manager

    job = await job_manager.get("job-image-idem")
    assert job is not None
    job.user_id = "u1"
    result = await providers.generate_image(ImageGenerationCreate(prompt="测试"), job)

    assert result["providerTaskId"] == "image-task-1"
    assert job.idempotency_key == "job-image-idem:image"
    assert _job_row("job-image-idem")["idempotency_key"] == "job-image-idem:image"


async def test_generate_video_v3_seedance_flow(client, monkeypatch) -> None:
    """V3 视频全链路：创建返回官方报文 id，轮询 succeeded 后从 content.video_url 落库，last_frame_url 做封面。"""
    import httpx

    from app import providers
    from app.schemas import VideoGenerationCreate

    class FakeV3VideoClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url: str, headers=None, json=None) -> httpx.Response:
            assert url.endswith("/v3/video/tasks")
            assert headers["Idempotency-Key"] == "job-v3-video:reference"
            assert json.get("return_last_frame") is True
            return httpx.Response(200, json={"id": "cgt-test-1", "status": "queued", "model": "doubao-seedance-2.0"}, request=httpx.Request("POST", url))

        async def get(self, url: str, headers=None) -> httpx.Response:
            assert url.endswith("/v3/video/tasks/cgt-test-1")
            return httpx.Response(
                200,
                json={
                    "id": "cgt-test-1",
                    "status": "succeeded",
                    "content": {"video_url": "https://upstream.test/v.mp4", "last_frame_url": "https://upstream.test/last.png"},
                    "usage": {"completion_tokens": 60682, "total_tokens": 60682},
                },
                request=httpx.Request("GET", url),
            )

    async def fake_import_remote(url, prefix, name):
        return f"https://tos.test/{prefix}/{name}"

    async def fake_import_remote_image(url, prefix):
        return (f"https://tos.test/{prefix}/cover.png", f"https://tos.test/{prefix}/thumb.png")

    monkeypatch.setattr(providers, "_video_config", lambda: ("https://api-aigc.test", {"Authorization": "Bearer test"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeV3VideoClient)
    monkeypatch.setattr(providers, "import_remote", fake_import_remote)
    monkeypatch.setattr(providers, "import_remote_image", fake_import_remote_image)

    _insert_job("job-v3-video", kind="video")
    from app.jobs import jobs as job_manager

    job = await job_manager.get("job-v3-video")
    assert job is not None
    job.user_id = "u1"
    job.request = {"model": "doubao-seedance-2.0", "duration": 5, "ratio": "16:9"}
    request = VideoGenerationCreate(prompt="测试提示词", image_urls=["asset://asset-1"], generate_audio=False, ratio="16:9", resolution="480p", duration=5, watermark=False)
    result = await providers.generate_video(request, job)

    assert result["providerTaskId"] == "cgt-test-1"
    assert result["videoUrl"] == "https://tos.test/users/u1/generated/videos/cgt-test-1.mp4"
    assert result["coverUrl"] == "https://tos.test/users/u1/generated/covers/cover.png"
    assert result["sourceUrl"] == "https://upstream.test/v.mp4"
    assert result["usage"]["total_tokens"] == 60682


async def test_general_character_video_retries_without_reference_on_real_person_block(monkeypatch) -> None:
    from app import providers
    from app.jobs import Job
    from app.schemas import VideoGenerationCreate

    submitted: list[list[dict]] = []

    class Response:
        def __init__(self, task_id: str):
            self._task_id = task_id

        def raise_for_status(self):
            return None

        def json(self):
            return {"id": self._task_id}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, *, headers, json):
            submitted.append(json["content"])
            return Response(f"video-{len(submitted)}")

    async def fake_set_provider_task(job, _provider, task_id, **_kwargs):
        job.provider_task_id = task_id

    polls = 0

    async def fake_poll(*_args, **_kwargs):
        nonlocal polls
        polls += 1
        if polls == 1:
            raise providers.ProviderError("输入参考图疑似包含真实人物")
        return {"content": {"video_url": "https://upstream.test/result.mp4"}}

    async def fake_store(_job, task_id, _data, _created):
        return {"providerTaskId": task_id}

    monkeypatch.setattr(providers, "_video_config", lambda: ("https://api.test", {"Authorization": "Bearer test"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", lambda **_kwargs: Client())
    monkeypatch.setattr(providers.jobs, "mark_provider_submitting", lambda _job: asyncio.sleep(0))
    monkeypatch.setattr(providers.jobs, "set_provider_task", fake_set_provider_task)
    monkeypatch.setattr(providers, "_poll_scheduled", fake_poll)
    monkeypatch.setattr(providers, "_store_video_result", fake_store)
    request = VideoGenerationCreate(prompt="人物走在街道", image_urls=["https://tos.test/scene-with-person.png"])
    job = Job(id="job-general-fallback", kind="video", request={"_generalCharacterTextFallback": True})

    result = await providers.generate_video(request, job)

    assert len(submitted) == 2
    assert [item["type"] for item in submitted[0]] == ["text", "image_url"]
    assert [item["type"] for item in submitted[1]] == ["text"]
    assert result["referenceFallback"] == "text-to-video-real-person-policy"


def test_create_real_face_asset_polls_to_active(client, monkeypatch) -> None:
    from app import providers

    async def fake_video_config():
        return ("https://api-aigc.test", {"Authorization": "Bearer test", "Content-Type": "application/json"})

    monkeypatch.setattr(providers, "_video_config", lambda: ("https://api-aigc.test", {"Authorization": "Bearer test"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", _fake_asset_client(["Processing", "Active"]))

    asset_url = asyncio.run(providers.create_real_face_asset("https://tos.test/face.jpg", name="mv-001"))
    assert asset_url == "asset://asset-test-1"


def test_create_real_face_asset_rejected_raises_friendly_error(client, monkeypatch) -> None:
    from app import providers

    monkeypatch.setattr(providers, "_video_config", lambda: ("https://api-aigc.test", {"Authorization": "Bearer test"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", _fake_asset_client(["Rejected"]))

    with pytest.raises(providers.ProviderError, match="虚拟资产审核未通过"):
        asyncio.run(providers.create_real_face_asset("https://tos.test/face.jpg", name="mv-001"))


def test_create_real_face_asset_uses_v3_without_moderation(client, monkeypatch) -> None:
    """V3 素材接口：请求走 /v3/assets，且不再携带 Moderation 参数（V3 仅支持虚拟人像素材）。"""
    import httpx

    from app import providers

    calls: list[dict] = []

    class FakeV3Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url: str, headers=None, json=None) -> httpx.Response:
            request = httpx.Request("POST", url)
            if url.endswith("/v3/assets"):
                calls.append(dict(json))
                return httpx.Response(200, json={"code": 200, "data": {"id": "asset-cn-1", "status": "Processing"}}, request=request)
            return httpx.Response(200, json={"code": 200, "data": {"id": "asset-cn-1", "status": "Active"}}, request=request)

    monkeypatch.setattr(providers, "_video_config", lambda: ("https://api-aigc.test", {"Authorization": "Bearer test"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", FakeV3Client)

    asset_url = asyncio.run(providers.create_real_face_asset("https://tos.test/face.jpg", name="mv-001"))
    assert asset_url == "asset://asset-cn-1"
    assert len(calls) == 1
    assert "Moderation" not in calls[0]


async def test_resolve_asset_avatar_urls_maps_human_tos_to_asset(client) -> None:
    from app.database import session_factory
    from app.main import _resolve_asset_avatar_urls
    from app.models import DigitalHumanModel

    async with session_factory() as db:
        db.add(
            DigitalHumanModel(
                id="dh-asset-map",
                user_id="admin",
                name="asset-map",
                description="",
                avatar_url="https://tos.test/human.jpg",
                avatar_thumbnail_url="https://tos.test/human-thumb.jpg",
                asset_avatar_url="asset://human-1",
                scope="private",
            )
        )
        await db.commit()

    async with session_factory() as db:
        result = await _resolve_asset_avatar_urls(
            db,
            ["https://tos.test/human.jpg", "https://tos.test/scene.png", "https://tos.test/human-thumb.jpg", "asset://already-asset"],
        )
    # 头像（原图与缩略图）映射为 asset://，非头像 URL（场景图、已是 asset:// 的）原样保留
    assert result == ["asset://human-1", "https://tos.test/scene.png", "asset://human-1", "asset://already-asset"]


def test_video_generation_endpoint_uses_asset_avatar_url(client, monkeypatch) -> None:
    """端到端：POST /api/generations/videos 时，数字人头像 TOS 路径在进入生成器前被替换为 asset://。"""
    import time

    from app import main

    user = client.get("/api/auth/me").json()
    _fail_active_jobs()
    captured: dict[str, list[str]] = {}

    async def fake_video(payload, job) -> dict:
        captured["image_urls"] = list(payload.image_urls)
        return {"videoUrl": "https://tos.test/videos/ok.mp4", "coverUrl": "https://tos.test/images/ok.png", "duration": 5}

    monkeypatch.setattr(main, "generate_video", fake_video)

    async def _seed_human() -> None:
        from app.database import session_factory
        from app.models import DigitalHumanModel

        async with session_factory() as db:
            db.add(
                DigitalHumanModel(
                    id="dh-video-asset",
                    user_id=user["id"],
                    name="video-asset",
                    description="",
                    avatar_url="https://tos.test/video-human.jpg",
                    asset_avatar_url="asset://video-human-1",
                    scope="private",
                )
            )
            await db.commit()

    asyncio.run(_seed_human())
    try:
        response = client.post(
            "/api/generations/videos",
            json={"prompt": "test video", "image_urls": ["https://tos.test/video-human.jpg", "https://tos.test/scene.png"]},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(50):
            state = client.get(f"/api/generations/{job_id}").json()
            if state["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        assert state["status"] == "succeeded"
        assert captured["image_urls"] == ["asset://video-human-1", "https://tos.test/scene.png"]
    finally:
        _fail_active_jobs()
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute("DELETE FROM daily_usage_quotas WHERE user_id = ? AND category = 'video'", (user["id"],))
            connection.commit()
        finally:
            connection.close()


async def test_general_video_server_strips_character_reference_images(client) -> None:
    from app.database import session_factory
    from app.main import _strip_general_character_references
    from app.models import DigitalHumanModel, ProjectModel, ProjectTaskModel

    async with session_factory() as db:
        db.add(ProjectModel(id="project-general-random", user_id="user-admin", name="General random"))
        db.add(ProjectTaskModel(id="task-general-random", project_id="project-general-random", title="General", storyboard_type="general"))
        db.add(
            DigitalHumanModel(
                id="dh-general-random",
                user_id="user-admin",
                name="Reference person",
                avatar_url="https://tos.test/human.png",
                avatar_thumbnail_url="https://tos.test/human-thumb.png",
                asset_avatar_url="asset://human",
                scope="private",
            )
        )
        await db.commit()
        filtered = await _strip_general_character_references(
            db,
            "task-general-random",
            ["https://tos.test/scene.png", "https://tos.test/human.png", "asset://human"],
        )
    assert filtered == ["https://tos.test/scene.png"]


def test_h3_endpoint_enforces_official_reference_capabilities(client) -> None:
    base = {
        "prompt": "故宫舞蹈",
        "model": "minimax-h3-runninghub",
        "image_urls": ["https://tos.test/person.jpg"],
    }
    too_many_videos = client.post(
        "/api/generations/videos",
        json={**base, "video_urls": [f"https://tos.test/dance-{index}.mp4" for index in range(4)]},
    )
    assert too_many_videos.status_code == 422

    audio_only = client.post(
        "/api/generations/videos",
        json={"prompt": "故宫舞蹈", "model": "minimax-h3-runninghub", "audio_urls": ["https://tos.test/music.wav"]},
    )
    assert audio_only.status_code == 422
    assert "不能单独使用" in audio_only.json()["detail"]


def test_create_human_registers_asset_avatar(client, monkeypatch) -> None:
    """用户上传数字人创建时，同步注册平台虚拟资产并入库 asset:// 链接。"""
    from app import domain

    created: list[str] = []

    async def fake_create_asset(public_url: str, *, name: str) -> str:
        created.append(public_url)
        return f"asset://user-{len(created)}"

    monkeypatch.setattr("app.providers.create_real_face_asset", fake_create_asset)
    payload = {
        "name": "上传人物-测试",
        "description": "t",
        "avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/face.jpg",
        "source": "uploaded",
    }
    response = client.post("/api/digital-humans", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assetAvatarUrl"] == "asset://user-1"
    assert body["originalAvatar"] == payload["avatar_url"]  # TOS 原路径保留
    assert created == [payload["avatar_url"]]
    assert domain._sync_human_asset_avatar is not None  # 引用保证函数存在


def test_update_human_re_registers_asset_avatar_on_avatar_change(client, monkeypatch) -> None:
    """换图（重新生成形象）后旧资产失效，自动用新图重新注册 asset。"""
    created: list[str] = []

    async def fake_create_asset(public_url: str, *, name: str) -> str:
        created.append(public_url)
        return f"asset://user-{len(created)}"

    monkeypatch.setattr("app.providers.create_real_face_asset", fake_create_asset)
    first = client.post(
        "/api/digital-humans",
        json={"name": "换图人物", "description": "t", "avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/old.jpg", "source": "uploaded"},
    ).json()
    assert first["assetAvatarUrl"] == "asset://user-1"

    second = client.patch(
        f"/api/digital-humans/{first['id']}",
        json={"avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/new.jpg"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["assetAvatarUrl"] == "asset://user-2"
    assert created == [
        "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/old.jpg",
        "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/new.jpg",
    ]

    # 未换图时（只改名字）不重新注册资产
    renamed = client.patch(f"/api/digital-humans/{first['id']}", json={"name": "改名字"})
    assert renamed.json()["assetAvatarUrl"] == "asset://user-2"
    assert len(created) == 2


def test_create_human_asset_failure_degrades_gracefully(client, monkeypatch) -> None:
    """资产注册失败不阻断数字人创建：接口正常返回，assetAvatarUrl 为空，后续由启动任务兜底。"""
    from app.providers import ProviderError

    async def boom(public_url: str, *, name: str) -> str:
        raise ProviderError("上游挂了")

    monkeypatch.setattr("app.providers.create_real_face_asset", boom)
    response = client.post(
        "/api/digital-humans",
        json={"name": "降级人物", "description": "t", "avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/face.jpg", "source": "uploaded"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["assetAvatarUrl"] is None
    assert response.json()["originalAvatar"].startswith("https://")
