def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_and_login_user(client, username: str) -> tuple[str, dict[str, str]]:
    created = client.post("/api/admin/users", json={"username": username, "password": "secure-pass-123", "display_name": username})
    assert created.status_code == 201
    login = client.post("/api/auth/login", json={"username": username, "password": "secure-pass-123"})
    assert login.status_code == 200
    changed = client.post(
        "/api/auth/change-password",
        headers=bearer(login.json()["accessToken"]),
        json={"current_password": "secure-pass-123", "new_password": "secure-pass-456"},
    )
    assert changed.status_code == 200
    return created.json()["id"], bearer(changed.json()["accessToken"])


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
            "genre": "流行歌曲",
            "secondary_category": "爱情积极",
            "tertiary_category": "青涩心动",
            "season": "春",
            "gender": "女",
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
    assert result["status"] == "parsed"
    assert result["title"].startswith("通用分镜-")
    assert len(result["title"]) == len("通用分镜-20260810-01-23-38")
    assert result["storyboardConfig"]["genre"] == "流行歌曲"
    assert result["storyboardConfig"]["gender"] == "女"
    # 大纲异步生成前，lines 为占位：shotType 统一 empty，人物待后台回填
    assert {line["shotType"] for line in result["lines"]} == {"empty"}
    assert all(line["shotOptions"]["duration"] == round(line["plannedDuration"]) for line in result["lines"])
    assert all(line["shotOptions"]["outlineStatus"] == "pending" for line in result["lines"])
    task = client.get(f"/api/tasks/{result['taskId']}", headers=headers).json()
    assert task["storyboardType"] == "general"
    assert task["overallPrompt"] == "统一暖色电影质感"
    assert task["status"] == "parsed"


def test_general_storyboard_allows_genre_without_secondary_category(client) -> None:
    _, headers = create_and_login_user(client, "no-secondary-user")
    project = client.post("/api/projects", headers=headers, json={"name": "Xiqu MV"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=headers,
        json={
            "genre": "戏曲",
            "season": "春",
            "gender": "女",
            "age_group": "青年",
            "visual_style": "国风",
            "ratio": "16:9",
            "empty_shot_count": 1,
            "character_shot_count": 1,
            "total_duration": 10,
            "digital_human_ids": ["dh-system-020"],
        },
    )
    assert response.status_code == 201
    result = response.json()
    assert result["status"] == "parsed"
    assert result["storyboardConfig"]["secondary_category"] is None


def test_general_storyboard_outline_generation_is_async(client, monkeypatch) -> None:
    import time

    from app import domain

    async def fake_general_outline(*, config, selected_humans, on_progress=None):
        if on_progress:
            await on_progress({"phase": "generating", "shotsDone": 0, "shotsTotal": 2})
        return {
            "shots": [
                {
                    "index": 0,
                    "shotType": "empty",
                    "outlineScene": "空旷街道夜景",
                    "outlineShot": "低机位缓慢推进",
                    "requiredCharacterIds": [],
                    "intent": "建立孤独氛围",
                    "characterAction": "无人环境",
                    "emotionalFocus": "孤寂",
                    "cameraPurpose": "交代环境",
                },
                {
                    "index": 1,
                    "shotType": "character",
                    "outlineScene": "窗边黄昏",
                    "outlineShot": "人物凝视远方",
                    "requiredCharacterIds": ["dh-system-020"],
                    "intent": "引入人物情绪",
                    "characterAction": "人物望向窗外",
                    "emotionalFocus": "思念",
                    "cameraPurpose": "推进到近景",
                },
            ],
            "usageRecords": [{"operation": "general_story_outline", "usage": {}, "requestId": "gen-outline-test"}],
            "usage": {},
            "requestId": "gen-outline-test",
        }

    monkeypatch.setattr(domain, "generate_general_story_outline", fake_general_outline)
    _, headers = create_and_login_user(client, "general-async-user")
    project = client.post("/api/projects", headers=headers, json={"name": "General Async"}).json()
    created = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=headers,
        json={
            "genre": "流行歌曲",
            "secondary_category": "爱情消极",
            "season": "秋",
            "gender": "女",
            "age_group": "青年",
            "visual_style": "电影写实",
            "ratio": "16:9",
            "empty_shot_count": 1,
            "character_shot_count": 1,
            "total_duration": 10,
            "digital_human_ids": ["dh-system-020"],
        },
    )
    assert created.status_code == 201
    task_id = created.json()["taskId"]
    assert created.json()["status"] == "parsed"
    # 创建阶段不触发 LLM，storyBible 尚未生成
    assert "storyBible" not in created.json()["storyboardConfig"]

    trigger = client.post(f"/api/tasks/{task_id}/storyboard-outline/regenerate", headers=headers)
    assert trigger.status_code == 202
    assert trigger.json()["status"] == "outlining"

    deadline = time.monotonic() + 3
    task = None
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if task["status"] != "outlining":
            break
        time.sleep(0.01)
    assert task is not None and task["status"] == "generating"
    assert task["storyboardConfig"]["storyBible"]["shots"][0]["shotType"] == "empty"
    assert task["storyboardConfig"]["storyBible"]["shots"][1]["shotType"] == "character"
    lines = task["lines"]
    assert [line["shotType"] for line in lines] == ["empty", "character"]
    assert lines[1]["digitalHumanIds"] == ["dh-system-020"]
    assert all(line["shotOptions"]["outlineStatus"] == "ready" for line in lines)


