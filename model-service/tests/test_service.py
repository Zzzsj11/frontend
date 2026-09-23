import importlib
import os
import sqlite3
import subprocess
import sys
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "public-api"), str(ROOT / "admin-api")]


@pytest.fixture
async def service(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///" + str(tmp_path / "test.db"))
    monkeypatch.setenv("ADMIN_JWT_SECRET", "test-only-" * 8)
    monkeypatch.setenv("ADMIN_PASSWORD", "test-only-password")
    monkeypatch.setenv("YINGHE_API_KEY", "fake-test-key")
    monkeypatch.setenv("YSEEAI_API_KEY", "fake-test-key")
    monkeypatch.setenv("YINGHE_LLM_API_KEY", "fake-test-key")
    monkeypatch.setenv("POLL_SECONDS", "0")
    for name in list(sys.modules):
        if name.startswith(("gateway", "control")):
            del sys.modules[name]
    # Exercise legacy catalog compatibility; fresh head catalog has separate migration tests.
    subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"], check=True, capture_output=True)
    # Disposable synthetic database: replace release catalog with legacy seed fixtures.
    with sqlite3.connect(tmp_path / "test.db") as fixture_db:
        fixture_db.execute("DELETE FROM model_routes")
        fixture_db.execute("DELETE FROM models")
    subprocess.run(
        [sys.executable, str(ROOT / "scripts/seed.py")],
        env={**os.environ, "PYTHONPATH": str(ROOT / "public-api")},
        check=True,
        capture_output=True,
    )
    public = importlib.import_module("gateway.main")
    admin = importlib.import_module("control.main")
    async with (
        httpx.AsyncClient(transport=httpx.ASGITransport(app=public.app), base_url="http://test") as api,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=admin.app), base_url="http://test") as ctl,
    ):
        response = await ctl.post("/admin/login", json={"username": "admin", "password": "test-only-password"})
        ctl.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        c = (await ctl.post("/admin/clients", json={"name": "test", "require_agent": True, "billing_enabled": False})).json()
        api.headers.update(
            {
                "Authorization": "Bearer " + c["api_key"],
                "X-User-Id": "u1",
                "Idempotency-Key": "key1",
                "X-Agent-Name": "code-agent",
                "X-Agent-Run-Id": "test-1",
                "X-Test-Run-Id": "test-1",
            }
        )
        yield api, ctl, public, c
    await public.Session.kw["bind"].dispose()
    await admin.Session.kw["bind"].dispose()


def body():
    return {"model": "veo-3.1-generate-preview", "payload": {"prompt": "test", "duration": 8, "resolution": "720p"}}


@pytest.mark.asyncio
async def test_isolation_idempotency_attribution(service):
    api, ctl, public, c = service
    r = await api.post("/v1/jobs", json=body())
    assert r.status_code == 202, r.text
    jid = r.json()["id"]
    assert (await api.post("/v1/jobs", json=body())).json()["id"] == jid
    changed = body()
    changed["payload"]["prompt"] = "changed"
    assert (await api.post("/v1/jobs", json=changed)).status_code == 409
    assert (await api.get("/v1/jobs/" + jid, headers={"X-User-Id": "u2"})).status_code == 404
    other = (await ctl.post("/admin/clients", json={"name": "other"})).json()
    assert (await api.get("/v1/jobs/" + jid, headers={"Authorization": "Bearer " + other["api_key"]})).status_code == 404
    assert (await api.post("/v1/jobs", json=body(), headers={"X-Agent-Name": ""})).status_code == 400
    rows = (await ctl.get("/admin/jobs?origin=agent_test&agent_run_id=test-1")).json()
    assert rows["total"] == 1 and rows["items"][0]["agent_name"] == "code-agent"
    assert "key_hash" not in (await ctl.get("/admin/clients")).text
    assert (await ctl.delete("/admin/clients/" + c["id"])).status_code == 204
    assert (await api.get("/v1/models")).status_code == 401


@pytest.mark.asyncio
async def test_native_contract_and_disabled_models(service):
    api, ctl, public, c = service
    r = await api.post(
        "/providers/yinghe/v3/video/tasks",
        json={"model": "doubao-seedance-2.0", "content": [{"type": "text", "text": "test"}], "duration": 5},
    )
    assert r.status_code == 200 and r.json()["code"] == 200
    jid = r.json()["data"]["id"]
    r = await api.get("/providers/yinghe/v3/video/tasks/" + jid)
    assert r.json()["data"]["status"] == "processing"
    assert (await api.get("/providers/yseeai/v3/video/tasks/" + jid)).status_code == 404
    assert (await api.post("/providers/yinghe/arbitrary", json={})).status_code == 404
    await ctl.patch("/admin/models/veo-3.1-generate-preview", json={"enabled": False})
    assert (await api.post("/v1/jobs", json=body(), headers={"Idempotency-Key": "disabled"})).status_code == 400
    assert (await ctl.post("/admin/jobs/" + jid + "/recover")).status_code == 409


