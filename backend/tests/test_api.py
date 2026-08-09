def test_health(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["postgres"] is True
    assert body["redis"] is True


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
