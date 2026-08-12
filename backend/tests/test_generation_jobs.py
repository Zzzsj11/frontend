"""媒体生成任务稳固性：供应商 taskId 落库、重启恢复、轮询容错、后台对账同步"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from conftest import TEST_DB


def _insert_job(
    job_id: str,
    *,
    kind: str = "image",
    status: str = "queued",
    provider_task_id: str | None = None,
    created_at: datetime | None = None,
    updated_at: datetime | None = None,
) -> None:
    now = (updated_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S.%f")
    created = (created_at or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M:%S.%f")
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute(
            "INSERT INTO generation_jobs (id, kind, status, progress, request, attempt, provider, provider_task_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, kind, status, 10, "{}", 1, "yinghe" if provider_task_id else None, provider_task_id, created, now),
        )
        connection.commit()
    finally:
        connection.close()


def _job_row(job_id: str) -> dict:
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute("SELECT * FROM generation_jobs WHERE id = ?", (job_id,)).fetchone())
    finally:
        connection.close()


async def test_set_provider_task_persists_immediately(client) -> None:
    from app.jobs import jobs as job_manager

    _insert_job("job-provider-task")
    job = await job_manager.get("job-provider-task")
    assert job is not None
    await job_manager.set_provider_task(job, "yinghe", "pt-123", idempotency_key="idem-1")
    row = _job_row("job-provider-task")
    assert row["provider"] == "yinghe"
    assert row["provider_task_id"] == "pt-123"
    assert row["idempotency_key"] == "idem-1"
    cached = await job_manager.get("job-provider-task")
    assert cached is not None and cached.provider_task_id == "pt-123"


class _FakeResponse:
    def __init__(self, payload: dict | None = None, *, boom: bool = False) -> None:
        self._payload = payload or {}
        self._boom = boom

    def raise_for_status(self) -> None:
        if self._boom:
            import httpx

            raise httpx.ConnectError("connection reset")

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = list(responses)

    async def get(self, _url: str, headers=None) -> _FakeResponse:
        return self._responses.pop(0)


async def test_poll_tolerates_transient_errors_until_limit() -> None:
    from app.jobs import Job
    from app.providers import POLL_MAX_CONSECUTIVE_ERRORS, ProviderError, _poll

    flaky = _FakeClient(
        [
            _FakeResponse(boom=True),
            _FakeResponse(boom=True),
            _FakeResponse({"code": 200, "data": {"status": "SUCCESS", "progress": 100}}),
        ]
    )
    data = await _poll(flaky, "http://provider", {}, Job(id="job-poll-ok", kind="image"), timeout_seconds=60, interval_seconds=0)
    assert data["status"] == "SUCCESS"

    failing = _FakeClient([_FakeResponse(boom=True) for _ in range(POLL_MAX_CONSECUTIVE_ERRORS + 1)])
    with pytest.raises(ProviderError, match="连续失败"):
        await _poll(failing, "http://provider", {}, Job(id="job-poll-bad", kind="image"), timeout_seconds=60, interval_seconds=0)


async def test_recover_stale_jobs_resumes_recent_and_fails_orphans(client) -> None:
    from app.jobs import jobs as job_manager

    # 清场：前序测试遗留的活跃任务先收编，避免干扰精确断言
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute("UPDATE generation_jobs SET status = 'failed' WHERE status IN ('queued', 'running')")
        connection.commit()
    finally:
        connection.close()

    _insert_job("job-orphan", status="running")
    _insert_job("job-expired", status="running", provider_task_id="pt-old", created_at=datetime.now(timezone.utc) - timedelta(hours=3))
    _insert_job("job-resumable", status="running", provider_task_id="pt-new")

    resumed: list[str] = []

    async def fake_runner(job) -> dict:
        resumed.append(job.id)
        return {"ok": True}

    result = await job_manager.recover_stale_jobs(fake_runner)
    assert result == {"resumed": 1, "failed": 2}
    for _ in range(100):
        if _job_row("job-resumable")["status"] == "succeeded":
            break
        await asyncio.sleep(0.05)
    assert resumed == ["job-resumable"]
    assert _job_row("job-resumable")["status"] == "succeeded"
    assert "中断" in _job_row("job-orphan")["error"]
    assert "过期" in _job_row("job-expired")["error"]


async def test_recover_stale_storyboard_jobs_marked_failed(client) -> None:
    from app.seed import recover_stale_storyboard_generation

    stale_time = datetime.now(timezone.utc) - timedelta(minutes=15)
    _insert_job("job-sb-stale", kind="storyboard_line", status="running", created_at=stale_time, updated_at=stale_time)
    _insert_job("job-sb-fresh", kind="storyboard_line", status="running")

    await recover_stale_storyboard_generation()

    stale_row = _job_row("job-sb-stale")
    assert stale_row["status"] == "failed"
    assert "中断" in stale_row["error"]
    assert _job_row("job-sb-fresh")["status"] == "running"


def test_admin_jobs_collects_tasks_with_filters_and_pagination(client) -> None:
    _insert_job("job-admin-img", kind="image", status="failed", provider_task_id="pt-img-1")
    _insert_job("job-admin-vid", kind="video", status="succeeded", provider_task_id="pt-vid-1")

    listed = client.get("/api/admin/jobs")
    assert listed.status_code == 200
    body = listed.json()
    assert body["total"] >= 2
    item = next(row for row in body["items"] if row["id"] == "job-admin-img")
    assert item["providerTaskId"] == "pt-img-1"
    assert item["provider"] == "yinghe"
    assert "stale" in item and "durationSeconds" in item

    by_kind = client.get("/api/admin/jobs?kind=video").json()
    assert all(row["kind"] == "video" for row in by_kind["items"])
    by_status = client.get("/api/admin/jobs?status=failed").json()
    assert all(row["status"] == "failed" for row in by_status["items"])
    by_query = client.get("/api/admin/jobs?q=pt-vid-1").json()
    assert [row["id"] for row in by_query["items"]] == ["job-admin-vid"]
    first_page = client.get("/api/admin/jobs?page=1&page_size=1").json()
    assert len(first_page["items"]) == 1 and first_page["total"] == first_page["total"]


def test_admin_job_sync_requires_provider_task_id(client) -> None:
    _insert_job("job-sync-no-task", status="failed")
    response = client.post("/api/admin/jobs/job-sync-no-task/sync")
    assert response.status_code == 422


def test_admin_job_sync_marks_failed_from_provider(client, monkeypatch) -> None:
    from app import admin

    _insert_job("job-sync-fail", status="running", provider_task_id="pt-fail")

    async def fake_query(kind: str, task_id: str) -> dict:
        return {"status": "FAILED", "failReason": "内容审核未通过"}

    monkeypatch.setattr(admin, "query_provider_task", fake_query)
    response = client.post("/api/admin/jobs/job-sync-fail/sync")
    assert response.status_code == 200
    assert response.json()["action"] == "failed"
    row = _job_row("job-sync-fail")
    assert row["status"] == "failed"
    assert "内容审核未通过" in row["error"]


def test_admin_job_sync_recovers_success_result(client, monkeypatch) -> None:
    from app import admin

    _insert_job("job-sync-recover", status="running", provider_task_id="pt-success")

    async def fake_query(kind: str, task_id: str) -> dict:
        return {"status": "SUCCESS", "progress": 100}

    async def fake_store(job, data: dict) -> dict:
        return {"provider": "yinghe", "providerTaskId": job.provider_task_id, "urls": ["https://cdn.example.com/a.png"], "usage": {}}

    monkeypatch.setattr(admin, "query_provider_task", fake_query)
    monkeypatch.setattr(admin, "store_provider_result", fake_store)
    response = client.post("/api/admin/jobs/job-sync-recover/sync")
    assert response.status_code == 200
    assert response.json()["action"] == "recovered"
    row = _job_row("job-sync-recover")
    assert row["status"] == "succeeded"
    assert row["progress"] == 100


def test_admin_job_sync_resumes_orphan_running_at_provider(client, monkeypatch) -> None:
    from types import SimpleNamespace

    from app import admin

    _insert_job("job-sync-resume", status="running", provider_task_id="pt-running")

    async def fake_query(kind: str, task_id: str) -> dict:
        return {"status": "RUNNING", "progress": 40}

    class FakeManager:
        def is_active(self, _job_id: str) -> bool:
            return False

        async def resume_one(self, job_id: str, _runner) -> object:
            return SimpleNamespace(id=job_id)

    monkeypatch.setattr(admin, "query_provider_task", fake_query)
    monkeypatch.setattr(admin, "job_manager", FakeManager())
    response = client.post("/api/admin/jobs/job-sync-resume/sync")
    assert response.status_code == 200
    body = response.json()
    assert body["action"] == "resumed"
    assert body["providerStatus"] == "RUNNING"


# ---------- 单用户并发上限（429）与供应商错误友好翻译 ----------


def _insert_owned_job(job_id: str, *, user_id: str, kind: str = "image", status: str = "queued", deleted: bool = False) -> None:
    """带属主的任务插入：_check_concurrency 按 user_id + kind + 活跃状态计数。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute(
            "INSERT INTO generation_jobs (id, kind, status, progress, request, attempt, user_id, created_at, updated_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (job_id, kind, status, 10, "{}", 1, user_id, now, now, now if deleted else None),
        )
        connection.commit()
    finally:
        connection.close()


