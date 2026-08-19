"""RunningHub 工作流测试页：nodeInfoList 组装纯函数 + 管理端点（鉴权/key 门禁/代理转发）。"""

import asyncio
import dataclasses
import uuid

import pytest
from sqlalchemy import select

from app import admin as admin_module
from app.config import settings
from app.database import session_factory
from app.models import ProjectModel, ProjectTaskModel, ShotAssetModel, StoryboardLineModel, UserModel
from app.runninghub import (
    RunningHubError,
    build_first_frame_node_info_list,
    build_first_last_frame_node_info_list,
    build_node_info_list,
    build_reference_workflow,
    build_text_node_info_list,
)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_runninghub_node_info_list_full():
    nodes = build_node_info_list(
        prompt="subject_definitions:\n<Subject 1> ...",
        duration=10,
        aspect_ratio="16:9 (Widescreen)",
        images=["openapi/a.png", "openapi/b.png", "openapi/c.png"],
        seed=100,
        stage1_megapixels=0.6,
        stage2_megapixels=1.5,
    )
    by_node = {}
    for item in nodes:
        by_node.setdefault(item["nodeId"], {})[item["fieldName"]] = item["fieldValue"]
    assert by_node["83"]["text"].startswith("subject_definitions:")
    assert by_node["84"]["value"] == 10
    assert by_node["105"]["aspect_ratio"] == "16:9 (Widescreen)"
    assert by_node["297"]["aspect_ratio"] == "16:9 (Widescreen)"
    # 一/二阶段分辨率独立可调
    assert by_node["105"]["megapixels"] == 0.6
    assert by_node["297"]["megapixels"] == 1.5
    assert by_node["97"]["image"] == "openapi/a.png"
    assert by_node["101"]["image"] == "openapi/b.png"
    assert by_node["132"]["image"] == "openapi/c.png"
    # 一采/二采种子错开，避免两阶段噪声完全一致
    assert by_node["243"]["noise_seed"] == 100
    assert by_node["300"]["noise_seed"] == 101


def test_runninghub_node_info_list_single_image_pads_slots():
    nodes = build_node_info_list(prompt="测试", duration=6, aspect_ratio="9:16 (Portrait)", images=["https://x.test/p.png"])
    images = {item["nodeId"]: item["fieldValue"] for item in nodes if item["fieldName"] == "image"}
    # 单图补齐三个槽位，避免工作流默认示例图污染主体
    assert images == {"97": "https://x.test/p.png", "101": "https://x.test/p.png", "132": "https://x.test/p.png"}
    # 未传种子 → 不覆盖工作流默认种子
    assert all(item["fieldName"] != "noise_seed" for item in nodes)
    # 未传分辨率 → 沿用工作流默认（一采 0.4 / 二采 0.9）
    megapixels = {item["nodeId"]: item["fieldValue"] for item in nodes if item["fieldName"] == "megapixels"}
    assert megapixels == {"105": 0.4, "297": 0.9}


def test_runninghub_node_info_list_validation():
    with pytest.raises(RunningHubError, match="提示词不能为空"):
        build_node_info_list(prompt="  ", duration=8, aspect_ratio="16:9 (Widescreen)", images=["a.png"])
    with pytest.raises(RunningHubError, match="视频时长"):
        build_node_info_list(prompt="x", duration=99, aspect_ratio="16:9 (Widescreen)", images=["a.png"])
    with pytest.raises(RunningHubError, match="宽高比"):
        build_node_info_list(prompt="x", duration=8, aspect_ratio="16:9", images=["a.png"])
    with pytest.raises(RunningHubError, match="至少需要 1 张参考图"):
        build_node_info_list(prompt="x", duration=8, aspect_ratio="16:9 (Widescreen)", images=["", "  "])
    with pytest.raises(RunningHubError, match="一阶段分辨率"):
        build_node_info_list(prompt="x", duration=8, aspect_ratio="16:9 (Widescreen)", images=["a.png"], stage1_megapixels=3.0)
    with pytest.raises(RunningHubError, match="二阶段分辨率"):
        build_node_info_list(prompt="x", duration=8, aspect_ratio="16:9 (Widescreen)", images=["a.png"], stage2_megapixels=0.1)