def test_general_storyboard_all_empty_outline_needs_no_cast(client, monkeypatch) -> None:
    import time

    from app import domain

    async def fake_general_outline(*, config, selected_humans, on_progress=None):
        assert selected_humans == []
        return {
            "shots": [
                {
                    "index": 0,
                    "shotType": "empty",
                    "outlineScene": "雨夜空街",
                    "outlineShot": "缓慢横移",
                    "requiredCharacterIds": [],
                    "intent": "建立氛围",
                    "characterAction": "雨水落下",
                    "emotionalFocus": "孤寂",
                    "cameraPurpose": "交代环境",
                }
            ],
            "usageRecords": [],
            "usage": {},
            "requestId": "empty-outline",
        }

    monkeypatch.setattr(domain, "generate_general_story_outline", fake_general_outline)
    _, headers = create_and_login_user(client, "empty-outline-user")
    project = client.post("/api/projects", headers=headers, json={"name": "Empty MV"}).json()
    created = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=headers,
        json={
            "genre": "流行歌曲",
            "season": "秋",
            "gender": "女",
            "age_group": "青年",
            "visual_style": "电影写实",
            "empty_shot_count": 1,
            "character_shot_count": 0,
            "total_duration": 5,
            "digital_human_ids": [],
        },
    )
    task_id = created.json()["taskId"]
    trigger = client.post(f"/api/tasks/{task_id}/storyboard-outline/regenerate", headers=headers)
    assert trigger.status_code == 202, trigger.text
    deadline = time.monotonic() + 3
    task = None
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}", headers=headers).json()
        if task["status"] != "outlining":
            break
        time.sleep(0.02)
    assert task is not None and task["status"] == "generating"
    assert task["lines"][0]["shotType"] == "empty"
    assert task["lines"][0]["digitalHumanIds"] == []


def test_material_exports_are_isolated_between_users(client, monkeypatch) -> None:
    from app import domain

    class Storage:
        async def put_file(self, key, path, content_type=None, progress_callback=None):
            return f"https://tos.test/{key}"

    monkeypatch.setattr(domain, "get_storage", lambda: Storage())
    _, user_a = create_and_login_user(client, "export-user-a")
    _, user_b = create_and_login_user(client, "export-user-b")
    project = client.post("/api/projects", headers=user_a, json={"name": "Export project"}).json()
    storyboard = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=user_a,
        json={
            "genre": "流行歌曲",
            "secondary_category": "爱情消极",
            "season": "春",
            "gender": "女",
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


def test_active_generations_reflect_running_jobs_only(client) -> None:
    import sqlite3
    from datetime import datetime, timezone

    from conftest import TEST_DB

    user_id, headers = create_and_login_user(client, "active-gen-user")
    other_id, other = create_and_login_user(client, "active-gen-other")
    project = client.post("/api/projects", headers=headers, json={"name": "Active gen"}).json()
    storyboard = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=headers,
        json={
            "genre": "流行歌曲",
            "secondary_category": "爱情消极",
            "season": "春",
            "gender": "女",
            "age_group": "青年",
            "visual_style": "电影写实",
            "empty_shot_count": 1,
            "character_shot_count": 1,
            "total_duration": 10,
            "digital_human_ids": ["dh-system-020"],
        },
    )
    assert storyboard.status_code == 201
    task_id = storyboard.json()["taskId"]
    line_id = storyboard.json()["lines"][0]["id"]

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")

    def insert_job(job_id: str, kind: str, status: str, task: str | None, line: str | None, owner: str) -> None:
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute(
                "INSERT INTO generation_jobs (id, kind, status, progress, request, attempt, user_id, project_id, project_task_id, storyboard_line_id, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, kind, status, 10, "{}", 1, owner, project["id"], task, line, now, now),
            )
            connection.commit()
        finally:
            connection.close()

    insert_job("job-active-v", "video", "running", task_id, line_id, user_id)
    insert_job("job-done-i", "image", "succeeded", task_id, line_id, user_id)
    insert_job("job-no-task", "image", "queued", None, None, user_id)
    insert_job("job-other-user", "video", "queued", task_id, line_id, other_id)

    listed = client.get(f"/api/tasks/{task_id}/generations/active", headers=headers)
    assert listed.status_code == 200
    active = listed.json()
    assert [job["id"] for job in active] == ["job-active-v"]
    assert active[0]["storyboardLineId"] == line_id
    assert active[0]["kind"] == "video"
    assert client.get(f"/api/tasks/{task_id}/generations/active", headers=other).status_code == 404