@pytest.mark.asyncio
async def test_worker_records_id_and_recovers_without_resubmit(service, monkeypatch):
    api, ctl, public, c = service
    queue = importlib.import_module("gateway.queue")
    jid = (await api.post("/v1/jobs", json=body())).json()["id"]
    calls = []

    async def transport(req):
        calls.append(req.method)
        assert req.headers["X-Agent-Name"] == "code-agent"
        if req.method == "POST":
            return httpx.Response(200, json={"task_id": "provider-1", "usage": {"creation_tokens": 7}})
        return httpx.Response(
            200, json={"status": "SUCCESS", "resultUrl": "https://example.com/output.mp4", "usage": {"output_seconds": 8}}
        )

    factory = httpx.AsyncClient
    monkeypatch.setattr(queue.httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))

    async def fail_archive(job, data):
        raise RuntimeError("download interrupted")

    monkeypatch.setattr(queue, "archive", fail_archive)
    assert await queue.claim("worker") == jid
    await queue.process(jid)
    assert (await api.get("/v1/jobs/" + jid)).json()["status"] == "running"
    assert (await ctl.get("/admin/jobs/" + jid)).json()["status"] == "recoverable"
    assert (await ctl.post("/admin/jobs/" + jid + "/recover")).status_code == 200

    async def good_archive(job, data):
        return {"media": [{"url": "https://tos.example/video.mp4"}], "native": data}

    monkeypatch.setattr(queue, "archive", good_archive)
    assert await queue.claim("worker") == jid
    await queue.process(jid)
    result = (await api.get("/v1/jobs/" + jid)).json()
    assert result["status"] == "succeeded" and result["usage"]["output_seconds"] == 8
    assert result["usage"]["creation_tokens"] == 7
    assert calls.count("POST") == 1


@pytest.mark.asyncio
async def test_ambiguous_submission_never_auto_replayed(service, monkeypatch):
    api, ctl, public, c = service
    queue = importlib.import_module("gateway.queue")
    jid = (await api.post("/v1/jobs", json=body())).json()["id"]
    calls = []

    async def transport(req):
        calls.append(req.method)
        raise httpx.ReadTimeout("timeout", request=req)

    factory = httpx.AsyncClient
    monkeypatch.setattr(queue.httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))
    assert await queue.claim("worker") == jid
    await queue.process(jid)
    assert (await api.get("/v1/jobs/" + jid)).json()["status"] == "failed"
    assert (await ctl.get("/admin/jobs/" + jid)).json()["status"] == "manual_review"
    assert await queue.claim("worker") is None
    assert calls == ["POST"]


@pytest.mark.asyncio
async def test_chat_and_model_capacity(service, monkeypatch):
    api, ctl, public, c = service

    async def transport(req):
        return httpx.Response(
            200,
            json={"id": "chat-test", "choices": [{"message": {"role": "assistant", "content": "hello"}}], "usage": {"total_tokens": 12}},
        )

    factory = httpx.AsyncClient
    monkeypatch.setattr(public.httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))
    r = await api.post("/v1/chat/completions", json={"model": "gpt-5.6-sol", "messages": [{"role": "user", "content": "hello"}]})
    assert r.status_code == 200 and r.json()["usage"]["total_tokens"] == 12
    jobs = (await ctl.get("/admin/jobs")).json()["items"]
    assert jobs[0]["status"] == "succeeded" and jobs[0]["origin"] == "agent_test"


def test_control_plane_contract_is_independent():
    assert (ROOT / "public-api/gateway/db.py").read_bytes() == (ROOT / "admin-api/control/db.py").read_bytes()
    for p in (ROOT / "admin-api/control").glob("*.py"):
        assert "from gateway" not in p.read_text()