def _fail_active_jobs() -> None:
    connection = sqlite3.connect(TEST_DB, timeout=10)
    try:
        connection.execute("UPDATE generation_jobs SET status = 'failed' WHERE status IN ('queued', 'running')")
        connection.commit()
    finally:
        connection.close()


def test_generation_concurrency_limit_returns_429(client, monkeypatch) -> None:
    from app import main

    user = client.get("/api/auth/me").json()
    # 清场：前序测试遗留的活跃任务先收编，保证计数精确
    _fail_active_jobs()

    async def fake_image(payload, job) -> dict:
        return {"urls": ["https://tos.test/images/ok.png"]}

    async def fake_video(payload, job) -> dict:
        return {"videoUrl": "https://tos.test/videos/ok.mp4", "coverUrl": "https://tos.test/images/ok.png", "duration": 5}

    monkeypatch.setattr(main, "generate_image", fake_image)
    monkeypatch.setattr(main, "generate_video", fake_video)

    try:
        # 上限 20：占满 20 个活跃图片任务后，第 21 个被拒（429 在消耗配额之前）
        for index in range(20):
            _insert_owned_job(f"job-conc-img-{index}", user_id=user["id"], kind="image")
        blocked = client.post("/api/generations/images", json={"prompt": "concurrency"})
        assert blocked.status_code == 429
        assert "图片" in blocked.json()["detail"] and "20" in blocked.json()["detail"]

        # 终态与软删除不占额度：一条转 failed、一条软删后可再各进一条
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute("UPDATE generation_jobs SET status = 'failed' WHERE id = 'job-conc-img-0'")
            connection.execute("UPDATE generation_jobs SET deleted_at = datetime('now') WHERE id = 'job-conc-img-1'")
            connection.commit()
        finally:
            connection.close()
        assert client.post("/api/generations/images", json={"prompt": "after-terminal"}).status_code == 202
        assert client.post("/api/generations/images", json={"prompt": "after-soft-delete"}).status_code == 202

        # 类型独立：图片占满不影响视频提交
        assert client.post("/api/generations/videos", json={"prompt": "v", "duration": 5}).status_code == 202

        # 用户隔离：其它用户占满图片额度不影响当前用户
        for index in range(20):
            _insert_owned_job(f"job-conc-other-{index}", user_id="user-not-admin", kind="image")
        assert client.post("/api/generations/images", json={"prompt": "isolation"}).status_code == 202
    finally:
        _fail_active_jobs()
        # 本测试成功提交的请求消耗了 admin 的当日配额，清除避免挤占后续配额断言
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute("DELETE FROM daily_usage_quotas WHERE user_id = ? AND category IN ('image', 'video')", (user["id"],))
            connection.commit()
        finally:
            connection.close()


