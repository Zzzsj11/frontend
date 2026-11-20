"""Password lifecycle tests use disposable accounts and never call suppliers."""

import pytest


@pytest.mark.asyncio
async def test_first_login_password_gate_and_session_revocation(service):
    api, ctl, _, _ = service
    credentials = {"username": "first@star-net.cn", "password": "Initial123"}
    created = await ctl.post("/admin/users", json={"username": credentials["username"], "initial_password": credentials["password"]})
    assert created.status_code == 201
    tokens = [(await api.post("/portal/login", json=credentials)).json()["access_token"] for _ in range(2)]
    auth = {"Authorization": "Bearer " + tokens[0]}
    me = (await api.get("/portal/me", headers=auth)).json()
    assert me["must_change_password"] is True and me["keys"] == []
    for path in ("/portal/jobs", "/portal/ledger"):
        assert (await api.get(path, headers=auth)).status_code == 403
    assert (await api.post("/portal/keys", headers=auth, json={"name": "first", "monthly_points": 0})).status_code == 403
    for value in ("abc1234", "12345678", "abcdefgh"):
        result = await api.post(
            "/portal/change-password",
            headers=auth,
            json={
                "current_password": credentials["password"],
                "new_password": value,
                "confirmation": value,
            },
        )
        assert result.status_code == 422
    body = {"current_password": credentials["password"], "new_password": "Abcd1234", "confirmation": "Abcd1234"}
    for invalid in (
        {"confirmation": "Other123"},
        {"current_password": "Wrong123"},
        {"new_password": "Initial123", "confirmation": "Initial123"},
    ):
        assert (await api.post("/portal/change-password", headers=auth, json={**body, **invalid})).status_code == 400
    assert (await api.post("/portal/change-password", headers=auth, json=body)).status_code == 204
    for token in tokens:
        old = {"Authorization": "Bearer " + token}
        assert (await api.get("/portal/me", headers=old)).status_code == 401
        assert (await api.post("/portal/change-password", headers=old, json=body)).status_code == 401
    assert (await api.post("/portal/login", json=credentials)).status_code == 401
    login = await api.post("/portal/login", json={**credentials, "password": "Abcd1234"})
    assert login.status_code == 200
    auth = {"Authorization": "Bearer " + login.json()["access_token"]}
    assert (await api.get("/portal/me", headers=auth)).json()["must_change_password"] is False
    assert (await api.get("/portal/jobs", headers=auth)).status_code == 200
    key = (await api.post("/portal/keys", headers=auth, json={"name": "first", "monthly_points": 0})).json()
    assert (
        await api.get("/v1/models", headers={"Authorization": "Bearer " + key["api_key"], "X-User-Id": created.json()["id"]})
    ).status_code == 200


async def test_portal_failure_windows_and_trusted_source(service, monkeypatch):
    from gateway.db import Audit, Session
    from sqlalchemy import func, select

    api, ctl, _, _ = service
    monkeypatch.setenv("PORTAL_TRUSTED_PROXY_HOST", "127.0.0.1")
    first, second = "first@star-net.cn", "second@star-net.cn"
    for name in [first, second]:
        assert (await ctl.post("/admin/users", json={"username": name, "initial_password": "Initial123"})).status_code == 201
    # One remaining attempt for the first account behind a shared ingress.
    async with Session.begin() as db:
        for idx in range(19):
            db.add(Audit(id=f"sample-{idx}", actor=first, action="portal.login.failed", target="192.0.2.1", detail={}))
    for name in (first, second):
        response = await api.post("/portal/login", json={"username": name, "password": "Initial123"}, headers={"X-Real-IP": "192.0.2.1"})
        assert response.status_code == 200
    async with Session() as db:
        assert await db.scalar(select(func.count()).select_from(Audit).where(Audit.action == "portal.login.failed")) == 19
    bad = {"username": first, "password": "Wrong123"}
    assert (await api.post("/portal/login", json=bad, headers={"X-Real-IP": "192.0.2.2"})).status_code == 401
    assert (await api.post("/portal/login", json=bad)).status_code == 429
    monkeypatch.setenv("PORTAL_TRUSTED_PROXY_HOST", "192.0.2.10")
    assert (await api.post("/portal/login", json={**bad, "username": second}, headers={"X-Real-IP": "192.0.2.2"})).status_code == 401
    async with Session() as db:
        assert (await db.scalars(select(Audit.target).where(Audit.actor == first, Audit.action == "portal.login.failed"))).all().count(
            "192.0.2.2"
        ) == 1
        assert await db.scalar(select(Audit.target).where(Audit.actor == second, Audit.action == "portal.login.failed")) == "127.0.0.1"
