import asyncio
from unittest.mock import AsyncMock

import pytest


async def test_worker_stops_claiming_and_drains(service, monkeypatch, tmp_path):
    from gateway import channel_balances, queue

    stop = asyncio.Event()
    finished = asyncio.Event()
    balance_stopped = asyncio.Event()

    async def balance():
        try:
            await asyncio.Event().wait()
        finally:
            balance_stopped.set()

    async def claim(worker):
        assert (tmp_path / "worker-ready").is_file()
        await asyncio.sleep(0)
        stop.set()
        return "fixture"

    async def process(jid):
        await asyncio.sleep(0.01)
        finished.set()

    monkeypatch.setattr(queue, "claim", AsyncMock(side_effect=claim))
    monkeypatch.setattr(queue, "process", process)
    monkeypatch.setattr(channel_balances, "loop", balance)
    await queue.main(stop=stop, drain_seconds=1)
    assert finished.is_set() and balance_stopped.is_set()
    assert not (tmp_path / "worker-ready").exists()
    assert queue.claim.await_count == 1


async def test_interrupted_submission_is_not_retried(service, monkeypatch):
    import httpx
    from gateway import queue
    from gateway.db import Job, Session

    api, _, _, _ = service
    response = await api.post("/v1/jobs", json={"model": "veo-3.1-generate-preview", "payload": {"prompt": "test", "duration": 8}})
    jid = response.json()["id"]
    assert await queue.claim("fixture-worker") == jid
    submitting = asyncio.Event()
    original = httpx.AsyncClient.post

    async def post(self, url, **kwargs):
        if "yseeai" in str(url):
            submitting.set()
            await asyncio.Event().wait()
        return await original(self, url, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    task = asyncio.create_task(queue.process(jid))
    await asyncio.wait_for(submitting.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with Session() as db:
        job = await db.get(Job, jid)
        assert job.status == "manual_review" and job.worker_id is None
    assert await queue.claim("new-worker") is None


async def test_idle_and_database_failure_readiness(service, monkeypatch, tmp_path):
    from contextlib import asynccontextmanager

    from gateway import channel_balances, queue

    ready = tmp_path / "worker-ready"
    stop = asyncio.Event()

    async def idle_claim(worker):
        assert ready.exists()
        stop.set()

    @asynccontextmanager
    async def offline():
        raise ConnectionError("database unavailable")
        yield

    monkeypatch.setattr(channel_balances, "loop", asyncio.Event().wait)
    monkeypatch.setattr(queue, "claim", idle_claim)
    await queue.main(stop)
    assert not ready.exists()
    ready.touch()
    monkeypatch.setattr(queue, "Session", offline)
    with pytest.raises(ConnectionError, match="database unavailable"):
        await queue.main(asyncio.Event())
    assert not ready.exists()
