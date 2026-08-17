"""Kling V3 Omni 测试页：任务 payload 组装纯函数 + 管理端点（鉴权/key 门禁/代理转发）。"""

import dataclasses

import pytest

from app import admin as admin_module
from app.config import settings
from app.kling import KlingError, build_task_payload


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_kling_payload_text_only():
    payload = build_task_payload(prompt="一只白色机械狐狸在雪山上奔跑", duration=5)
    assert payload["model_name"] == settings.kling_model
    assert payload["prompt"] == "一只白色机械狐狸在雪山上奔跑"
    assert payload["mode"] == "pro" and payload["aspect_ratio"] == "16:9"
    assert payload["sound"] == "off" and payload["cfg_scale"] == 0.5
    # 未提供的可选输入不出现在请求体
    assert "image_list" not in payload and "video_list" not in payload and "negative_prompt" not in payload


def test_kling_payload_first_end_frames_and_elements():
    payload = build_task_payload(
        prompt="<<>> 自然转为奔跑",
        negative_prompt="模糊, 变形",
        images=[
            {"imageUrl": "https://x.test/first.png", "type": "first_frame"},
            {"imageUrl": "https://x.test/end.png", "type": "end_frame"},
            {"imageUrl": "  ", "type": "reference"},  # 空 URL 被过滤
        ],
        element_ids=["123456789"],
        duration=8,
        mode="4k",
        aspect_ratio="9:16",
        sound="on",
        cfg_scale=0.8,
    )
    assert payload["image_list"] == [
        {"image_url": "https://x.test/first.png", "type": "first_frame"},
        {"image_url": "https://x.test/end.png", "type": "end_frame"},
    ]
    assert payload["element_list"] == [{"element_id": "123456789"}]
    assert payload["negative_prompt"] == "模糊, 变形"
    assert payload["duration"] == 8 and payload["mode"] == "4k"
    assert payload["aspect_ratio"] == "9:16" and payload["sound"] == "on" and payload["cfg_scale"] == 0.8


def test_kling_payload_reference_video_requires_sound_off():
    with pytest.raises(KlingError, match="sound 必须设置为 off"):
        build_task_payload(
            prompt="参考动作",
            videos=[{"videoUrl": "https://x.test/motion.mp4", "referType": "feature", "keepOriginalSound": "yes"}],
            sound="on",
        )
    payload = build_task_payload(
        prompt="参考动作",
        videos=[{"videoUrl": "https://x.test/motion.mp4", "referType": "feature", "keepOriginalSound": "yes"}],
        sound="off",
    )
    assert payload["video_list"] == [{"video_url": "https://x.test/motion.mp4", "refer_type": "feature", "keep_original_sound": "yes"}]


def test_kling_payload_validation():
    with pytest.raises(KlingError, match="至少提供一项"):
        build_task_payload(prompt="  ")
    with pytest.raises(KlingError, match="生成时长"):
        build_task_payload(prompt="x", duration=99)
    with pytest.raises(KlingError, match="生成模式"):
        build_task_payload(prompt="x", mode="ultra")
    with pytest.raises(KlingError, match="画面比例"):
        build_task_payload(prompt="x", aspect_ratio="4:3")
    with pytest.raises(KlingError, match="on/off"):
        build_task_payload(prompt="x", sound="yes")
    with pytest.raises(KlingError, match="cfg_scale"):
        build_task_payload(prompt="x", cfg_scale=1.5)
    with pytest.raises(KlingError, match="图片用途"):
        build_task_payload(images=[{"imageUrl": "https://x.test/a.png", "type": "middle_frame"}])


def test_kling_endpoints_require_api_key(client, monkeypatch):
    # 未配置 key（强制覆盖，避免共享 AIGC_TOKEN 影响）→ status 显示未配置，其余端点 503
    monkeypatch.setattr(admin_module, "settings", dataclasses.replace(settings, kling_api_key=""))
    status = client.get("/api/admin/kling/status").json()
    assert status["configured"] is False
    assert status["model"] == settings.kling_model
    assert status["modes"] == ["std", "pro", "4k"]
    assert status["imageTypes"] == ["first_frame", "end_frame", "reference"]
    assert client.post("/api/admin/kling/tasks", json={"prompt": "x"}).status_code == 503
    assert client.get("/api/admin/kling/tasks/t1").status_code == 503


def test_kling_task_submit_and_query(client, monkeypatch):
    monkeypatch.setattr(admin_module, "settings", dataclasses.replace(settings, kling_api_key="sk-kling-test-9abc"))
    submitted: dict = {}
    queries: list[str] = []

    async def fake_create(**kwargs):
        submitted.update(kwargs)
        return {"taskId": "893605946402811985", "status": "submitted"}

    async def fake_query(task_id: str):
        queries.append(task_id)
        return {
            "task_id": task_id,
            "task_status": "succeed",
            "task_result": {"videos": [{"id": "1", "url": "https://cdn.test/out.mp4", "duration": "5"}]},
        }

    monkeypatch.setattr(admin_module, "kling_create_task", fake_create)
    monkeypatch.setattr(admin_module, "kling_query_task", fake_query)

    status = client.get("/api/admin/kling/status").json()
    assert status["configured"] is True and status["keyTail"] == "...9abc"

    created = client.post(
        "/api/admin/kling/tasks",
        json={
            "prompt": "镜头缓慢拉远",
            "images": [{"imageUrl": "https://x.test/first.png", "type": "first_frame"}],
            "duration": 5,
            "mode": "std",
            "aspectRatio": "1:1",
            "sound": "off",
            "cfgScale": 0.3,
        },
    )
    assert created.status_code == 201
    assert created.json() == {"taskId": "893605946402811985", "status": "submitted"}
    assert submitted["prompt"] == "镜头缓慢拉远"
    assert submitted["images"] == [{"imageUrl": "https://x.test/first.png", "type": "first_frame"}]
    assert submitted["mode"] == "std" and submitted["aspect_ratio"] == "1:1" and submitted["cfg_scale"] == 0.3

    result = client.get("/api/admin/kling/tasks/893605946402811985").json()
    assert result["task_status"] == "succeed"
    assert result["task_result"]["videos"][0]["url"] == "https://cdn.test/out.mp4"
    assert queries == ["893605946402811985"]

    actions = {x["action"] for x in client.get("/api/admin/audit-logs").json()["items"]}
    assert "kling_task.submit" in actions


def test_kling_upstream_error_mapped_to_502(client, monkeypatch):
    monkeypatch.setattr(admin_module, "settings", dataclasses.replace(settings, kling_api_key="sk-x"))

    async def fake_query(task_id: str):
        raise KlingError("Kling 返回错误：余额不足")

    monkeypatch.setattr(admin_module, "kling_query_task", fake_query)
    response = client.get("/api/admin/kling/tasks/t-err")
    assert response.status_code == 502
    assert "余额不足" in response.json()["detail"]


def test_kling_endpoints_require_admin(client):
    created = client.post("/api/admin/users", json={"username": "kling-normal-user", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "kling-normal-user", "password": "secure-pass-123"}).json()
    headers = bearer(login["accessToken"])
    assert client.get("/api/admin/kling/status", headers=headers).status_code == 403
    assert client.post("/api/admin/kling/tasks", json={"prompt": "x"}, headers=headers).status_code == 403
    assert client.get("/api/admin/kling/tasks/t", headers=headers).status_code == 403
    client.delete(f"/api/admin/users/{created['id']}")
    # 恢复共享 TestClient 的管理员会话，避免影响后续测试
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"