# ---------- 拖拽排序（reorder）、素材导出清理、数字人列表排序 ----------


def test_project_reorder_applies_only_to_own_projects(client) -> None:
    _, headers = create_and_login_user(client, "reorder-owner")
    ids = [client.post("/api/projects", headers=headers, json={"name": name}).json()["id"] for name in ("P1", "P2", "P3")]

    reordered = [ids[2], ids[0], ids[1]]
    response = client.patch("/api/projects/reorder", headers=headers, json={"order": reordered})
    assert response.status_code == 200
    listed = client.get("/api/projects", headers=headers).json()
    assert [item["id"] for item in listed] == reordered

    # 其它用户的项目 id 混入：被静默忽略（不占排序位，也不改写他人数据）
    _, outsider = create_and_login_user(client, "reorder-outsider")
    foreign = client.post("/api/projects", headers=outsider, json={"name": "foreign"}).json()
    client.patch("/api/projects/reorder", headers=headers, json={"order": [ids[1], foreign["id"], ids[2]]})
    listed = client.get("/api/projects", headers=headers).json()
    assert [item["id"] for item in listed] == [ids[1], ids[0], ids[2]]
    assert [item["id"] for item in client.get("/api/projects", headers=outsider).json()] == [foreign["id"]]


def test_task_reorder_scoped_to_project_owner(client) -> None:
    _, headers = create_and_login_user(client, "task-reorder-owner")
    _, outsider = create_and_login_user(client, "task-reorder-outsider")
    project = client.post("/api/projects", headers=headers, json={"name": "T"}).json()
    task_ids = [client.post(f"/api/projects/{project['id']}/tasks", headers=headers, json={"title": title}).json()["id"] for title in ("t1", "t2", "t3")]

    reordered = [task_ids[2], task_ids[0], task_ids[1]]
    response = client.patch(f"/api/projects/{project['id']}/tasks/reorder", headers=headers, json={"order": reordered})
    assert response.status_code == 200

    def task_order(project_id: str) -> list[str]:
        listed = client.get("/api/projects", headers=headers).json()
        item = next(entry for entry in listed if entry["id"] == project_id)
        return [task["id"] for task in item["tasks"]]

    assert task_order(project["id"]) == reordered

    # 越权：outsider 对该项目重排 → 404（项目不可见）
    assert client.patch(f"/api/projects/{project['id']}/tasks/reorder", headers=outsider, json={"order": reordered}).status_code == 404

    # 跨项目的 task id 混入：按 project_id 过滤跳过，不影响其它项目
    other_project = client.post("/api/projects", headers=headers, json={"name": "T2"}).json()
    other_task = client.post(f"/api/projects/{other_project['id']}/tasks", headers=headers, json={"title": "x"}).json()
    client.patch(
        f"/api/projects/{project['id']}/tasks/reorder",
        headers=headers,
        json={"order": [task_ids[1], other_task["id"], task_ids[2], task_ids[0]]},
    )
    assert task_order(project["id"]) == [task_ids[1], task_ids[2], task_ids[0]]
    assert task_order(other_project["id"]) == [other_task["id"]]


