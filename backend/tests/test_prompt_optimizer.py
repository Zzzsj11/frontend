import asyncio
import time

from sqlalchemy import select

from app import admin as admin_module
from app import creative as creative_module
from app import prompt_optimizer
from app.database import session_factory
from app.models import PromptOptimizationTaskModel, TokenUsageModel
from app.storage import is_user_owned_tos_url


def wait_for_task(client, path: str, expected: str = "succeeded") -> dict:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        body = client.get(path).json()
        if body["status"] not in {"queued", "running"}:
            assert body["status"] == expected
            return body
        time.sleep(0.05)
    raise AssertionError("prompt optimization task did not finish")


def test_prompt_optimizer_status_is_admin_only(client, monkeypatch) -> None:
    monkeypatch.setattr(
        admin_module,
        "prompt_optimizer_provider_status",
        lambda: {
            "gemini": {"configured": True, "model": "gemini-3.7-flash", "keyTail": "…test"},
            "minimax": {"configured": True, "model": "MiniMax-H3", "keyTail": "…test"},
        },
    )
    response = client.get("/api/admin/prompt-optimizer/status")
    assert response.status_code == 200
    body = response.json()
    assert body["providers"]["gemini"]["configured"] is True
    assert body["providers"]["minimax"]["configured"] is True
    assert body["limits"]["images"] == 9
    assert body["durationRange"] == [4, 15]


def test_prompt_optimizer_upload_registers_tos_and_runninghub(client, monkeypatch) -> None:
    monkeypatch.setattr(admin_module, "_runninghub_guard", lambda: None)

    async def fake_put_image(_key, _content, _mime_type):
        return "https://tos.example/person.jpg", "https://tos.example/person-thumb.jpg"

    async def fake_rh_upload(_content, filename):
        assert filename == "person.jpg"
        return {"fileName": "rh-person.jpg", "downloadUrl": "https://rh.example/person.jpg", "size": "5"}

    monkeypatch.setattr(admin_module, "put_image_with_thumbnail", fake_put_image)
    monkeypatch.setattr(admin_module, "rh_upload_media", fake_rh_upload)
    response = client.post(
        "/api/admin/prompt-optimizer/upload",
        files={"file": ("person.jpg", b"image", "image/jpeg")},
    )
    assert response.status_code == 200
    assert response.json()["url"] == "https://tos.example/person.jpg"
    assert response.json()["thumbnailUrl"] == "https://tos.example/person-thumb.jpg"
    assert response.json()["runningHubFileName"] == "rh-person.jpg"