def test_reference_workflow_uses_product_limits_and_removes_empty_defaults():
    workflow = build_reference_workflow(
        prompt="subject_definitions:\n<Subject 1> ...",
        duration=10,
        aspect_ratio="16:9 (Widescreen)",
        images=[f"openapi/image-{index}.png" for index in range(6)],
        videos=["openapi/video.mp4"],
        audios=[],
        seed=10,
    )
    inputs = workflow["108"]["inputs"]
    assert all(f"ref_images.ref_image_{index}" in inputs for index in range(6))
    assert "ref_images.ref_image_6" not in inputs
    assert "ref_videos.ref_video_0" in inputs
    assert "ref_videos.ref_video_1" not in inputs
    assert all(f"ref_audios.ref_audio_{index}" not in inputs for index in range(3))
    assert all(node not in workflow for node in ("100", "103", "130", "169", "173", "177"))
    assert workflow["243"]["inputs"]["noise_seed"] == 10
    assert workflow["300"]["inputs"]["noise_seed"] == 11


def test_reference_workflow_enforces_cross_media_rules():
    common = {"prompt": "x", "duration": 8, "aspect_ratio": "16:9 (Widescreen)"}
    with pytest.raises(RunningHubError, match="音频不能作为唯一输入"):
        build_reference_workflow(**common, images=[], audios=["a.wav"])
    with pytest.raises(RunningHubError, match="最多支持 6 张"):
        build_reference_workflow(
            **common,
            images=[f"{index}.png" for index in range(7)],
        )
    with pytest.raises(RunningHubError, match="最多支持 1 段"):
        build_reference_workflow(**common, images=["1.png"], videos=["1.mp4", "2.mp4"])


def test_runninghub_text_node_info_list():
    nodes = build_text_node_info_list(
        prompt="A fox in a misty forest",
        duration=6,
        aspect_ratio="9:16 (Portrait Widescreen)",
        seed=77,
        megapixels=0.9,
    )
    by_node = {}
    for item in nodes:
        by_node.setdefault(item["nodeId"], {})[item["fieldName"]] = item["fieldValue"]
    assert by_node == {
        "25": {"text": "A fox in a misty forest"},
        "27": {"value": 6},
        "23": {"aspect_ratio": "9:16 (Portrait Widescreen)", "megapixels": 0.9},
        "228": {"noise_seed": 77},
    }


def test_runninghub_first_frame_node_info_list():
    nodes = build_first_frame_node_info_list(
        prompt="Start exactly from Picture 1",
        duration=8,
        aspect_ratio="3:4 (Portrait Standard)",
        image="openapi/first.png",
        seed=88,
        megapixels=0.9,
    )
    by_node = {}
    for item in nodes:
        by_node.setdefault(item["nodeId"], {})[item["fieldName"]] = item["fieldValue"]
    assert by_node == {
        "55": {"text": "Start exactly from Picture 1"},
        "58": {"value": 8},
        "59": {"aspect_ratio": "3:4 (Portrait Standard)", "megapixels": 0.9},
        "61": {"image": "openapi/first.png"},
        "235": {"noise_seed": 88},
    }


def test_runninghub_first_last_frame_node_info_list():
    nodes = build_first_last_frame_node_info_list(
        prompt="transition from Picture 1 to Picture 2",
        duration=8,
        aspect_ratio="16:9 (Widescreen)",
        first_image="openapi/first.png",
        last_image="openapi/last.png",
        seed=99,
        megapixels=0.9,
    )
    by_node = {}
    for item in nodes:
        by_node.setdefault(item["nodeId"], {})[item["fieldName"]] = item["fieldValue"]
    assert by_node["332"]["prompt"].startswith("transition")
    assert by_node["347"]["text"].startswith("transition")
    assert by_node["346"]["value"] == 8
    assert by_node["349"] == {"aspect_ratio": "16:9 (Widescreen)", "megapixels": 0.9}
    assert by_node["61"]["image"] == "openapi/first.png"
    assert by_node["73"]["image"] == "openapi/last.png"
    assert by_node["338"]["noise_seed"] == 99


def test_runninghub_endpoints_require_api_key(client, monkeypatch):
    # 未配置 RUNNINGHUB_API_KEY（强制覆盖，避免本地 .env 影响）→ status 显示未配置，其余端点 503
    monkeypatch.setattr(admin_module, "settings", dataclasses.replace(settings, runninghub_api_key=""))
    status = client.get("/api/admin/runninghub/status").json()
    assert status["configured"] is False
    assert status["workflowId"] == settings.runninghub_workflow_id
    assert "16:9 (Widescreen)" in status["aspectRatios"]
    assert status["megapixelsDefault"] == [0.4, 0.9]
    assert {"value": 0.9, "size": "1280×736"} in status["megapixelsPresets"]
    payload = {"prompt": "测试", "images": ["a.png"]}
    assert client.post("/api/admin/runninghub/tasks", json=payload).status_code == 503
    assert client.post("/api/admin/runninghub/query", json={"taskId": "t1"}).status_code == 503
    assert client.post("/api/admin/runninghub/upload", files={"file": ("a.png", b"png-bytes")}).status_code == 503