def _set_export_status(export_id: str, status: str) -> None:
    import sqlite3

    from conftest import TEST_DB

    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute("UPDATE material_exports SET status = ? WHERE id = ?", (status, export_id))
        connection.commit()
    finally:
        connection.close()


def test_material_export_supersedes_finished_history(client, monkeypatch) -> None:
    import sqlite3
    from dataclasses import replace

    from conftest import TEST_DB

    from app import domain

    async def fake_export(export_id: str, job) -> dict:
        # 不推进导出状态：导出记录保持 queued，便于测试幂等与清理分支
        return {}

    monkeypatch.setattr(domain, "_run_material_export", fake_export)

    _, headers = create_and_login_user(client, "export-clean-owner")
    project = client.post("/api/projects", headers=headers, json={"name": "E"}).json()
    task = client.post(f"/api/projects/{project['id']}/tasks", headers=headers, json={"title": "e"}).json()
    other_task = client.post(f"/api/projects/{project['id']}/tasks", headers=headers, json={"title": "e2"}).json()

    try:
        first = client.post(f"/api/tasks/{task['id']}/material-exports", headers=headers)
        assert first.status_code == 202
        # 进行中重复提交：幂等返回同一导出，不产生新记录
        again = client.post(f"/api/tasks/{task['id']}/material-exports", headers=headers)
        assert again.status_code == 202
        assert again.json()["id"] == first.json()["id"]

        # first 进入终态后再次导出：产生新记录，旧的 ready 记录被软删（每个子项目只留最新一次）
        _set_export_status(first.json()["id"], "ready")
        second = client.post(f"/api/tasks/{task['id']}/material-exports", headers=headers)
        assert second.status_code == 202
        assert second.json()["id"] != first.json()["id"]
        listed = client.get(f"/api/tasks/{task['id']}/material-exports", headers=headers).json()
        assert [item["id"] for item in listed] == [second.json()["id"]]

        # failed 同样会被清理；其它任务的导出不受牵连
        _set_export_status(second.json()["id"], "failed")
        foreign = client.post(f"/api/tasks/{other_task['id']}/material-exports", headers=headers)
        assert foreign.status_code == 202
        _set_export_status(foreign.json()["id"], "ready")
        third = client.post(f"/api/tasks/{task['id']}/material-exports", headers=headers)
        assert third.status_code == 202
        listed = client.get(f"/api/tasks/{task['id']}/material-exports", headers=headers).json()
        assert [item["id"] for item in listed] == [third.json()["id"]]
        assert client.get(f"/api/material-exports/{foreign.json()['id']}", headers=headers).status_code == 200

        # 用户级并发上限：存在进行中导出时，对另一个任务发起导出返回 429
        monkeypatch.setattr(domain, "settings", replace(domain.settings, export_per_user_concurrency=1))
        blocked = client.post(f"/api/tasks/{other_task['id']}/material-exports", headers=headers)
        assert blocked.status_code == 429
        assert "导出" in blocked.json()["detail"]
    finally:
        # 清场：收编仍 queued 的导出，避免占用后续测试的用户级并发额度
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute("UPDATE material_exports SET status = 'cancelled' WHERE status IN ('queued', 'running')")
            connection.commit()
        finally:
            connection.close()


def test_material_export_progress_counters_never_regress(client, monkeypatch) -> None:
    import asyncio

    from app import domain
    from app.database import session_factory
    from app.jobs import Job
    from app.models import MaterialExportModel

    user_id, headers = create_and_login_user(client, "export-progress-owner")
    project = client.post("/api/projects", headers=headers, json={"name": "progress"}).json()
    task = client.post(f"/api/projects/{project['id']}/tasks", headers=headers, json={"title": "progress"}).json()
    export_id = "export-progress-monotonic"

    async def scenario() -> None:
        async with session_factory() as session:
            session.add(MaterialExportModel(id=export_id, user_id=user_id, project_task_id=task["id"]))
            await session.commit()

        async def no_job_progress(_job, _progress):
            return None

        monkeypatch.setattr(domain.jobs, "update_progress", no_job_progress)
        job = Job(id="job-export-progress", kind="export")
        await domain._set_export_progress(export_id, job, 20, "下载中", processed_assets=5, processed_bytes=12_000, total_bytes=20_000)
        await domain._set_export_progress(export_id, job, 21, "下载中", processed_assets=3, processed_bytes=9_000, total_bytes=18_000)
        async with session_factory() as session:
            item = await session.get(MaterialExportModel, export_id)
            assert item.processed_assets == 5
            assert item.processed_bytes == 12_000
            assert item.total_bytes == 20_000

    asyncio.run(scenario())


