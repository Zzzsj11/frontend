"""All amounts below are synthetic contract fixtures; these tests make no model calls."""

import asyncio
import importlib
from decimal import Decimal
from pathlib import Path

import pytest
from test_service import body


async def user_key(api, ctl, name="alice", monthly=20):
    name += "@star-net.cn"
    result = await ctl.post("/admin/users", json={"username": name, "initial_password": "test-password-123", "monthly_points": monthly})
    assert result.status_code == 201, result.text
    uid = result.json()["id"]
    token = (await api.post("/portal/login", json={"username": name, "password": "test-password-123"})).json()["access_token"]
    changed = await api.post(
        "/portal/change-password",
        headers={"Authorization": "Bearer " + token},
        json={
            "current_password": "test-password-123",
            "new_password": "test-password-456",
            "confirmation": "test-password-456",
        },
    )
    assert changed.status_code == 204, changed.text
    token = (await api.post("/portal/login", json={"username": name, "password": "test-password-456"})).json()["access_token"]
    key = await api.post("/portal/keys", headers={"Authorization": "Bearer " + token}, json={"name": name, "monthly_points": monthly})
    assert key.status_code == 201, key.text
    return uid, token, key.json()


def pricing(mode="text_to_video", rate="2", reserve="10"):
    return {
        "selector": {"mode": mode},
        "confirmed": True,
        "reserve_points": reserve,
        "description": "Synthetic test fixture, not supplier price",
        "source": "contract-test-only",
        "rates": [{"label": "output", "path": "completion_tokens", "unit": "1000000", "cny": rate}],
    }


async def publish(ctl, rule=None):
    response = await ctl.post("/admin/pricing/veo-3.1-generate-preview", json=rule or pricing())
    assert response.status_code == 200, response.text
    return response.json()


def headers(uid, key, idem="job1"):
    return {"Authorization": "Bearer " + key["api_key"], "X-User-Id": uid, "Idempotency-Key": idem}


@pytest.mark.asyncio
async def test_registration_binding_and_private_data(service):
    api, ctl, public, _ = service
    uid, token, key = await user_key(api, ctl)
    uid2, token2, _ = await user_key(api, ctl, "bob")
    auth = {"Authorization": "Bearer " + token}
    me = (await api.get("/portal/me", headers=auth)).json()
    assert len(me["keys"]) == 1 and me["keys"][0]["available_points"] == "20.000000"
    assert "api_key" not in str(me) and "password_hash" not in str(me)
    assert (await ctl.get("/admin/users", headers=auth)).status_code == 401
    assert (await api.post("/portal/keys", headers=auth, json={})).status_code == 422
    assert (await api.post("/v1/jobs", json=body(), headers=headers(uid2, key))).status_code == 403
    assert (await api.post("/v1/jobs", json=body(), headers=headers(uid, key))).status_code == 503
    await publish(ctl)
    response = await api.post("/v1/jobs", json=body(), headers=headers(uid, key))
    assert response.status_code == 202, response.text
    assert (await api.get("/portal/jobs", headers=auth)).json()["total"] == 1
    other = {"Authorization": "Bearer " + token2}
    assert (await api.get("/portal/jobs", headers=other)).json()["total"] == 0
    assert (await ctl.post(f"/admin/clients/{key['id']}/bind", json={"user_id": uid2})).status_code == 403
    assert (await api.post("/portal/logout", headers=auth)).status_code == 204
    assert (await api.get("/portal/me", headers=auth)).status_code == 401
    db = importlib.import_module("gateway.db")
    async with db.Session() as session:
        u = await session.get(db.User, uid)
        assert "test-password" not in u.password_hash