def test_runninghub_task_submit_and_query(client, monkeypatch):
    configured = dataclasses.replace(settings, runninghub_api_key="rh-test-key-1234")
    monkeypatch.setattr(admin_module, "settings", configured)
    submitted: dict = {}
    queries: list[str] = []
    uploads: list[bytes] = []

    async def fake_submit(**kwargs):
        submitted.update(kwargs)
        return {"taskId": "2013508786110730241", "status": "RUNNING"}

    async def fake_query(task_id: str):
        queries.append(task_id)
        return {"taskId": task_id, "status": "SUCCESS", "results": [{"url": "https://cos.test/out.mp4", "outputType": "mp4"}]}

    async def fake_upload(content: bytes, filename: str):
        uploads.append(content)
        return {"fileName": f"openapi/{filename}", "downloadUrl": "https://cos.test/in.png", "size": str(len(content))}

    async def fake_import(url: str, category: str, filename: str | None = None):
        return f"https://tos.test/{filename}"

    class FakeStorage:
        async def put_bytes(self, key: str, content: bytes, content_type: str | None = None):
            return f"https://tos.test/{key}"

    monkeypatch.setattr(admin_module, "rh_submit_reference_task", fake_submit)
    monkeypatch.setattr(admin_module, "rh_query_task", fake_query)
    monkeypatch.setattr(admin_module, "rh_upload_media", fake_upload)
    monkeypatch.setattr(admin_module, "import_remote", fake_import)
    monkeypatch.setattr(admin_module, "get_storage", lambda: FakeStorage())

    status = client.get("/api/admin/runninghub/status").json()
    assert status["configured"] is True and status["keyTail"] == "...1234"

    created = client.post(
        "/api/admin/runninghub/tasks",
        json={"prompt": "医生场景", "duration": 12, "aspectRatio": "16:9 (Widescreen)", "images": ["openapi/a.png"], "seed": 42},
    )
    assert created.status_code == 201
    assert created.json() == {"taskId": "2013508786110730241", "status": "RUNNING"}
    assert submitted == {
        "prompt": "医生场景",
        "duration": 12,
        "aspect_ratio": "16:9 (Widescreen)",
        "images": ["openapi/a.png"],
        "videos": [],
        "audios": [],
        "seed": 42,
        # 请求未传 → pydantic 默认值
        "stage1_megapixels": 0.4,
        "stage2_megapixels": 0.9,
    }

    result = client.post("/api/admin/runninghub/query", json={"taskId": "2013508786110730241"}).json()
    assert result["status"] == "SUCCESS"
    assert result["results"][0]["url"] == "https://tos.test/2013508786110730241-0.mp4"
    assert queries == ["2013508786110730241"]

    uploaded = client.post("/api/admin/runninghub/upload", files={"file": ("ref.png", b"fake-png")})
    assert uploaded.status_code == 200
    assert uploaded.json()["fileName"] == "openapi/ref.png"
    assert uploaded.json()["tosUrl"].startswith("https://tos.test/")
    assert uploads == [b"fake-png"]

    actions = {x["action"] for x in client.get("/api/admin/audit-logs").json()["items"]}
    assert "runninghub_task.submit" in actions


def test_runninghub_upstream_error_mapped_to_502(client, monkeypatch):
    configured = dataclasses.replace(settings, runninghub_api_key="rh-test-key")
    monkeypatch.setattr(admin_module, "settings", configured)

    async def fake_query(task_id: str):
        raise RunningHubError("RunningHub 返回 HTTP 429：too many requests")

    monkeypatch.setattr(admin_module, "rh_query_task", fake_query)
    response = client.post("/api/admin/runninghub/query", json={"taskId": "t-err"})
    assert response.status_code == 502
    assert "429" in response.json()["detail"]


