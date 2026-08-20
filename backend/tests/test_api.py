def test_health(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert set(body) == {"ok"}


def test_release_info_without_deployment_manifest(client) -> None:
    response = client.get("/api/release")
    assert response.status_code == 200
    assert response.json() == {"version": None, "deployedAt": None}


def test_api_errors_are_logged_with_tracking_code_and_redaction(client) -> None:
    response = client.post("/api/auth/login", json={"username": "admin", "password": "wrong-password"})
    assert response.status_code == 401
    assert response.json()["errorCode"].startswith("ERR-")
    logs = client.get("/api/admin/api-errors").json()["items"]
    item = next(value for value in logs if value["errorCode"] == response.json()["errorCode"])
    assert item["path"] == "/api/auth/login"
    assert item["statusCode"] == 401
    assert item["requestPayload"]["password"] == "***"


def test_auth_me_and_refresh(client) -> None:
    assert client.get("/api/auth/me").json()["username"] == "admin"
    refreshed = client.post("/api/auth/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["accessToken"]


def test_forced_password_change_revokes_existing_sessions(client) -> None:
    username = "forced-password-user"
    created = client.post(
        "/api/admin/users",
        json={"username": username, "password": "initial-pass-123", "display_name": "Forced password", "role": "user"},
    )
    assert created.status_code == 201
    logged_in = client.post("/api/auth/login", json={"username": username, "password": "initial-pass-123"})
    assert logged_in.status_code == 200
    old_access = logged_in.json()["accessToken"]
    old_refresh = logged_in.cookies.get("mv_refresh_token")
    assert client.get("/api/projects", headers={"Authorization": f"Bearer {old_access}"}).status_code == 403

    changed = client.post(
        "/api/auth/change-password",
        headers={"Authorization": f"Bearer {old_access}"},
        json={"current_password": "initial-pass-123", "new_password": "changed-pass-456"},
    )
    assert changed.status_code == 200
    assert client.get("/api/projects", headers={"Authorization": f"Bearer {old_access}"}).status_code == 401
    assert client.get("/api/projects", headers={"Authorization": f"Bearer {changed.json()['accessToken']}"}).status_code == 200
    assert client.post("/api/auth/refresh", cookies={"mv_refresh_token": old_refresh}).status_code == 401

    restored = client.post("/api/auth/login", json={"username": "admin", "password": "secure-admin-123"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"


def test_login_rate_limit_is_shared_and_returns_retry_after(client) -> None:
    import asyncio
    import hashlib

    from app.redis_store import redis

    ip_key = hashlib.sha256(b"ip\0testclient").hexdigest()
    username_key = hashlib.sha256(b"username\0rate-limit-probe").hexdigest()
    asyncio.run(redis.delete(f"auth:login:{ip_key}", f"auth:login:{username_key}"))
    for _ in range(8):
        assert client.post("/api/auth/login", json={"username": "rate-limit-probe", "password": "wrong-pass"}).status_code == 401
    blocked = client.post("/api/auth/login", json={"username": "rate-limit-probe", "password": "wrong-pass"})
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "300"
    asyncio.run(redis.delete(f"auth:login:{ip_key}", f"auth:login:{username_key}"))


def test_upload_rejects_unsupported_or_mismatched_media(client) -> None:
    unsupported = client.post(
        "/api/uploads",
        files={"file": ("payload.exe", b"not-an-executable", "application/octet-stream")},
    )
    assert unsupported.status_code == 422
    mismatched = client.post(
        "/api/uploads",
        files={"file": ("avatar.png", b"not-a-png", "video/mp4")},
    )
    assert mismatched.status_code == 422


def test_account_balance_endpoint(client, monkeypatch) -> None:
    from app import main

    async def fake_balance(force=False):
        return {"available": True, "balance": "287.391936", "balanceDisplay": "287.39", "currency": "credits", "updatedAt": "2026-08-07T00:00:00Z", "message": None}

    monkeypatch.setattr(main, "query_business_balance", fake_balance)
    response = client.get("/api/account/balance?force=true")
    assert response.status_code == 200
    assert response.json()["balanceDisplay"] == "287.39"


def test_generation_not_found(client) -> None:
    response = client.get("/api/generations/missing")
    assert response.status_code == 404


def test_local_validation_errors_are_returned_in_chinese(client) -> None:
    response = client.post("/api/generations/videos", json={"prompt": "test", "duration": "not-a-number"})
    assert response.status_code == 422
    assert "duration：必须是整数" in response.json()["detail"]
    assert "Input should" not in response.json()["detail"]


def test_chat_lifecycle(client) -> None:
    created = client.post("/api/chat/sessions", json={}).json()
    session_id = created["id"]
    assert client.get(f"/api/chat/{session_id}").status_code == 200
    assert any(item["id"] == session_id for item in client.get("/api/chat/sessions").json())
    assert client.delete(f"/api/chat/{session_id}").json() == {"ok": True}


def test_generation_is_persisted(client) -> None:
    created = client.post("/api/generations/images", json={"prompt": "test"})
    assert created.status_code == 202
    job_id = created.json()["id"]
    fetched = client.get(f"/api/generations/{job_id}")
    assert fetched.status_code == 200
    assert fetched.json()["kind"] == "image"