@pytest.mark.asyncio
async def test_atomic_reservations_idempotent_settlement_and_snapshot(service):
    api, ctl, public, _ = service
    uid, token, key = await user_key(api, ctl)
    initial = await publish(ctl)
    responses = await asyncio.gather(*(api.post("/v1/jobs", json=body(), headers=headers(uid, key, f"request-{i}")) for i in range(6)))
    assert sorted(r.status_code for r in responses) == [202, 202, 402, 402, 402, 402], [r.text for r in responses]
    successful = next(r for r in responses if r.status_code == 202)
    job = successful.json()
    # New price must not affect a previously accepted request.
    await publish(ctl, pricing(rate="100"))
    queue = importlib.import_module("gateway.queue")
    await queue.update(job["id"], status="succeeded", usage={"completion_tokens": 1500})
    await queue.update(job["id"], status="succeeded", usage={"completion_tokens": 1500})
    result = (await api.get("/v1/jobs/" + job["id"], headers=headers(uid, key))).json()
    assert result["billing"]["points"] == "0.300000"
    assert result["billing"]["status"] == "usage_priced"
    assert result["billing"]["rule"]["id"] == initial["id"]
    ledger = (await api.get("/portal/ledger", headers={"Authorization": "Bearer " + token})).json()["items"]
    charges = [r for r in ledger if r["kind"] == "task_charge"]
    assert len(charges) == 1 and charges[0]["points"] == "-0.300000"
    assert charges[0]["evidence"]["breakdown"][0]["quantity"] == "1500"
    correction = {"actual_cny": "0.001", "operation_id": "statement-correction", "reason": "核账退回差额", "reference": "fixture-bill-2"}
    for _ in range(2):
        assert (await ctl.post("/admin/jobs/" + job["id"] + "/reconcile", json=correction)).status_code == 200
    conflict = {**correction, "reference": "different-statement"}
    assert (await ctl.post("/admin/jobs/" + job["id"] + "/reconcile", json=conflict)).status_code == 409
    ledger = (await api.get("/portal/ledger", headers={"Authorization": "Bearer " + token})).json()["items"]
    refunds = [r for r in ledger if r["kind"] == "reconciliation"]
    assert len(refunds) == 1 and refunds[0]["points"] == "0.200000"


@pytest.mark.asyncio
async def test_monthly_reset_adjustment_audit_and_reconciliation(service, monkeypatch):
    api, ctl, public, _ = service
    uid, token, key = await user_key(api, ctl)
    await publish(ctl)
    cid = key["id"]
    plus = {"points": "5.125000", "reason": "合同测试临时增加", "operation_id": "credit-unique"}
    one = await ctl.post(f"/admin/clients/{cid}/adjust", json=plus)
    two = await ctl.post(f"/admin/clients/{cid}/adjust", json=plus)
    assert one.json()["id"] == two.json()["id"]
    assert (await ctl.post(f"/admin/clients/{cid}/adjust", json={**plus, "points": "6"})).status_code == 409
    minus = {"points": "-2", "reason": "合同测试临时扣减", "operation_id": "debit-unique"}
    assert (await ctl.post(f"/admin/clients/{cid}/adjust", json=minus)).status_code == 200
    assert (
        await ctl.post(f"/admin/clients/{cid}/adjust", json={**minus, "operation_id": "debit-too-large", "points": "-100"})
    ).status_code == 409
    assert (
        await api.post(f"/portal/keys/{cid}/quota", headers={"Authorization": "Bearer " + token}, json={"points": "30"})
    ).status_code == 200
    auth = {"Authorization": "Bearer " + token}
    before = (await api.get("/portal/me", headers=auth)).json()["keys"][0]
    assert before["monthly_balance"] == "30.000000" and before["extra_balance"] == "3.125000"
    credits = importlib.import_module("gateway.credits")
    monkeypatch.setattr(credits, "month", lambda: "2099-01")
    after = (await api.get("/portal/me", headers=auth)).json()["keys"][0]
    assert after["monthly_balance"] == "30.000000" and after["extra_balance"] == "3.125000"
    await api.get("/portal/me", headers=auth)
    records = (await api.get("/portal/ledger", headers=auth)).json()["items"]
    assert len([r for r in records if r["kind"] == "monthly_reset"]) == 2
    monkeypatch.setattr(importlib.import_module("control.credits"), "month", lambda: "2099-01")
    job = (await api.post("/v1/jobs", json=body(), headers=headers(uid, key))).json()
    await importlib.import_module("gateway.queue").update(job["id"], status="failed", usage={})
    pending = (await api.get("/v1/jobs/" + job["id"], headers=headers(uid, key))).json()["billing"]
    assert pending["points"] is None and pending["reserved_points"] == "10.000000"
    statement = {"actual_cny": "0", "operation_id": "statement-unique", "reason": "渠道确认未扣费", "reference": "fixture-statement-1"}
    assert (await ctl.post("/admin/jobs/" + job["id"] + "/reconcile", json=statement)).status_code == 200
    assert (await ctl.post("/admin/jobs/" + job["id"] + "/reconcile", json=statement)).status_code == 200
    result = (await api.get("/v1/jobs/" + job["id"], headers=headers(uid, key))).json()["billing"]
    assert result["status"] == "settled" and result["reserved_points"] == "0.000000"