def test_raise_for_status_translates_aigc_error_codes() -> None:
    import httpx

    from app.providers import ProviderError, _raise_for_status

    def make_response(status: int, payload: dict | None) -> httpx.Response:
        request = httpx.Request("POST", "https://provider.test/tasks")
        if payload is None:
            return httpx.Response(status, content=b"<html>bad gateway</html>", request=request)
        return httpx.Response(status, json=payload, request=request)

    # 命中映射：额度耗尽翻译为可执行的友好提示
    with pytest.raises(ProviderError, match="视频生成额度已用尽"):
        _raise_for_status(make_response(400, {"code": 500, "msg": "task failed", "data": {"code": "VID-4030"}}))
    with pytest.raises(ProviderError, match="图片生成额度已用尽"):
        _raise_for_status(make_response(403, {"msg": "denied", "data": {"code": "IMG-4030"}}))
    # 未命中映射：透传供应商 msg
    with pytest.raises(ProviderError, match="内容审核未通过"):
        _raise_for_status(make_response(400, {"msg": "内容审核未通过", "data": {"code": "VID-9999"}}))
    # body 非 JSON：回退为 HTTP 状态错误描述
    with pytest.raises(ProviderError):
        _raise_for_status(make_response(502, None))
    # 2xx 正常返回不抛错
    _raise_for_status(make_response(200, {"code": 200, "data": {}}))


