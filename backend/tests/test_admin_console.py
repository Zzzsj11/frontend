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
    assert any(x["action"] == "model.update" for x in client.get("/api/admin/audit-logs").json()["items"])
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


def test_admin_lists_are_paginated_with_offset_and_total(client):
    """projects/audit-logs/api-errors 分页契约：{total, items} + offset 生效 + limit 上限封顶。"""
    projects = client.get("/api/admin/projects").json()
    assert isinstance(projects["total"], int) and projects["total"] >= 0
    assert len(projects["items"]) <= 50  # 默认 limit=50
    paged = client.get("/api/admin/projects", params={"limit": 10, "offset": 0}).json()
    assert len(paged["items"]) <= 10
    assert paged["total"] == projects["total"]
    # 超大 limit 被钳制（防拉挂数据库）
    clamped = client.get("/api/admin/projects", params={"limit": 99999}).json()
    assert len(clamped["items"]) <= 300
    audit = client.get("/api/admin/audit-logs").json()
    assert "total" in audit and "items" in audit
    errors = client.get("/api/admin/api-errors").json()
    assert "total" in errors and "items" in errors
    errors_clamped = client.get("/api/admin/api-errors", params={"limit": 99999}).json()
    assert len(errors_clamped["items"]) <= 500


def test_admin_users_list_has_limit_cap(client):
    """用户列表强制 limit 上限：超大请求不返回超过 500 个用户。"""
    response = client.get("/api/admin/users", params={"limit": 99999})
    assert response.status_code == 200
    assert len(response.json()) <= 500


def test_admin_can_set_per_user_daily_model_limits(client):
    created = client.post(
        "/api/admin/users",
        json={
            "username": "custom-daily-limits",
            "password": "secure-pass-123",
            "daily_chat_limit": 12,
            "daily_image_limit": 7,
            "daily_video_limit": 4,
        },
    )
    assert created.status_code == 201
    assert created.json()["dailyChatLimit"] == 12
    updated = client.patch(
        f"/api/admin/users/{created.json()['id']}",
        json={"daily_chat_limit": 20, "daily_image_limit": 10, "daily_video_limit": 5},
    )
    assert updated.status_code == 200
    assert updated.json()["dailyChatLimit"] == 20
    assert updated.json()["dailyImageLimit"] == 10
    assert updated.json()["dailyVideoLimit"] == 5