@pytest.mark.asyncio
async def test_mode_specific_prices_cache_usage_and_determinism(service):
    api, ctl, public, _ = service
    await publish(ctl)
    await publish(ctl, pricing(mode="reference_to_video", rate="4"))
    credits = importlib.import_module("gateway.credits")
    db = importlib.import_module("gateway.db")
    async with db.Session() as session:
        m = await session.get(db.Model, "veo-3.1-generate-preview")
        text = await credits.rule(session, m.id, credits.dimensions(m, {"prompt": "x"}))
        refs = await credits.rule(session, m.id, credits.dimensions(m, {"images": ["https://example.com/a.png"]}))
        assert text["rates"][0]["cny"] == "2" and refs["rates"][0]["cny"] == "4"
    conflicting = {**pricing(), "selector": {"resolution": "720p"}}
    assert (await ctl.post("/admin/pricing/veo-3.1-generate-preview", json=conflicting)).status_code == 409
    from types import SimpleNamespace

    job = SimpleNamespace(
        usage={"prompt_tokens": 1000, "completion_tokens": 100, "prompt_tokens_details": {"cached_tokens": 200}},
        pricing_snapshot={
            "confirmed": True,
            "rates": [
                {
                    "label": "input",
                    "path": "prompt_tokens",
                    "subtract": ["prompt_tokens_details.cached_tokens"],
                    "unit": "1000000",
                    "cny": "10",
                },
                {"label": "cache", "path": "prompt_tokens_details.cached_tokens", "unit": "1000000", "cny": "1"},
                {"label": "output", "path": "completion_tokens", "unit": "1000000", "cny": "20"},
            ],
        },
    )
    assert credits.measured_points(job)[0] == Decimal("1.020000")
    job.usage.pop("completion_tokens")
    assert credits.measured_points(job) is None
    root = Path(__file__).resolve().parents[1]
    assert (root / "public-api/gateway/credits.py").read_bytes() == (root / "admin-api/control/credits.py").read_bytes()


@pytest.mark.asyncio
async def test_public_status_projection_preserves_internal_state(service):
    api, ctl, public, _ = service
    uid, token, key = await user_key(api, ctl)
    await publish(ctl)
    jid = (await api.post("/v1/jobs", json=body(), headers=headers(uid, key))).json()["id"]
    db = importlib.import_module("gateway.db")
    for internal, external in [
        ("queued", "queued"),
        ("preparing", "running"),
        ("submitting", "running"),
        ("running", "running"),
        ("archiving", "running"),
        ("recoverable", "running"),
        ("manual_review", "failed"),
        ("failed", "failed"),
        ("succeeded", "succeeded"),
    ]:
        async with db.Session.begin() as session:
            job = await session.get(db.Job, jid)
            job.status = internal
        assert (await api.get("/v1/jobs/" + jid, headers=headers(uid, key))).json()["status"] == external
        portal = (await api.get("/portal/jobs", headers={"Authorization": "Bearer " + token})).json()["items"][0]
        assert portal["status"] == external
        assert (await ctl.get("/admin/jobs/" + jid)).json()["status"] == internal
        async with db.Session() as session:
            assert (await session.get(db.Job, jid)).status == internal


@pytest.mark.asyncio
async def test_registration_requires_exact_company_email(service):
    api, ctl, _, _ = service
    assert (await api.post("/portal/register", json={})).status_code == 403
    for name in (
        "alice",
        "alice@example.com",
        "alice@sub.star-net.cn",
        "alice@star-net.cn.evil.com",
        "alice@@star-net.cn",
        ".alice@star-net.cn",
        "alice..bob@star-net.cn",
    ):
        response = await ctl.post("/admin/users", json={"username": name, "initial_password": "test-password-123"})
        assert response.status_code == 422
    response = await ctl.post("/admin/users", json={"username": "Alice@STAR-NET.CN", "initial_password": "test-password-123"})
    assert response.status_code == 201
    assert response.json()["username"] == "alice@star-net.cn"
    duplicate = await ctl.post("/admin/users", json={"username": "alice@star-net.cn", "initial_password": "test-password-123"})
    assert duplicate.status_code == 409