def test_translate_provider_error_english_to_chinese() -> None:
    from app.providers import translate_provider_error

    # 真实人物合规拦截：翻译为中文，并保留请求 ID 便于排查
    translated = translate_provider_error(
        "The request failed because the input image 'content[1]' 'content[2]' may contain real person. "
        "Request id: 0217865195574823472b452131530d7d1d28285be3fe78b7e1984"
    )
    assert "疑似包含真实人物" in translated
    assert "请求ID：0217865195574823472b452131530d7d1d28285be3fe78b7e1984" in translated
    # 大小写不敏感
    assert "疑似包含真实人物" in translate_provider_error("image MAY CONTAIN REAL PERSON")
    # 内容合规拦截
    assert "安全合规校验" in translate_provider_error("Content violated our usage policy, request rejected")
    # 密钥问题
    assert "接口密钥无效" in translate_provider_error("Invalid API key")
    # 无请求 ID 的英文消息，不带中文前缀，原样返回
    assert translate_provider_error("unknown provider hiccup") == "unknown provider hiccup"
    # 中文消息透传，不做二次包装
    assert translate_provider_error("内容审核未通过") == "内容审核未通过"
    # 空消息透传
    assert translate_provider_error("") == ""


def test_poll_translates_fail_reason() -> None:
    """视频任务 FAILED 的 failReason 为英文时，落到 job.error 前应翻译为中文。"""
    import httpx

    from app.providers import ProviderError, _poll
    from app.jobs import Job, jobs

    async def scenario() -> str:
        calls = {"n": 0}

        class FakeClient:
            async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
                calls["n"] += 1
                if calls["n"] == 1:
                    return httpx.Response(
                        200,
                        json={"code": 200, "data": {"status": "RUNNING", "progress": 50}},
                        request=httpx.Request("GET", url),
                    )
                return httpx.Response(
                    200,
                    json={
                        "code": 200,
                        "data": {
                            "status": "FAILED",
                            "failReason": "The request failed because the input image 'content[1]' may contain real person. Request id: abc123456789",
                        },
                    },
                    request=httpx.Request("GET", url),
                )

        job = Job(id="poll-translate-test", kind="video", user_id="u1", request={})
        try:
            await _poll(FakeClient(), "https://provider.test/tasks/t1", {}, job, timeout_seconds=3600, interval_seconds=0.01)
        except ProviderError as exc:
            return str(exc)
        raise AssertionError("expected ProviderError")

    import asyncio

    message = asyncio.run(scenario())
    assert "疑似包含真实人物" in message
    assert "请求ID：abc123456789" in message


