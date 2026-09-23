import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_catalog_routes():
    import json

    spec = importlib.util.spec_from_file_location("overseas_import", ROOT / "scripts/import-overseas.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    items = json.loads((ROOT / "catalog/yseeai-2026-09-21.json").read_text())["models"]
    rows = [module.definition(i) for i in items]
    assert len(rows) == 97
    assert sum(not r["enabled"] for r in rows) == 3
    assert all("tencent-mps" not in r["id"] for r in rows)
    assert next(r for r in rows if r["provider_model"] == "seedream-4.0")["protocol"] == "image-sync"
    assert next(r for r in rows if r["provider_model"] == "codex-auto-review")["protocol"] == "responses"


@pytest.mark.asyncio
async def test_sync_image_recovery_never_resubmits(service, monkeypatch):
    from gateway import queue
    from gateway.db import Model, Session

    api, _, _, _ = service
    async with Session.begin() as db:
        db.add(
            Model(
                id="seedream-test",
                provider_model="seedream-4.0",
                channel="yseeai-llm",
                kind="image",
                protocol="image-sync",
                capabilities={},
                enabled=True,
            )
        )
    r = await api.post("/v1/jobs", json={"model": "seedream-test", "payload": {"prompt": "cup"}})
    jid = r.json()["id"]
    calls = []

    async def post(self, url, **kwargs):
        calls.append(url)
        return httpx.Response(
            200,
            json={"data": [{"url": "https://example.com/image.png"}], "usage": {"output_tokens": 12}},
            request=httpx.Request("POST", url),
        )

    async def broken(*args):
        raise ValueError("storage unavailable")

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    monkeypatch.setattr(queue, "archive", broken)
    await queue.claim("test-worker")
    await queue.process(jid)
    async with Session() as db:
        job = await db.get(queue.Job, jid)
        assert job.status == "recoverable" and job.usage["output_tokens"] == 12
    await queue.update(jid, status="queued")

    async def archived(*args):
        return {"media": [{"url": "https://example.com/stored.png"}]}

    monkeypatch.setattr(queue, "archive", archived)
    await queue.claim("test-worker")
    await queue.process(jid)
    assert len(calls) == 1
    async with Session() as db:
        assert (await db.get(queue.Job, jid)).status == "succeeded"


def test_wan_and_dreamactor_adapters():
    from gateway.adapters import video_payload
    from gateway.schemas import VideoCreate

    model = SimpleNamespace(protocol="wan", provider_model="wan2.6-i2v-sg")
    req = VideoCreate(model="x", prompt="move", images=["https://example.com/a.png"], reference_mode="first_frame")
    assert video_payload(model, req)["input"]["img_url"] == req.images[0]
    model.protocol, model.provider_model = "dreamactor", "dreamactor-m2.0"
    req.videos = ["https://example.com/motion.mp4"]
    assert video_payload(model, req)["video_url"] == req.videos[0]


@pytest.mark.asyncio
async def test_responses_usage_and_business_error(service, monkeypatch):
    from gateway.db import Job, Model, Session
    from sqlalchemy import select

    api, _, _, _ = service
    async with Session.begin() as db:
        db.add(
            Model(
                id="responses-test",
                provider_model="codex-auto-review",
                channel="yseeai-llm",
                kind="chat",
                protocol="responses",
                capabilities={},
                enabled=True,
            )
        )
    original = httpx.AsyncClient.send
    seen = []

    async def send(self, req, **kwargs):
        if req.url.host == "ai-aigc.yseeai.com":
            seen.append(req)
            return httpx.Response(
                200, json={"id": "response-fixture", "output": [], "usage": {"input_tokens": 3, "output_tokens": 2}}, request=req
            )
        return await original(self, req, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await api.post("/v1/responses", json={"model": "responses-test", "input": "Synthetic test"})
    assert result.status_code == 200
    assert seen[0].url.path == "/v1/responses"
    assert seen[0].headers["X-Agent-Name"] == "code-agent"
    async with Session() as db:
        row = await db.scalar(select(Job).where(Job.model_id == "responses-test"))
        assert row.status == "succeeded" and row.usage["output_tokens"] == 2
    result = await api.post("/v1/responses", json={"model": "responses-test", "input": "Synthetic test"})
    assert result.status_code == 200 and len(seen) == 1
