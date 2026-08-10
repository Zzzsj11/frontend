def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_and_login_user(client, username: str) -> tuple[str, dict[str, str]]:
    created = client.post("/api/admin/users", json={"username": username, "password": "secure-pass-123", "display_name": username})
    assert created.status_code == 201
    login = client.post("/api/auth/login", json={"username": username, "password": "secure-pass-123"})
    assert login.status_code == 200
    return created.json()["id"], bearer(login.json()["accessToken"])


def test_projects_and_private_resources_are_isolated(client) -> None:
    _, user_a = create_and_login_user(client, "user-a")
    _, user_b = create_and_login_user(client, "user-b")
    project_a = client.post("/api/projects", headers=user_a, json={"name": "A project"}).json()
    project_b = client.post("/api/projects", headers=user_b, json={"name": "B project"}).json()

    assert [item["id"] for item in client.get("/api/projects", headers=user_a).json()] == [project_a["id"]]
    assert [item["id"] for item in client.get("/api/projects", headers=user_b).json()] == [project_b["id"]]
    assert client.patch(f"/api/projects/{project_b['id']}", headers=user_a, json={"name": "stolen"}).status_code == 404
    assert client.delete(f"/api/projects/{project_b['id']}", headers=user_a).status_code == 404


def test_system_characters_are_visible_and_read_only_for_every_user(client) -> None:
    _, user = create_and_login_user(client, "system-role-viewer")
    humans = client.get("/api/digital-humans", headers=user).json()
    system_humans = [item for item in humans if item["scope"] == "system"]
    assert len(system_humans) == 32
    assert {item["style"] for item in system_humans} == {"男", "女", "儿童"}
    children = [item for item in system_humans if item["style"] == "儿童"]
    assert {item["name"] for item in children} == {"小男孩 01", "小女孩 01"}
    assert all(item["readOnly"] for item in children)
    assert all(item["originalAvatar"].endswith(("/031.jpg", "/032.jpg")) for item in children)
    assert all(item["avatar"].endswith(("/031.jpg", "/032.jpg")) for item in children)

    styles = client.get("/api/digital-human-styles", headers=user).json()
    system_styles = [item for item in styles if item["scope"] == "system"]
    assert [(item["name"], item["readOnly"]) for item in system_styles] == [("男", True), ("女", True), ("儿童", True)]
    luoli = next(item for item in humans if item["id"] == "dh-system-020")
    assert luoli["scope"] == "system"
    assert luoli["readOnly"] is True
    assert luoli["assetCode"] == "020" and "图片ID：020" in luoli["systemPrompt"]
    assert client.patch("/api/digital-humans/dh-system-020", headers=user, json={"name": "changed"}).status_code == 404
    assert client.delete("/api/digital-humans/dh-system-020", headers=user).status_code == 404


def test_uploaded_character_keeps_its_category_and_is_visible_immediately(client, monkeypatch) -> None:
    from app import domain

    monkeypatch.setattr(domain, "is_tos_url", lambda url: url.startswith("https://tos.test/"))
    _, headers = create_and_login_user(client, "uploaded-role-viewer")
    style = client.post("/api/digital-human-styles", headers=headers, json={"name": "用户上传"})
    assert style.status_code == 201
    created = client.post(
        "/api/digital-humans",
        headers=headers,
        json={
            "name": "上传角色",
            "style_id": style.json()["id"],
            "description": "上传测试角色",
            "avatar_url": "https://tos.test/users/uploaded-role-viewer/digital-humans/original.jpg",
            "avatar_thumbnail_url": "https://tos.test/users/uploaded-role-viewer/digital-humans/thumbnail.jpg",
            "source": "uploaded",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["style"] == "用户上传"
    listed = client.get("/api/digital-humans", headers=headers).json()
    assert any(item["id"] == created.json()["id"] and item["style"] == "用户上传" for item in listed)


def test_all_deletes_are_soft_deletes(client) -> None:
    user_id, headers = create_and_login_user(client, "soft-delete-user")
    project = client.post("/api/projects", headers=headers, json={"name": "Temporary"}).json()
    assert client.delete(f"/api/projects/{project['id']}", headers=headers).json() == {"ok": True}
    assert client.get("/api/projects", headers=headers).json() == []

    import sqlite3

    with sqlite3.connect("/tmp/mv-agent-backend-test.sqlite3") as connection:
        owner, deleted_at = connection.execute("SELECT user_id, deleted_at FROM projects WHERE id = ?", (project["id"],)).fetchone()
    assert owner == user_id
    assert deleted_at is not None


def test_general_storyboard_persists_type_specific_configuration(client) -> None:
    _, headers = create_and_login_user(client, "general-user")
    project = client.post("/api/projects", headers=headers, json={"name": "General MV"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=headers,
        json={
            "genre": "pop",
            "secondary_category": "positive-love",
            "tertiary_category": "young-crush",
            "season": "春",
            "age_group": "青年",
            "visual_style": "电影写实",
            "ratio": "16:9",
            "empty_shot_count": 1,
            "character_shot_count": 1,
            "total_duration": 10,
            "digital_human_ids": ["dh-system-020"],
            "overall_prompt": "统一暖色电影质感",
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["title"].startswith("通用分镜-")
    assert len(result["title"]) == len("通用分镜-20260810-01-23-38")
    assert result["storyboardConfig"]["genre"] == "pop"
    assert {line["shotType"] for line in result["lines"]} == {"empty", "character"}
    assert all(line["shotOptions"]["duration"] == round(line["plannedDuration"]) for line in result["lines"])
    assert [shot["materialDuration"] for shot in result["storyboardConfig"]["storyBible"]["shots"]] == [line["plannedDuration"] for line in result["lines"]]
    task = client.get(f"/api/tasks/{result['taskId']}", headers=headers).json()
    assert task["storyboardType"] == "general"
    assert task["overallPrompt"] == "统一暖色电影质感"


def test_material_exports_are_isolated_between_users(client, monkeypatch) -> None:
    from app import domain

    class Storage:
        async def put_file(self, key, path, content_type=None):
            return f"https://tos.test/{key}"

    monkeypatch.setattr(domain, "get_storage", lambda: Storage())
    _, user_a = create_and_login_user(client, "export-user-a")
    _, user_b = create_and_login_user(client, "export-user-b")
    project = client.post("/api/projects", headers=user_a, json={"name": "Export project"}).json()
    storyboard = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=user_a,
        json={
            "genre": "pop",
            "secondary_category": "positive",
            "season": "春",
            "age_group": "青年",
            "visual_style": "电影写实",
            "empty_shot_count": 1,
            "character_shot_count": 0,
            "total_duration": 5,
        },
    ).json()
    created = client.post(f"/api/tasks/{storyboard['taskId']}/material-exports", headers=user_a)
    assert created.status_code == 202
    export_id = created.json()["id"]
    assert client.get(f"/api/material-exports/{export_id}", headers=user_a).status_code == 200
    assert client.get(f"/api/material-exports/{export_id}", headers=user_b).status_code == 404
    assert client.get(f"/api/tasks/{storyboard['taskId']}/material-exports", headers=user_b).status_code == 404