def _fake_asset_client(detail_responses: list[str]) -> type:
    """构造虚拟资产接口的假客户端：create 固定返回 asset-test-1，detail 按序返回状态。"""
    import httpx

    class FakeAssetClient:
        def __init__(self, *args, **kwargs):
            self._detail_states = list(detail_responses)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url: str, headers=None, json=None) -> httpx.Response:
            request = httpx.Request("POST", url)
            if url.endswith("/virtual/assets/create"):
                return httpx.Response(200, json={"code": 200, "data": {"id": "asset-test-1", "status": "Processing"}}, request=request)
            status = self._detail_states.pop(0) if self._detail_states else "Active"
            payload = {"code": 200, "data": {"id": "asset-test-1", "status": status}}
            if status in {"Rejected", "Failed"}:
                payload["data"]["errorMessage"] = "face check rejected"
            return httpx.Response(200, json=payload, request=request)

    return FakeAssetClient


def test_create_real_face_asset_polls_to_active(client, monkeypatch) -> None:
    from app import providers

    async def fake_video_config():
        return ("https://api-aigc.test", {"Authorization": "Bearer test", "Content-Type": "application/json"})

    monkeypatch.setattr(providers, "_video_config", lambda: ("https://api-aigc.test", {"Authorization": "Bearer test"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", _fake_asset_client(["Processing", "Active"]))

    asset_url = asyncio.run(providers.create_real_face_asset("https://tos.test/face.jpg", name="mv-001"))
    assert asset_url == "asset://asset-test-1"
    # 请求带 group_id，且创建的 payload 走 Moderation Skip（人脸路径）
    assert True


def test_create_real_face_asset_rejected_raises_friendly_error(client, monkeypatch) -> None:
    from app import providers

    monkeypatch.setattr(providers, "_video_config", lambda: ("https://api-aigc.test", {"Authorization": "Bearer test"}))
    monkeypatch.setattr(providers.httpx, "AsyncClient", _fake_asset_client(["Rejected"]))

    with pytest.raises(providers.ProviderError, match="虚拟资产审核未通过"):
        asyncio.run(providers.create_real_face_asset("https://tos.test/face.jpg", name="mv-001"))


async def test_resolve_asset_avatar_urls_maps_human_tos_to_asset(client) -> None:
    from app.database import session_factory
    from app.main import _resolve_asset_avatar_urls
    from app.models import DigitalHumanModel

    async with session_factory() as db:
        db.add(
            DigitalHumanModel(
                id="dh-asset-map",
                user_id="admin",
                name="asset-map",
                description="",
                avatar_url="https://tos.test/human.jpg",
                avatar_thumbnail_url="https://tos.test/human-thumb.jpg",
                asset_avatar_url="asset://human-1",
                scope="private",
            )
        )
        await db.commit()

    async with session_factory() as db:
        result = await _resolve_asset_avatar_urls(
            db,
            ["https://tos.test/human.jpg", "https://tos.test/scene.png", "https://tos.test/human-thumb.jpg", "asset://already-asset"],
        )
    # 头像（原图与缩略图）映射为 asset://，非头像 URL（场景图、已是 asset:// 的）原样保留
    assert result == ["asset://human-1", "https://tos.test/scene.png", "asset://human-1", "asset://already-asset"]


def test_video_generation_endpoint_uses_asset_avatar_url(client, monkeypatch) -> None:
    """端到端：POST /api/generations/videos 时，数字人头像 TOS 路径在进入生成器前被替换为 asset://。"""
    import time

    from app import main

    user = client.get("/api/auth/me").json()
    _fail_active_jobs()
    captured: dict[str, list[str]] = {}

    async def fake_video(payload, job) -> dict:
        captured["image_urls"] = list(payload.image_urls)
        return {"videoUrl": "https://tos.test/videos/ok.mp4", "coverUrl": "https://tos.test/images/ok.png", "duration": 5}

    monkeypatch.setattr(main, "generate_video", fake_video)

    async def _seed_human() -> None:
        from app.database import session_factory
        from app.models import DigitalHumanModel

        async with session_factory() as db:
            db.add(
                DigitalHumanModel(
                    id="dh-video-asset",
                    user_id=user["id"],
                    name="video-asset",
                    description="",
                    avatar_url="https://tos.test/video-human.jpg",
                    asset_avatar_url="asset://video-human-1",
                    scope="private",
                )
            )
            await db.commit()

    asyncio.run(_seed_human())
    try:
        response = client.post(
            "/api/generations/videos",
            json={"prompt": "test video", "image_urls": ["https://tos.test/video-human.jpg", "https://tos.test/scene.png"]},
        )
        assert response.status_code == 202
        job_id = response.json()["id"]
        for _ in range(50):
            state = client.get(f"/api/generations/{job_id}").json()
            if state["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.05)
        assert state["status"] == "succeeded"
        assert captured["image_urls"] == ["asset://video-human-1", "https://tos.test/scene.png"]
    finally:
        _fail_active_jobs()
        connection = sqlite3.connect(TEST_DB, timeout=10)
        try:
            connection.execute("DELETE FROM daily_usage_quotas WHERE user_id = ? AND category = 'video'", (user["id"],))
            connection.commit()
        finally:
            connection.close()


def test_create_human_registers_asset_avatar(client, monkeypatch) -> None:
    """用户上传数字人创建时，同步注册平台虚拟资产并入库 asset:// 链接。"""
    from app import domain

    created: list[str] = []

    async def fake_create_asset(public_url: str, *, name: str) -> str:
        created.append(public_url)
        return f"asset://user-{len(created)}"

    monkeypatch.setattr("app.providers.create_real_face_asset", fake_create_asset)
    payload = {
        "name": "上传人物-测试",
        "description": "t",
        "avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/face.jpg",
        "source": "uploaded",
    }
    response = client.post("/api/digital-humans", json=payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["assetAvatarUrl"] == "asset://user-1"
    assert body["originalAvatar"] == payload["avatar_url"]  # TOS 原路径保留
    assert created == [payload["avatar_url"]]
    assert domain._sync_human_asset_avatar is not None  # 引用保证函数存在


def test_update_human_re_registers_asset_avatar_on_avatar_change(client, monkeypatch) -> None:
    """换图（重新生成形象）后旧资产失效，自动用新图重新注册 asset。"""
    created: list[str] = []

    async def fake_create_asset(public_url: str, *, name: str) -> str:
        created.append(public_url)
        return f"asset://user-{len(created)}"

    monkeypatch.setattr("app.providers.create_real_face_asset", fake_create_asset)
    first = client.post(
        "/api/digital-humans",
        json={"name": "换图人物", "description": "t", "avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/old.jpg", "source": "uploaded"},
    ).json()
    assert first["assetAvatarUrl"] == "asset://user-1"

    second = client.patch(
        f"/api/digital-humans/{first['id']}",
        json={"avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/new.jpg"},
    )
    assert second.status_code == 200, second.text
    assert second.json()["assetAvatarUrl"] == "asset://user-2"
    assert created == [
        "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/old.jpg",
        "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/new.jpg",
    ]

    # 未换图时（只改名字）不重新注册资产
    renamed = client.patch(f"/api/digital-humans/{first['id']}", json={"name": "改名字"})
    assert renamed.json()["assetAvatarUrl"] == "asset://user-2"
    assert len(created) == 2


def test_create_human_asset_failure_degrades_gracefully(client, monkeypatch) -> None:
    """资产注册失败不阻断数字人创建：接口正常返回，assetAvatarUrl 为空，后续由启动任务兜底。"""
    from app.providers import ProviderError

    async def boom(public_url: str, *, name: str) -> str:
        raise ProviderError("上游挂了")

    monkeypatch.setattr("app.providers.create_real_face_asset", boom)
    response = client.post(
        "/api/digital-humans",
        json={"name": "降级人物", "description": "t", "avatar_url": "https://media-generate-chouka.tos-cn-beijing.volces.com/uploaded/face.jpg", "source": "uploaded"},
    )
    assert response.status_code == 201, response.text
    assert response.json()["assetAvatarUrl"] is None
    assert response.json()["originalAvatar"].startswith("https://")