@pytest.mark.asyncio
async def test_streaming_chat_records_final_usage(service, monkeypatch):
    api, ctl, public, c = service

    async def transport(req):
        return httpx.Response(
            200,
            text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: {"choices":[],"usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}\n\ndata: [DONE]\n\n',
            headers={"content-type": "text/event-stream"},
        )

    factory = httpx.AsyncClient
    monkeypatch.setattr(public.httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))
    response = await api.post(
        "/v1/chat/completions", json={"model": "gpt-5.6-sol", "messages": [{"role": "user", "content": "OK"}], "stream": True}
    )
    assert response.status_code == 200 and "[DONE]" in response.text
    rows = (await ctl.get("/admin/jobs")).json()["items"]
    assert rows[0]["usage"]["total_tokens"] == 4 and rows[0]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_expired_worker_fence_and_capacity(service):
    api, ctl, public, c = service
    queue = importlib.import_module("gateway.queue")
    dbmod = importlib.import_module("gateway.db")
    from datetime import timedelta

    await ctl.patch("/admin/models/veo-3.1-generate-preview", json={"concurrency": 1})
    first = (await api.post("/v1/jobs", json=body())).json()["id"]
    await api.post("/v1/jobs", json=body(), headers={"Idempotency-Key": "second"})
    assert await queue.claim("old-worker") == first
    assert await queue.claim("second-worker") is None
    await queue.update(first, lease_until=dbmod.now() - timedelta(seconds=10), status="submitting")
    assert await queue.claim("second-worker") is not None
    row = (await api.get("/v1/jobs/" + first)).json()
    assert row["status"] == "failed"
    assert (await ctl.get("/admin/jobs/" + first)).json()["status"] == "manual_review"
    token = queue._worker.set("old-worker")
    try:
        with pytest.raises(queue.LeaseLost):
            await queue.update(first, status="running")
    finally:
        queue._worker.reset(token)


def record_snapshot(row, exclude=()):
    return deepcopy({column.name: getattr(row, column.name) for column in row.__table__.columns if column.name not in exclude})


@pytest.mark.asyncio
async def test_deleted_model_window_does_not_starve_valid_jobs(service, monkeypatch):
    api, _, public, client = service
    queue = importlib.import_module("gateway.queue")
    dbmod = importlib.import_module("gateway.db")
    valid_id = (await api.post("/v1/jobs", json=body())).json()["id"]
    automatic = AsyncMock(side_effect=AssertionError("Quarantine must not recalculate billing"))
    monkeypatch.setattr(queue, "automatic", automatic)
    async with public.Session.begin() as db:
        db.add(
            dbmod.Model(
                id="deleted-test-model",
                channel="historical-test-channel",
                provider_model="historical-test-model",
                kind="video",
                protocol="historical-test-protocol",
                enabled=False,
                deleted_at=dbmod.now(),
            )
        )
        for index in range(100):
            db.add(
                dbmod.Job(
                    id=f"old-job-{index}",
                    client_id=client["id"],
                    user_id="u1",
                    model_id="deleted-test-model",
                    channel="historical-test-channel",
                    protocol="historical-test-protocol",
                    kind="video",
                    payload={"prompt": "historical test"},
                    request_hash="historical-test-hash",
                    idempotency_key=f"old-request-{index}",
                    provider_id=f"old-provider-{index}",
                    charged_points=Decimal("123.456789"),
                    worker_id="old-worker",
                    lease_until=dbmod.now() + timedelta(seconds=120),
                    created_at=dbmod.now() - timedelta(days=1, seconds=index),
                )
            )
    # The bounded first window is entirely obsolete; the next iteration must advance.
    assert await queue.claim("worker") is None
    async with public.Session() as db:
        old = (await db.scalars(select(dbmod.Job).where(dbmod.Job.model_id == "deleted-test-model"))).all()
        assert len(old) == 100
        assert all(row.status == "manual_review" and row.worker_id is None and row.lease_until is None for row in old)
        assert all(row.provider_id == row.id.replace("job", "provider") and row.charged_points == Decimal("123.456789") for row in old)
        assert all(row.attempts == 0 and row.deleted_at is None for row in old)
    assert await queue.claim("worker") == valid_id
    assert await queue.claim("worker") is None
    automatic.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("target", ["missing_model", "deleted_model", "missing_route", "deleted_route"])
