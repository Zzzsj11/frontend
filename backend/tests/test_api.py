def test_health(client) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["postgres"] is True
    assert body["redis"] is True


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
