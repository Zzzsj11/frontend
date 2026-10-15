from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import image_failover as policy
from app.all_in_one_catalog import rows
from app.jobs import Job


class State:
    def __init__(self):
        self.count = 0
        self.seen = set()
        self.ttl = None

    async def get(self, key):
        return self.count

    async def eval(self, script, keys, counter, event, outcome, ttl):
        if event in self.seen:
            return -1
        self.seen.add(event)
        self.ttl = ttl
        self.count = 0 if outcome == "success" else self.count + 1
        return self.count


def job(number, model=policy.PRIMARY_MODEL):
    return Job(id=str(number), kind="image", request={"model": model, "_provider": "all-in-one"})


@pytest.mark.asyncio
async def test_consecutive_task_outcomes_deduplicate_and_recover(monkeypatch):
    state = State()
    monkeypatch.setattr(policy, "redis", state)
    for n in range(2):
        await policy.record_outcome(job(n), succeeded=False)
        assert await policy.choose_model(policy.PRIMARY_MODEL) == policy.PRIMARY_MODEL
    await policy.record_outcome(job(1), succeeded=False)
    assert state.count == 2
    await policy.record_outcome(job(2), succeeded=False)
    assert await policy.choose_model(policy.PRIMARY_MODEL) == policy.FALLBACK_MODEL
    await policy.record_outcome(job("backup", policy.FALLBACK_MODEL), succeeded=True)
    assert state.count == 3
    assert state.ttl == 7200
    await policy.record_outcome(job("primary-success"), succeeded=True)
    assert state.count == 0
    await policy.record_outcome(job("new-failure"), succeeded=False)
    assert state.count == 1
    state.count = 0  # Redis expiry returns subsequent requests to the primary.
    assert await policy.choose_model(policy.PRIMARY_MODEL) == policy.PRIMARY_MODEL


@pytest.mark.asyncio
async def test_redis_unavailable_retains_primary(monkeypatch):
    monkeypatch.setattr(policy, "redis", SimpleNamespace(get=AsyncMock(side_effect=RuntimeError("offline"))))
    assert await policy.choose_model(policy.PRIMARY_MODEL) == policy.PRIMARY_MODEL


@pytest.mark.asyncio
async def test_backup_freezes_actual_model_spec_and_pool(monkeypatch):
    monkeypatch.setattr(policy, "choose_model", AsyncMock(return_value=policy.FALLBACK_MODEL))
    seedream = next(row for row in rows({}) if row["code"] == policy.FALLBACK_MODEL)
    model = SimpleNamespace(**seedream)
    session = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: (model, object()))))
    original = {
        "model": policy.PRIMARY_MODEL,
        "_provider": "all-in-one",
        "size": "16:9",
        "resolution": "4K",
        "images": ["https://example.test/face.jpg"],
        "purpose": "digital_human",
    }
    actual = await policy.prepare_request(session, original)
    assert actual["model"] == policy.FALLBACK_MODEL
    assert actual["resolution"] == "2K"
    assert actual["_imageFailover"]["requestedResolution"] == "4K"
    assert original["resolution"] == "4K"
    assert actual["images"] == original["images"]
    assert actual["_executionPool"] == "all-in-one:seedream-5.0-pro"
    assert actual["_executionConcurrency"] == 5
    too_many = await policy.prepare_request(session, {**original, "images": ["https://example.test/ref.jpg"] * 11})
    assert too_many["model"] == policy.PRIMARY_MODEL
    assert too_many["_imageFailover"]["skipped"] == "incompatible_backup_capabilities"
    session.execute.return_value.one_or_none = lambda: None
    unavailable = await policy.prepare_request(session, original)
    assert unavailable["model"] == policy.PRIMARY_MODEL


@pytest.mark.asyncio
@pytest.mark.parametrize("succeeded", [True, False])
async def test_terminal_provider_outcome_precedes_media_storage(monkeypatch, succeeded):
    from app import all_in_one
    from app.jobs import jobs
    from app.providers import ProviderError

    result = {"status": "SUCCEEDED" if succeeded else "FAILED", "failReason": "supplier error"}
    monkeypatch.setattr(all_in_one, "query_task", AsyncMock(return_value=result))
    monkeypatch.setattr(jobs, "record_provider_response", AsyncMock())
    recorded = AsyncMock()
    monkeypatch.setattr(policy, "record_outcome", recorded)
    monkeypatch.setattr(all_in_one, "store_result", AsyncMock(side_effect=RuntimeError("TOS unavailable")))
    task = job("terminal")
    task.provider_task_id = "existing-upstream"
    with pytest.raises((RuntimeError, ProviderError)):
        await all_in_one.resume(task)
    recorded.assert_awaited_once_with(task, succeeded=succeeded)


def test_api_enqueues_actual_backup_with_own_pool(client, monkeypatch):
    import asyncio

    from app.jobs import jobs

    monkeypatch.setattr(policy, "choose_model", AsyncMock(return_value=policy.FALLBACK_MODEL))
    monkeypatch.setattr(jobs, "dispatch", AsyncMock())
    response = client.post("/api/generations/images", json={"prompt": "Synthetic backup test", "model": policy.PRIMARY_MODEL, "resolution": "4K", "size": "16:9"})
    assert response.status_code == 202, response.text
    saved = asyncio.run(jobs.get(response.json()["id"]))
    assert saved.request["model"] == policy.FALLBACK_MODEL
    assert saved.request["_providerModelId"] == "seedream-5.0-pro"
    assert saved.request["_executionConcurrency"] == 5
    assert saved.request["resolution"] == "2K"
