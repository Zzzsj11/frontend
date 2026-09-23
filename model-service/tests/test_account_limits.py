"""Account-wide limits and ownership; synthetic jobs only, no supplier requests."""

import asyncio
import importlib
from datetime import datetime, timezone

import pytest
from test_portal_billing import headers, publish, user_key
from test_service import body


@pytest.mark.asyncio
async def test_user_key_ownership_and_atomic_ten_key_limit(service):
    api, ctl, _, _ = service
    uid, token, first = await user_key(api, ctl)
    uid2, token2, other = await user_key(api, ctl, "bob")
    auth = {"Authorization": "Bearer " + token}
    results = await asyncio.gather(
        *(api.post("/portal/keys", headers=auth, json={"name": f"key-{i}", "monthly_points": 100}) for i in range(11))
    )
    assert sorted(r.status_code for r in results) == [201] * 9 + [409] * 2
    me = (await api.get("/portal/me", headers=auth)).json()
    assert me["quota"]["key_count"] == 10 and len(me["keys"]) == 10
    assert me["quota"]["allocated_points"] == "920.000000"
    assert "api_key" not in str(me) and "key_hash" not in str(me)
    for path, method, data in (
        (f"/portal/keys/{other['id']}/quota", "POST", {"points": 999}),
        (f"/portal/keys/{other['id']}", "DELETE", None),
    ):
        assert (await api.request(method, path, headers=auth, json=data)).status_code == 404
    assert (await api.post("/portal/keys", headers=auth, json={"name": "spoof", "monthly_points": 1, "user_id": uid2})).status_code == 422
    assert (await api.post(f"/portal/users/{uid}/quota", headers=auth, json={"points": 999})).status_code == 404
    assert (await ctl.post(f"/admin/users/{uid}/quota", headers=auth, json={"points": 999})).status_code == 401
    assert (await ctl.post("/admin/users", headers=auth, json={"username": "intruder@star-net.cn"})).status_code == 401
    assert (await ctl.post("/admin/clients", json={"name": "bound", "user_id": uid})).status_code == 403
    assert (await ctl.post(f"/admin/clients/{first['id']}/quota", json={"points": 100})).status_code == 403
    assert (await api.delete(f"/portal/keys/{first['id']}", headers=auth)).status_code == 204
    assert (await api.get("/v1/models", headers=headers(uid, first))).status_code == 401
    assert (await api.post("/portal/keys", headers=auth, json={"name": "replacement", "monthly_points": 500})).status_code == 201
    assert (await api.get("/portal/me", headers={"Authorization": "Bearer " + token2})).json()["quota"]["key_count"] == 1


@pytest.mark.asyncio
async def test_aggregate_reservations_spending_reallocation_and_retired_keys(service):
    api, ctl, _, _ = service
    uid, token, first = await user_key(api, ctl, monthly=20)
    auth = {"Authorization": "Bearer " + token}
    second = (await api.post("/portal/keys", headers=auth, json={"name": "second", "monthly_points": 100})).json()
    await publish(ctl)
    results = await asyncio.gather(
        *(api.post("/v1/jobs", headers=headers(uid, key, f"parallel-{i}"), json=body()) for i, key in enumerate([first, second, second]))
    )
    assert sorted(r.status_code for r in results) == [202, 202, 402]
    me = (await api.get("/portal/me", headers=auth)).json()
    assert me["quota"]["reserved_points"] == "20.000000"
    # Removing an in-flight key must not release its reservation or future charge.
    assert (await api.delete(f"/portal/keys/{first['id']}", headers=auth)).status_code == 204
    assert (await api.get("/portal/me", headers=auth)).json()["quota"]["reserved_points"] == "20.000000"
    queue = importlib.import_module("gateway.queue")
    for response in results:
        if response.status_code == 202:
            await queue.update(response.json()["id"], status="succeeded", usage={"completion_tokens": 30000})
    me = (await api.get("/portal/me", headers=auth)).json()
    assert me["quota"]["spent_points"] == "12.000000"
    assert me["quota"]["available_points"] == "8.000000"
    # Raising key caps, deleting keys, or adding wallet credits cannot bypass account limit.
    assert (await api.post(f"/portal/keys/{second['id']}/quota", headers=auth, json={"points": 999})).status_code == 200
    assert (await api.post("/v1/jobs", headers=headers(uid, second, "blocked"), json=body())).status_code == 402
    assert (await ctl.post(f"/admin/users/{uid}/quota", json={"points": 30})).status_code == 200
    assert (await api.get("/portal/me", headers=auth)).json()["quota"]["spent_points"] == "12.000000"
    # Key cap is independently enforced even with account credit available.
    assert (await api.post(f"/portal/keys/{second['id']}/quota", headers=auth, json={"points": 0})).status_code == 200
    assert (await api.post("/v1/jobs", headers=headers(uid, second, "zero-key"), json=body())).status_code == 402
    assert (await api.post(f"/portal/keys/{second['id']}/quota", headers=auth, json={"points": 999})).status_code == 200
    response = await api.post("/v1/jobs", headers=headers(uid, second, "allowed"), json=body())
    assert response.status_code == 202, response.text


@pytest.mark.asyncio
async def test_beijing_month_boundary_preserves_reservations(service, monkeypatch):
    api, ctl, _, _ = service
    uid, token, key = await user_key(api, ctl, monthly=20)
    await publish(ctl)
    credits = importlib.import_module("gateway.credits")
    dbm = importlib.import_module("gateway.db")
    # A settled charge just before Beijing midnight belongs only to September.
    async with dbm.Session.begin() as db:
        db.add(
            dbm.Ledger(
                id="boundary",
                client_id=key["id"],
                user_id=uid,
                operation_id="boundary",
                kind="task_charge",
                points=-5,
                monthly_after=15,
                extra_after=0,
                actor="test",
                reason="fixture",
                evidence={},
                created_at=datetime(2026, 9, 30, 15, 59, tzinfo=timezone.utc),
            )
        )
    monkeypatch.setattr(credits, "now", lambda: datetime(2026, 9, 30, 15, 59, 30, tzinfo=timezone.utc))
    auth = {"Authorization": "Bearer " + token}
    assert (await api.get("/portal/me", headers=auth)).json()["quota"]["spent_points"] == "5.000000"
    response = await api.post("/v1/jobs", headers=headers(uid, key), json=body())
    assert response.status_code == 202, response.text
    monkeypatch.setattr(credits, "now", lambda: datetime(2026, 9, 30, 16, 0, tzinfo=timezone.utc))
    me = (await api.get("/portal/me", headers=auth)).json()
    assert me["quota"]["billing_month"] == "2026-10"
    assert me["quota"]["spent_points"] == "0.000000"
    assert me["quota"]["reserved_points"] == "10.000000"
    assert me["quota"]["available_points"] == "10.000000"
