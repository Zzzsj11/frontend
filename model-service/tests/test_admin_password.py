import importlib

import pytest
from sqlalchemy import select


@pytest.mark.asyncio
async def test_admin_change_revokes_all_tokens_and_never_falls_back_to_env(service, monkeypatch):
    _, ctl, _, _ = service
    old_password = "test-only-password"
    token = (await ctl.post("/admin/login", json={"username": "admin", "password": old_password})).json()["access_token"]
    original = ctl.headers["Authorization"]
    good = {"current_password": old_password, "new_password": "Newpass8", "confirmation": "Newpass8"}
    for invalid in ("short1", "12345678", "abcdefgh"):
        assert (
            await ctl.post("/admin/change-password", json={**good, "new_password": invalid, "confirmation": invalid})
        ).status_code == 422
    for invalid in (
        {"current_password": "wrongpass"},
        {"confirmation": "different8"},
        {"new_password": old_password, "confirmation": old_password},
    ):
        # The old fixture password has no digit, so the unchanged-password attempt is rejected by policy.
        assert (await ctl.post("/admin/change-password", json={**good, **invalid})).status_code in (400, 422)
    assert (await ctl.post("/admin/change-password", json=good)).status_code == 204
    for old in (original, "Bearer " + token):
        assert (await ctl.get("/admin/users", headers={"Authorization": old})).status_code == 401
        assert (await ctl.post("/admin/change-password", headers={"Authorization": old}, json=good)).status_code == 401
    assert (await ctl.post("/admin/login", json={"username": "admin", "password": old_password})).status_code == 401
    monkeypatch.setenv("ADMIN_PASSWORD", "AnotherEnv9")
    assert (await ctl.post("/admin/login", json={"username": "admin", "password": "AnotherEnv9"})).status_code == 401
    login = await ctl.post("/admin/login", json={"username": "admin", "password": "Newpass8"})
    assert login.status_code == 200
    ctl.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    assert (await ctl.get("/admin/users")).status_code == 200
    assert (
        await ctl.post(
            "/admin/change-password", json={"current_password": "Newpass8", "new_password": "Newpass8", "confirmation": "Newpass8"}
        )
    ).status_code == 400
    dbm = importlib.import_module("control.db")
    async with dbm.Session.begin() as db:
        row = await db.scalar(select(dbm.AdminCredential))
        assert row.auth_version == 2 and "Newpass8" not in row.password_hash
        row.deleted_at = dbm.now()
    assert (await ctl.get("/admin/users")).status_code == 401
    assert (await ctl.post("/admin/login", json={"username": "admin", "password": "AnotherEnv9"})).status_code == 401
    assert (await ctl.post("/admin/login", json={"username": "admin", "password": "Newpass8"})).status_code == 401


@pytest.mark.asyncio
async def test_admin_password_failures_are_persisted_and_rate_limited(service):
    _, ctl, _, _ = service
    body = {"current_password": "wrongpass", "new_password": "Goodpass8", "confirmation": "Goodpass8"}
    for _ in range(10):
        assert (await ctl.post("/admin/change-password", json=body)).status_code == 400
    assert (await ctl.post("/admin/change-password", json=body)).status_code == 429


@pytest.mark.asyncio
async def test_concurrent_admin_changes_only_one_old_session_can_commit(service):
    import asyncio

    _, ctl, _, _ = service
    responses = await asyncio.gather(
        *(
            ctl.post(
                "/admin/change-password",
                json={"current_password": "test-only-password", "new_password": f"Concurrent{i}9", "confirmation": f"Concurrent{i}9"},
            )
            for i in range(2)
        )
    )
    assert sorted(r.status_code for r in responses) == [204, 401]
    winner = next(i for i, response in enumerate(responses) if response.status_code == 204)
    assert (await ctl.post("/admin/login", json={"username": "admin", "password": f"Concurrent{winner}9"})).status_code == 200
