def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_admin_dashboard_models_and_audit(client):
    dashboard = client.get("/api/admin/dashboard")
    assert dashboard.status_code == 200
    assert dashboard.json()["systemHumans"] == 32
    models = client.get("/api/admin/models").json()
    assert {m["modality"] for m in models} >= {"chat", "image", "video"}
    image = next(m for m in models if m["modality"] == "image")
    assert client.patch(f"/api/admin/models/{image['id']}", json={"status": "disabled"}).status_code == 200
    assert any(x["action"] == "model.update" for x in client.get("/api/admin/audit-logs").json())
    assert client.patch(f"/api/admin/models/{image['id']}", json={"status": "active"}).status_code == 200


def test_non_admin_cannot_access_admin_but_can_read_model_options(client):
    created = client.post("/api/admin/users", json={"username": "admin-console-user", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "admin-console-user", "password": "secure-pass-123"}).json()
    headers = bearer(login["accessToken"])
    assert client.get("/api/admin/dashboard", headers=headers).status_code == 403
    options = client.get("/api/model-options", headers=headers).json()
    assert any(x["id"] == "gpt-image-2" for x in options)
    client.delete(f"/api/admin/users/{created['id']}")
    # Restore the shared TestClient's refresh cookie for subsequent auth tests.
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"


def test_admin_read_models_projects_jobs_usage_and_errors(client):
    for path in ["projects", "jobs", "usage", "api-errors"]:
        response = client.get(f"/api/admin/{path}")
        assert response.status_code == 200