def test_runninghub_admin_submits_first_last_mode(client, monkeypatch):
    configured = dataclasses.replace(settings, runninghub_api_key="rh-test-key")
    monkeypatch.setattr(admin_module, "settings", configured)
    submitted = {}

    async def fake_submit(**kwargs):
        submitted.update(kwargs)
        return {"taskId": "rh-fl2va-test", "status": "RUNNING"}

    monkeypatch.setattr(admin_module, "rh_submit_first_last_frame_task", fake_submit)
    response = client.post(
        "/api/admin/runninghub/tasks",
        json={
            "mode": "first_last",
            "prompt": "Picture 1 continuously transitions to Picture 2",
            "duration": 8,
            "aspectRatio": "16:9 (Widescreen)",
            "images": ["openapi/first.png", "openapi/last.png"],
            "seed": 7,
        },
    )
    assert response.status_code == 201
    assert submitted == {
        "prompt": "Picture 1 continuously transitions to Picture 2",
        "duration": 8,
        "aspect_ratio": "16:9 (Widescreen)",
        "first_image": "openapi/first.png",
        "last_image": "openapi/last.png",
        "seed": 7,
        "megapixels": 0.9,
    }


def test_runninghub_seedance_comparison_source_and_submit(client, monkeypatch):
    configured = dataclasses.replace(settings, runninghub_api_key="rh-test-key")
    monkeypatch.setattr(admin_module, "settings", configured)
    suffix = uuid.uuid4().hex
    line_id = f"line-{suffix}"

    async def seed_source():
        async with session_factory() as db:
            owner = (await db.execute(select(UserModel).where(UserModel.username == "admin"))).scalar_one()
            project = ProjectModel(id=f"project-{suffix}", user_id=owner.id, name="H3 对比项目")
            task = ProjectTaskModel(
                id=f"task-{suffix}",
                project_id=project.id,
                title="通用分镜测试",
                storyboard_type="general",
                status="ready",
            )
            line = StoryboardLineModel(
                id=line_id,
                project_task_id=task.id,
                source="general",
                shot_type="empty",
                sort_order=1,
                scene_prompt="清晨草原",
                shot_prompt="无人空镜，镜头缓慢推进",
                shot_options={"videoModel": "doubao-seedance-2.0", "ratio": "16:9"},
            )
            asset = ShotAssetModel(
                id=f"shot-{suffix}",
                storyboard_line_id=line.id,
                cover_url="https://tos.test/comparison-cover.jpg",
                video_url="https://tos.test/seedance.mp4",
                duration=8,
                ratio="16:9",
                is_current=True,
            )
            db.add_all([project, task, line, asset])
            await db.commit()

    asyncio.run(seed_source())
    submitted = {}

    async def fake_submit(**kwargs):
        submitted.update(kwargs)
        return {"taskId": "h3-comparison-task", "status": "RUNNING"}

    monkeypatch.setattr(admin_module, "rh_submit_first_frame_task", fake_submit)

    listed = client.get("/api/admin/runninghub/comparison-sources")
    assert listed.status_code == 200
    source = next(item for item in listed.json()["items"] if item["lineId"] == line_id)
    assert source["shotType"] == "empty"
    assert source["seedanceUrl"] == "https://tos.test/seedance.mp4"

    created = client.post("/api/admin/runninghub/comparisons", json={"lineId": line_id})
    assert created.status_code == 201
    payload = created.json()
    assert payload["taskId"] == "h3-comparison-task"
    assert payload["inputMedia"][1]["role"] == "seedance_source"
    assert submitted == {
        "prompt": "清晨草原\n\n无人空镜，镜头缓慢推进",
        "duration": 8.0,
        "aspect_ratio": "16:9 (Widescreen)",
        "image": "https://tos.test/comparison-cover.jpg",
        "seed": None,
        "megapixels": 0.9,
    }


def test_runninghub_endpoints_require_admin(client):
    created = client.post("/api/admin/users", json={"username": "rh-normal-user", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "rh-normal-user", "password": "secure-pass-123"}).json()
    headers = bearer(login["accessToken"])
    assert client.get("/api/admin/runninghub/status", headers=headers).status_code == 403
    assert client.post("/api/admin/runninghub/tasks", json={"prompt": "x", "images": ["a.png"]}, headers=headers).status_code == 403
    assert client.post("/api/admin/runninghub/query", json={"taskId": "t"}, headers=headers).status_code == 403
    assert client.post("/api/admin/runninghub/upload", files={"file": ("a.png", b"x")}, headers=headers).status_code == 403
    client.delete(f"/api/admin/users/{created['id']}")
    # 恢复共享 TestClient 的管理员会话，避免影响后续测试
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "123456"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"