def test_prompt_optimizer_gemini_records_user_task_and_usage(client, monkeypatch) -> None:
    monkeypatch.setattr(
        admin_module,
        "prompt_optimizer_provider_status",
        lambda: {
            "gemini": {"configured": True, "model": "gemini-3.7-flash", "keyTail": "…test"},
            "minimax": {"configured": False, "model": "MiniMax-H3", "keyTail": ""},
        },
    )
    monkeypatch.setattr(admin_module, "is_user_owned_tos_url", lambda _url, _user_id: True)

    async def fake_optimize(**_kwargs):
        return {
            "prompt": "subject_definitions:\n<Subject 1> test",
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            "requestId": "gemini-request-1",
            "durationMs": 123,
            "requestSnapshot": [{"role": "user", "content": "test"}],
        }

    monkeypatch.setattr(creative_module, "call_gemini", fake_optimize)
    response = client.post(
        "/api/admin/prompt-optimizer/tasks",
        json={
            "provider": "gemini",
            "prompt": "保持人物，迁移动作",
            "duration": 15,
            "ratio": "16:9",
            "media": [
                {
                    "kind": "image",
                    "url": "https://tos.example/person.jpg",
                    "name": "person.jpg",
                    "mimeType": "image/jpeg",
                    "role": "character",
                }
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    body = wait_for_task(client, f"/api/admin/prompt-optimizer/tasks/{body['id']}")
    assert body["outputPrompt"].startswith("subject_definitions:")

    async def verify() -> None:
        async with session_factory() as db:
            task = (await db.execute(select(PromptOptimizationTaskModel).where(PromptOptimizationTaskModel.id == body["id"]))).scalar_one()
            assert task.user_id
            assert task.generation_origin == "agent_test"
            usage = (
                await db.execute(
                    select(TokenUsageModel).where(
                        TokenUsageModel.operation == "admin_prompt_optimization",
                        TokenUsageModel.request_id == "gemini-request-1",
                    )
                )
            ).scalar_one()
            assert usage.total_tokens == 20

    asyncio.run(verify())


def test_prompt_optimizer_minimax_poll_records_usage_once(client, monkeypatch) -> None:
    monkeypatch.setattr(
        admin_module,
        "prompt_optimizer_provider_status",
        lambda: {
            "gemini": {"configured": False, "model": "gemini-3.7-flash", "keyTail": ""},
            "minimax": {"configured": True, "model": "MiniMax-H3", "keyTail": "…test"},
        },
    )
    monkeypatch.setattr(admin_module, "is_user_owned_tos_url", lambda _url, _user_id: True)

    async def fake_create(**_kwargs):
        return {"taskId": "provider-task-1", "requestId": "minimax-request-1"}

    async def fake_query(_task_id, **_kwargs):
        return {
            "status": "succeeded",
            "prompt": "subject_definitions:\n<Subject 1> official",
            "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            "error": "",
            "requestId": "query-request-1",
        }

    monkeypatch.setattr(creative_module, "create_minimax", fake_create)
    monkeypatch.setattr(creative_module, "query_minimax", fake_query)
    created = client.post(
        "/api/admin/prompt-optimizer/tasks",
        json={
            "provider": "minimax",
            "prompt": "生成 15 秒多参考舞蹈",
            "duration": 15,
            "ratio": "16:9",
            "media": [
                {
                    "kind": "video",
                    "url": "https://tos.example/dance.mp4",
                    "name": "dance.mp4",
                    "mimeType": "video/mp4",
                }
            ],
        },
    )
    assert created.status_code == 201
    assert created.json()["status"] == "running"
    task_id = created.json()["id"]
    first_body = wait_for_task(client, f"/api/admin/prompt-optimizer/tasks/{task_id}")
    second = client.get(f"/api/admin/prompt-optimizer/tasks/{task_id}")
    assert first_body["status"] == "succeeded"
    assert second.json()["outputPrompt"].endswith("official")

    async def verify() -> None:
        async with session_factory() as db:
            rows = list(
                (
                    await db.execute(
                        select(TokenUsageModel).where(
                            TokenUsageModel.operation == "admin_prompt_optimization",
                            TokenUsageModel.request_id == "minimax-request-1",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(rows) == 1
            assert rows[0].total_tokens == 40

    asyncio.run(verify())


def test_prompt_optimizer_rejects_non_tos_media(client, monkeypatch) -> None:
    monkeypatch.setattr(
        admin_module,
        "prompt_optimizer_provider_status",
        lambda: {
            "gemini": {"configured": True, "model": "gemini-3.7-flash", "keyTail": "…test"},
            "minimax": {"configured": False, "model": "MiniMax-H3", "keyTail": ""},
        },
    )
    response = client.post(
        "/api/admin/prompt-optimizer/tasks",
        json={
            "provider": "gemini",
            "prompt": "test",
            "media": [{"kind": "image", "url": "https://untrusted.example/a.jpg", "name": "a.jpg", "mimeType": "image/jpeg"}],
        },
    )
    assert response.status_code == 422
    assert "TOS" in response.json()["detail"]


def test_creative_gemini_optimization_is_available_to_authenticated_user(client, monkeypatch) -> None:
    monkeypatch.setattr(
        creative_module,
        "provider_status",
        lambda: {
            "gemini": {"configured": True, "model": "gemini-3.7-flash", "keyTail": "…test"},
            "minimax": {"configured": False, "model": "MiniMax-H3", "keyTail": ""},
        },
    )

    async def fake_optimize(**_kwargs):
        return {
            "prompt": "subject_definitions:\ncreative test",
            "usage": {"prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10},
            "requestId": "creative-gemini-1",
            "durationMs": 20,
            "requestSnapshot": [{"role": "user", "content": "creative"}],
        }

    monkeypatch.setattr(creative_module, "call_gemini", fake_optimize)
    response = client.post(
        "/api/creative/optimizations",
        json={"provider": "gemini", "prompt": "创意视频", "duration": 8, "ratio": "16:9", "media": []},
    )
    assert response.status_code == 201
    body = wait_for_task(client, f"/api/creative/optimizations/{response.json()['id']}")
    assert body["outputPrompt"].endswith("creative test")


def test_gemini_preserves_multimedia_content_types(monkeypatch) -> None:
    captured = {}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **kwargs):
            captured.update(kwargs["json"])
            import httpx

            return httpx.Response(200, request=httpx.Request("POST", "https://provider.test"), json={"choices": [{"message": {"content": "ok"}}]})

    monkeypatch.setattr(prompt_optimizer.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    asyncio.run(
        prompt_optimizer.call_gemini(
            prompt="test",
            duration=8,
            ratio="16:9",
            media=[
                {"kind": "image", "url": "https://tos.test/i.jpg"},
                {"kind": "video", "url": "https://tos.test/v.mp4"},
                {"kind": "audio", "url": "https://tos.test/a.mp3"},
            ],
        )
    )
    content = captured["messages"][0]["content"]
    assert [item["type"] for item in content[1:]] == ["image_url", "video_url", "audio_url"]


def test_minimax_missing_task_id_includes_response_body(monkeypatch) -> None:
    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, _url, **_kwargs):
            import httpx

            return httpx.Response(200, request=httpx.Request("POST", "https://provider.test"), json={"message": "accepted without id"})

    monkeypatch.setattr(prompt_optimizer.httpx, "AsyncClient", lambda **_kwargs: FakeClient())
    try:
        asyncio.run(prompt_optimizer.create_minimax(prompt="test", duration=8, ratio="16:9", media=[]))
    except RuntimeError as exc:
        assert "missing task_id" in str(exc)
        assert "accepted without id" in str(exc)
    else:
        raise AssertionError("missing task_id must fail")


def test_user_owned_tos_url_requires_user_prefix(monkeypatch) -> None:
    monkeypatch.setattr("app.storage.is_tos_url", lambda _url: True)
    assert is_user_owned_tos_url("https://tos.test/users/user-1/creative/image/a.jpg", "user-1")
    assert not is_user_owned_tos_url("https://tos.test/users/user-2/creative/image/a.jpg", "user-1")