@pytest.mark.parametrize(
    "entry,provider_id",
    [("claim", "historical-provider-id"), ("process", None), ("process", "historical-provider-id"), ("recover", "historical-provider-id")],
)
async def test_unavailable_target_quarantined_without_financial_changes(service, monkeypatch, target, entry, provider_id):
    api, ctl, public, client = service
    queue = importlib.import_module("gateway.queue")
    dbmod = importlib.import_module("gateway.db")
    jid = (await api.post("/v1/jobs", json=body())).json()["id"]
    async with public.Session.begin() as db:
        row = await db.get(dbmod.Job, jid)
        row.provider_id = provider_id
        row.provider_response = {"task_id": provider_id, "billing": {"actual_cny": "1.25"}}
        row.usage = {"output_seconds": 8, "creation_tokens": 7}
        row.result = {"media": [{"url": "https://tos.example/historical.mp4"}]}
        row.pricing_snapshot = {"id": "historical-price", "actual_cny_path": "response.billing.actual_cny"}
        row.reserved_points = Decimal("7.123456")
        row.charged_points = Decimal("42.123456")
        row.billing_status = "pending_reconciliation"
        if target.endswith("route"):
            row.route_id = "historical-route"
            row.routing_snapshot = {"route_id": row.route_id, "provider_model": "historical-provider-model"}
            db.add(
                dbmod.ModelRoute(
                    id=row.route_id,
                    model_id=row.model_id,
                    supplier="test-supplier",
                    channel=row.channel,
                    provider_model="historical-provider-model",
                    protocol=row.protocol,
                    enabled=True,
                )
            )
        db.add(
            dbmod.Ledger(
                id="historical-ledger",
                client_id=client["id"],
                user_id=row.user_id,
                job_id=jid,
                operation_id="historical-charge",
                kind="task_charge",
                points=Decimal("-42.123456"),
                monthly_after=Decimal("100"),
                extra_after=Decimal("5"),
                actor="test-fixture",
                reason="Synthetic historical charge",
                evidence={"provider_task_id": provider_id, "actual_cny": "0.42123456"},
            )
        )
    if entry == "process":
        assert await queue.claim("worker-before-deletion") == jid
    async with public.Session.begin() as db:
        row = await db.get(dbmod.Job, jid)
        if target == "missing_model":
            row.model_id = "missing-test-model"
        elif target == "missing_route":
            row.route_id = "missing-test-route"
        else:
            record = await db.get(
                dbmod.Model if target == "deleted_model" else dbmod.ModelRoute, row.model_id if target == "deleted_model" else row.route_id
            )
            record.deleted_at = dbmod.now()
            # enabled=True ensures deletion alone is sufficient, including acceptance traffic.
            assert record.enabled
        if target.endswith("route"):
            model = await db.get(dbmod.Model, row.model_id)
            assert model.enabled and model.deleted_at is None
        if entry != "process":
            row.worker_id = "old-worker"
            row.lease_until = dbmod.now() + timedelta(seconds=120)
        if entry == "recover":
            row.status = "recoverable"
    if entry == "recover":
        assert (await ctl.post(f"/admin/jobs/{jid}/recover")).status_code == 200
        assert (await ctl.get(f"/admin/jobs/{jid}")).json()["status"] == "queued"

    mutable = {"status", "error", "worker_id", "lease_until", "updated_at"}
    async with public.Session() as db:
        before = record_snapshot(await db.get(dbmod.Job, jid), mutable)
        ledger_before = [record_snapshot(row) for row in (await db.scalars(select(dbmod.Ledger))).all()]
        client_before = record_snapshot(await db.get(dbmod.Client, client["id"]))
    guards = {
        "automatic": AsyncMock(side_effect=AssertionError("No automatic financial rewrite")),
        "config": Mock(side_effect=AssertionError("No provider configuration lookup")),
        "headers": Mock(side_effect=AssertionError("No provider headers")),
        "heartbeat": AsyncMock(side_effect=AssertionError("No heartbeat for quarantined jobs")),
        "archive": AsyncMock(side_effect=AssertionError("No media download")),
    }
    for name, guard in guards.items():
        monkeypatch.setattr(queue, name, guard)
    http = Mock(side_effect=AssertionError("No HTTP client for quarantined jobs"))
    monkeypatch.setattr(queue.httpx, "AsyncClient", http)
    if entry == "process":
        await queue.process(jid)
    else:
        assert await queue.claim("worker") is None
    assert await queue.claim("worker") is None
    async with public.Session() as db:
        row = await db.get(dbmod.Job, jid)
        assert row.status == "manual_review"
        assert ("Model route" if target.endswith("route") else "Model") in row.error
        assert "not recoverable" in row.error and "must not be resubmitted" in row.error
        assert row.worker_id is None and row.lease_until is None
        assert record_snapshot(row, mutable) == before
        assert [record_snapshot(row) for row in (await db.scalars(select(dbmod.Ledger))).all()] == ledger_before
        assert record_snapshot(await db.get(dbmod.Client, client["id"])) == client_before
    assert (await ctl.post(f"/admin/jobs/{jid}/recover")).status_code == 409
    for guard in [*guards.values(), http]:
        guard.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin,require_agent,has_route,accepted",
    [
        ("business", True, True, False),
        ("agent_test", False, True, False),
        ("agent_test", True, False, False),
        ("agent_test", True, True, True),
    ],
)
async def test_disabled_non_deleted_model_keeps_waiting_and_acceptance_semantics(
    service, monkeypatch, origin, require_agent, has_route, accepted
):
    api, _, public, client = service
    queue = importlib.import_module("gateway.queue")
    dbmod = importlib.import_module("gateway.db")
    jid = (await api.post("/v1/jobs", json=body())).json()["id"]
    async with public.Session.begin() as db:
        row = await db.get(dbmod.Job, jid)
        row.origin = origin
        model = await db.get(dbmod.Model, row.model_id)
        model.enabled = False
        (await db.get(dbmod.Client, client["id"])).require_agent = require_agent
        if has_route:
            row.route_id = "disabled-test-route"
            db.add(
                dbmod.ModelRoute(
                    id=row.route_id,
                    model_id=model.id,
                    supplier="test-supplier",
                    channel=row.channel,
                    provider_model=model.provider_model,
                    protocol=row.protocol,
                    enabled=False,
                )
            )
    assert await queue.claim("worker") == (jid if accepted else None)
    async with public.Session() as db:
        row = await db.get(dbmod.Job, jid)
        assert row.status == ("preparing" if accepted else "queued")
        assert row.error is None and row.attempts == int(accepted)
    if not accepted:
        assert await queue.claim("worker") is None
        async with public.Session.begin() as db:
            (await db.get(dbmod.Model, body()["model"])).enabled = True
        assert await queue.claim("worker") == jid
    # Disabling (without deleting) a claimed target must not cancel accepted work.
    async with public.Session.begin() as db:
        (await db.get(dbmod.Model, body()["model"])).enabled = False
    calls = []

    async def transport(req):
        calls.append(req.method)
        if req.method == "POST":
            return httpx.Response(200, json={"task_id": "normal-provider-id"})
        return httpx.Response(200, json={"status": "SUCCESS", "usage": {"output_seconds": 8}})

    factory = httpx.AsyncClient
    monkeypatch.setattr(queue.httpx, "AsyncClient", lambda **kwargs: factory(transport=httpx.MockTransport(transport), **kwargs))
    monkeypatch.setattr(queue, "archive", AsyncMock(return_value={"media": [{"url": "https://tos.example/normal.mp4"}]}))
    await queue.process(jid)
    async with public.Session() as db:
        row = await db.get(dbmod.Job, jid)
        assert row.status == "succeeded" and row.provider_id == "normal-provider-id"
        assert row.usage == {"output_seconds": 8}
    assert calls == ["POST", "GET"]