def test_private_humans_sort_before_system(client) -> None:
    import asyncio
    from datetime import datetime, timedelta, timezone

    from app.database import session_factory
    from app.domain import uid
    from app.models import DigitalHumanModel

    user_id, headers = create_and_login_user(client, "dh-sort-owner")

    async def insert_private(human_id: str, created_at: datetime) -> None:
        async with session_factory() as db:
            db.add(
                DigitalHumanModel(
                    id=human_id,
                    user_id=user_id,
                    scope="private",
                    status="active",
                    name=human_id,
                    avatar_url="https://tos.test/avatar.png",
                    created_at=created_at,
                    updated_at=created_at,
                )
            )
            await db.commit()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    asyncio.run(insert_private(f"{uid('dh')}-old", now - timedelta(days=1)))
    asyncio.run(insert_private(f"{uid('dh')}-new", now))

    humans = client.get("/api/digital-humans", headers=headers).json()
    scopes = [item["scope"] for item in humans]
    # 私有角色整体排在系统人物之前
    assert scopes == sorted(scopes, key=lambda scope: 0 if scope == "private" else 1)
    # 同组内按创建时间倒序（新创建的排前面）
    private_ids = [item["id"] for item in humans if item["scope"] == "private"]
    assert private_ids.index(next(pid for pid in private_ids if pid.endswith("-new"))) < private_ids.index(next(pid for pid in private_ids if pid.endswith("-old")))
    assert any(item["id"] == "dh-system-001" for item in humans)


def test_storyboard_line_generation_per_user_concurrency_limit(client, monkeypatch) -> None:
    import asyncio
    from datetime import datetime, timezone

    from app import domain
    from app.database import session_factory
    from app.domain import uid
    from app.models import StoryboardLineModel

    async def fake_storyboard_line(**kwargs):
        return {
            "scenePrompt": "batched scene",
            "shotPrompt": "batched shot",
            "digitalHumanIds": [],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            "requestId": "req-limit",
        }

    monkeypatch.setattr(domain, "generate_storyboard_line", fake_storyboard_line)

    _, headers = create_and_login_user(client, "limit-owner")
    _, other = create_and_login_user(client, "limit-other")
    project = client.post("/api/projects", headers=headers, json={"name": "Limit"}).json()
    storyboard = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        headers=headers,
        json={
            "genre": "流行歌曲",
            "season": "春",
            "gender": "女",
            "age_group": "青年",
            "visual_style": "电影写实",
            "empty_shot_count": 1,
            "character_shot_count": 0,
            "total_duration": 5,
        },
    )
    assert storyboard.status_code == 201
    task_id = storyboard.json()["taskId"]
    line_id = storyboard.json()["lines"][0]["id"]

    other_project = client.post("/api/projects", headers=other, json={"name": "Other"}).json()
    other_task = client.post(f"/api/projects/{other_project['id']}/tasks", headers=other, json={"title": "o"}).json()

    async def insert_running(task: str, count: int) -> None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        async with session_factory() as db:
            for _ in range(count):
                db.add(
                    StoryboardLineModel(
                        id=uid("line"),
                        project_task_id=task,
                        generation_status="running",
                        created_at=now,
                        updated_at=now,
                    )
                )
            await db.commit()

    # 其他账号的 100 条 running 不占用本账号额度（按 user_id 隔离）
    asyncio.run(insert_running(other_task["id"], 100))
    ok = client.post(f"/api/tasks/{task_id}/storyboard-lines/{line_id}/generate", headers=headers, json={})
    assert ok.status_code == 200, ok.text

    # 本账号 running 达到 100：拒绝受理并返回 429
    asyncio.run(insert_running(task_id, 100))
    blocked = client.post(f"/api/tasks/{task_id}/storyboard-lines/{line_id}/generate", headers=headers, json={})
    assert blocked.status_code == 429
    assert "上限" in blocked.json()["detail"]
