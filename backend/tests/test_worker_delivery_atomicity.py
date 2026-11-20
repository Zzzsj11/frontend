"""No-network regressions for atomic delivery, version selection, and attribution."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.database import session_factory
from app.jobs import jobs
from app.models import GenerationJobModel, SceneAssetModel, TokenUsageModel, utcnow


@pytest.mark.asyncio
async def test_reverse_image_completion_and_deleted_job_costs(client):
    project = client.post("/api/projects", json={"name": "atomic image test"}).json()
    task = client.post(
        f"/api/projects/{project['id']}/storyboards/general/random",
        json={
            "genre": "流行歌曲",
            "empty_shot_count": 1,
            "character_shot_count": 0,
            "total_duration": 5,
            "video_model": "doubao-seedance-2.0-all-in-one",
        },
    ).json()
    line_id = task["lines"][0]["id"]
    now = utcnow()
    samples = []
    async with session_factory.begin() as db:
        for index in range(3):
            row = GenerationJobModel(
                id=f"atomic-image-{index}",
                status="running",
                kind="image",
                storyboard_line_id=line_id,
                generation_origin="agent_test",
                agent_name="code-agent",
                agent_run_id="atomic-run",
                deleted_at=now if index == 2 else None,
                created_at=now + timedelta(seconds=index),
            )
            db.add(row)
            await db.flush()
            job = jobs._from_model(row)
            job.result = {"urls": ["https://example.test/image"], "provider": "all-in-one", "providerTaskId": f"upstream-{index}", "usage": {"total_tokens": 12}}
            samples.append(job)
    # _persist_asset alone must durably finish the job even if the process dies before _run finally.
    for job in [samples[1], samples[0], samples[2], samples[0]]:
        await jobs._persist_asset(job)
    async with session_factory() as db:
        for job in samples:
            row = await db.get(GenerationJobModel, job.id)
            assert row.status == "succeeded"
            usage = (await db.scalars(select(TokenUsageModel).where(TokenUsageModel.generation_job_id == job.id))).one()
            assert (usage.total_tokens, usage.generation_origin, usage.agent_run_id) == (12, "agent_test", "atomic-run")
        rows = (await db.scalars(select(SceneAssetModel).where(SceneAssetModel.storyboard_line_id == line_id))).all()
        assert {(row.generation_job_id, row.is_current) for row in rows} == {(samples[0].id, False), (samples[1].id, True)}


@pytest.mark.asyncio
async def test_chat_failure_sets_job_terminal_and_records_one_usage(client, monkeypatch):
    from dataclasses import replace

    from app import chat, worker
    from app.models import ChatSessionModel, UserModel

    monkeypatch.setattr(chat, "settings", replace(chat.settings, llm_api_key=""))
    monkeypatch.setattr(chat, "gateway_enabled", lambda: False)
    async with session_factory.begin() as db:
        owner = await db.scalar(select(UserModel.id).where(UserModel.username == "admin"))
        session = ChatSessionModel(id="terminal-chat", user_id=owner, system_prompt="test", status="running")
        db.add(session)
        job = await jobs.enqueue(db, "chat", {"session_id": session.id}, user_id=owner)
    await jobs.run_claimed(job, worker._runner(job))
    async with session_factory() as db:
        row = await db.get(GenerationJobModel, job.id)
        assert row.status == "failed" and "LLM_API_KEY" in row.error
        assert (await db.get(ChatSessionModel, session.id)).status == "idle"
        usage = (await db.scalars(select(TokenUsageModel).where((TokenUsageModel.chat_session_id == session.id) | (TokenUsageModel.generation_job_id == job.id)))).all()
        assert [item.operation for item in usage] == ["chat_failed"]


@pytest.mark.asyncio
async def test_deleted_media_never_dispatches_unsubmitted_provider(client):
    async with session_factory.begin() as db:
        row = GenerationJobModel(id="deleted-unsubmitted", kind="image", status="running", phase="claimed", deleted_at=utcnow(), worker_id="fixture-owner")
        db.add(row)
        await db.flush()
        job = jobs._from_model(row)

    dispatched = False

    async def submit(owned):
        nonlocal dispatched
        await jobs.mark_provider_submitting(owned)
        dispatched = True

    await jobs.run_claimed(job, submit)
    assert not dispatched
    async with session_factory() as db:
        assert (await db.get(GenerationJobModel, job.id)).status == "cancelled"


@pytest.mark.asyncio
async def test_outline_model_wait_has_no_transaction_and_preserves_parallel_changes(client, monkeypatch):
    from app import domain
    from app.models import ProjectTaskModel

    user_id = client.get("/api/auth/me").json()["id"]
    project = client.post("/api/projects", json={"name": "outline progress test"}).json()
    task = client.post(
        f"/api/projects/{project['id']}/storyboards/general/random",
        json={"genre": "流行歌曲", "empty_shot_count": 1, "character_shot_count": 0, "total_duration": 5, "video_model": "doubao-seedance-2.0-all-in-one"},
    ).json()
    async with session_factory.begin() as db:
        job = await jobs.enqueue(db, "general_outline", {}, user_id=user_id, project_id=project["id"], project_task_id=task["taskId"])
    sessions = []

    def tracked_session():
        session = session_factory()
        sessions.append(session)
        return session

    async def generate(config, selected_humans, on_progress):
        assert all(not s.in_transaction() for s in sessions)
        async with session_factory.begin() as db:
            stored = await db.get(ProjectTaskModel, task["taskId"])
            stored.storyboard_config = {**stored.storyboard_config, "changedDuringModel": True}
        await on_progress({"phase": "test", "shotsDone": 0, "shotsTotal": 1})
        async with session_factory() as db:
            stored = await db.get(ProjectTaskModel, task["taskId"])
            assert stored.storyboard_config["outlineProgress"]["jobId"] == job.id
            assert stored.storyboard_config["changedDuringModel"]
        error = RuntimeError("fixture text provider failure")
        error.usage_records = [{"operation": "general_story_outline", "usage": {"total_tokens": 3}}]
        raise error

    monkeypatch.setattr(domain, "session_factory", tracked_session)
    monkeypatch.setattr(domain, "generate_general_story_outline", generate)
    await jobs.run_claimed(
        job, lambda owned: domain._run_general_outline_generation(task_id=task["taskId"], user_id=user_id, project_id=project["id"], selected_humans=[], job=owned)
    )
    async with session_factory() as db:
        stored = await db.get(ProjectTaskModel, task["taskId"])
        assert stored.storyboard_config["changedDuringModel"]
        row = await db.get(GenerationJobModel, job.id)
        assert row.status == "failed" and "fixture text provider failure" in row.error
        records = (await db.scalars(select(TokenUsageModel).where(TokenUsageModel.generation_job_id == job.id))).all()
        assert [(rec.operation, rec.total_tokens) for rec in records] == [("general_story_outline_failed", 3)]


@pytest.mark.asyncio
async def test_admin_sync_never_reuses_another_workers_id(client, monkeypatch):
    from unittest.mock import AsyncMock

    from app import admin, redis_store

    row = GenerationJobModel(
        id="owned-worker-sync",
        kind="video",
        status="running",
        worker_id="first-worker",
        provider_task_id="upstream",
        provider="all-in-one",
        request={"model": "doubao-seedance-2.0-all-in-one", "_provider": "all-in-one"},
    )
    async with session_factory.begin() as db:
        db.add(row)
    query = AsyncMock()
    monkeypatch.setattr(admin, "query_provider_task", query)
    monkeypatch.setattr(redis_store, "notify_worker", AsyncMock())
    response = client.post(f"/api/admin/jobs/{row.id}/sync")
    assert response.status_code == 200 and response.json()["action"] == "skipped"
    query.assert_not_awaited()
    redis_store.notify_worker.assert_awaited_once_with("video")
    async with session_factory() as db:
        assert (await db.get(GenerationJobModel, row.id)).worker_id == "first-worker"


@pytest.mark.asyncio
async def test_known_image_archive_failure_keeps_bill_visible_and_recovers_once(client):
    from app.providers import ProviderSubmissionUncertainError

    user = client.get("/api/auth/me").json()
    async with session_factory.begin() as db:
        row = GenerationJobModel(
            id="image-billed-archive-error",
            kind="image",
            status="running",
            provider="all-in-one",
            provider_task_id="original-image-bill",
            user_id=user["id"],
            generation_origin="agent_test",
            agent_name="code-agent",
            agent_run_id="archive-fixture",
            request={"model": "gpt-image-2-all-in-one"},
        )
        db.add(row)
        await db.flush()
        job = jobs._from_model(row)
    usage = {"platformBilling": {"status": "settled", "points": "2.50"}, "total_tokens": 7}

    async def archive_fails(owned):
        error = ProviderSubmissionUncertainError("mock archive unavailable")
        error.provider, error.request_id, error.usage, error.requires_reconciliation = "all-in-one", owned.provider_task_id, usage, True
        raise error

    await jobs.run_claimed(job, archive_fails)
    async with session_factory() as db:
        row = await db.get(GenerationJobModel, job.id)
        assert (row.status, row.phase, row.result["usage"]) == ("failed", "manual_review", usage)
    rows = client.get("/api/admin/image-billing?origin=agent_test").json()
    assert [(row["points"], row["agentRunId"]) for row in rows if row["jobId"] == job.id] == [("2.50", "archive-fixture")]
    await jobs.finalize_success(job, {"provider": "all-in-one", "providerTaskId": job.provider_task_id, "usage": usage, "urls": ["https://example.test/test.png"]})
    async with session_factory() as db:
        records = (await db.scalars(select(TokenUsageModel).where(TokenUsageModel.generation_job_id == job.id))).all()
        assert [(rec.operation, rec.total_tokens) for rec in records] == [("generation_image", 7)]