@pytest.mark.asyncio
async def test_request_body_limit_and_no_charge_on_invalid_input(service, monkeypatch):
    api, ctl, public, c = service
    monkeypatch.setenv("MAX_REQUEST_BYTES", "50")
    assert (await api.post("/v1/jobs", json=body())).status_code == 413
    monkeypatch.setenv("MAX_REQUEST_BYTES", "100000")
    assert (
        await api.post(
            "/v1/jobs",
            json={
                "model": "gemini-omni-flash-preview",
                "payload": {"prompt": "test", "duration": 10, "metadata": {"task": "reference_to_video"}},
            },
        )
    ).status_code == 422
    assert (await ctl.get("/admin/jobs")).json()["total"] == 0


@pytest.mark.asyncio
async def test_canonical_video_and_image_endpoints_persist_native_requests(service):
    api, ctl, public, c = service
    response = await api.post(
        "/v1/videos", json={"model": "gemini-omni-flash-preview", "prompt": "test", "images": ["https://example.com/original.jpg"]}
    )
    assert response.status_code == 202
    async with public.Session() as db:
        row = await db.get(public.Job, response.json()["id"])
        assert row.payload["duration"] == 10
        assert row.payload["metadata"]["task"] == "reference_to_video"
        assert row.payload["images"] == ["https://example.com/original.jpg"]
    response = await api.post(
        "/v1/images",
        headers={"Idempotency-Key": "image-canonical"},
        json={"model": "gpt-image-2.5-flare", "prompt": "test", "images": ["https://example.com/original.jpg"]},
    )
    assert response.status_code == 202
    async with public.Session() as db:
        row = await db.get(public.Job, response.json()["id"])
        assert row.payload["image"] == "https://example.com/original.jpg"
        assert row.origin == "agent_test"
