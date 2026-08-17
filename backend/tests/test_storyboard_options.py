"""通用分镜选项（需求 7）：公开 options 端点种子数据 + 管理后台 CRUD/级联/权限。"""


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_general_storyboard_options_seeded(client):
    response = client.get("/api/storyboards/general/options")
    assert response.status_code == 200
    data = response.json()
    # 种子曲风三级树（与前端 src/songCategories.ts 口径一致）
    first = next(g for g in data["genres"] if g["value"] == "流行歌曲")
    assert first["label"] == "流行歌曲"
    second = next(c for c in first["children"] if c["value"] == "爱情消极")
    assert [leaf["value"] for leaf in second["children"]] == ["失恋", "爱而不得", "背叛", "土味情歌"]
    # 戏曲无下级分类 → 不挂 children 键（前端据此允许二级留空）
    opera = next(g for g in data["genres"] if g["value"] == "戏曲")
    assert "children" not in opera
    assert data["seasons"] == ["春", "夏", "秋", "冬", "通用"]
    assert data["ageGroups"] == ["少儿", "青少年", "青年", "中年", "老年"]
    assert data["visualStyles"] == ["电影写实", "动漫", "国风", "复古", "赛博朋克"]
    assert data["ratios"] == ["16:9", "9:16", "4:3", "1:1"]


def test_storyboard_option_admin_crud_and_genre_cascade(client):
    # 平铺 kind：新增（排序自动取同级 max+1）→ 重名 409 → 重命名+排序 → 删除
    created = client.post("/api/admin/storyboard-options", json={"kind": "season", "name": "梅雨季"})
    assert created.status_code == 201
    season = created.json()
    assert season["sortOrder"] == 5
    assert client.post("/api/admin/storyboard-options", json={"kind": "season", "name": "梅雨季"}).status_code == 409
    updated = client.patch(f"/api/admin/storyboard-options/{season['id']}", json={"name": "梅雨", "sort_order": 0})
    assert updated.status_code == 200
    assert updated.json()["name"] == "梅雨" and updated.json()["sortOrder"] == 0
    assert "梅雨" in client.get("/api/storyboards/general/options").json()["seasons"]
    assert client.delete(f"/api/admin/storyboard-options/{season['id']}").status_code == 200
    assert "梅雨" not in client.get("/api/storyboards/general/options").json()["seasons"]

    # genre 树：三级可建，第四级 422；非 genre 带 parent 422；删除一级级联子孙
    root = client.post("/api/admin/storyboard-options", json={"kind": "genre", "name": "测试曲风"}).json()
    branch = client.post("/api/admin/storyboard-options", json={"kind": "genre", "parent_id": root["id"], "name": "测试二级"}).json()
    leaf = client.post("/api/admin/storyboard-options", json={"kind": "genre", "parent_id": branch["id"], "name": "测试三级"})
    assert leaf.status_code == 201
    too_deep = client.post("/api/admin/storyboard-options", json={"kind": "genre", "parent_id": leaf.json()["id"], "name": "测试四级"})
    assert too_deep.status_code == 422
    bad_kind = client.post("/api/admin/storyboard-options", json={"kind": "season", "parent_id": root["id"], "name": "非法"})
    assert bad_kind.status_code == 422
    assert client.get("/api/admin/storyboard-options", params={"kind": "unknown"}).status_code == 422
    deleted = client.delete(f"/api/admin/storyboard-options/{root['id']}").json()
    assert deleted["cascadeCount"] == 2
    genres = client.get("/api/storyboards/general/options").json()["genres"]
    assert all(g["value"] != "测试曲风" for g in genres)
    # 审计留痕
    actions = {x["action"] for x in client.get("/api/admin/audit-logs").json()["items"]}
    assert "storyboard_option.create" in actions and "storyboard_option.delete" in actions


def test_storyboard_options_admin_endpoints_require_admin(client):
    created = client.post("/api/admin/users", json={"username": "option-admin-user", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "option-admin-user", "password": "secure-pass-123"}).json()
    headers = bearer(login["accessToken"])
    assert client.get("/api/admin/storyboard-options", params={"kind": "season"}, headers=headers).status_code == 403
    assert client.post("/api/admin/storyboard-options", json={"kind": "season", "name": "越权"}, headers=headers).status_code == 403
    # 普通用户仍可读公开 options 端点
    assert client.get("/api/storyboards/general/options", headers=headers).status_code == 200
    client.delete(f"/api/admin/users/{created['id']}")
    # 恢复共享 TestClient 的管理员会话，避免影响后续测试
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"
