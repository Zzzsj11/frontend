import asyncio

from sqlalchemy import select

from app import admin as admin_module
from app.database import session_factory
from app.models import PromptOptimizationTaskModel, TokenUsageModel


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


def test_prompt_optimizer_gemini_records_user_task_and_usage(client, monkeypatch) -> None:
    monkeypatch.setattr(
        admin_module,
        "prompt_optimizer_provider_status",
        lambda: {
            "gemini": {"configured": True, "model": "gemini-3.7-flash", "keyTail": "…test"},
            "minimax": {"configured": False, "model": "MiniMax-H3", "keyTail": ""},
        },
    )
    monkeypatch.setattr(admin_module, "is_tos_url", lambda _url: True)

    async def fake_optimize(**_kwargs):
        return {
            "prompt": "subject_definitions:\n<Subject 1> test",
            "usage": {"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
            "requestId": "gemini-request-1",
            "durationMs": 123,
            "requestSnapshot": [{"role": "user", "content": "test"}],
        }

    monkeypatch.setattr(admin_module, "optimize_with_gemini", fake_optimize)
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
    assert body["status"] == "succeeded"
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
    monkeypatch.setattr(admin_module, "is_tos_url", lambda _url: True)

    async def fake_create(**_kwargs):
        return {"taskId": "provider-task-1", "requestId": "minimax-request-1"}

    async def fake_query(_task_id):
        return {
            "status": "succeeded",
            "prompt": "subject_definitions:\n<Subject 1> official",
            "usage": {"prompt_tokens": 30, "completion_tokens": 10, "total_tokens": 40},
            "error": "",
            "requestId": "query-request-1",
        }

    monkeypatch.setattr(admin_module, "create_minimax_optimization", fake_create)
    monkeypatch.setattr(admin_module, "query_minimax_optimization", fake_query)
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
    first = client.get(f"/api/admin/prompt-optimizer/tasks/{task_id}")
    second = client.get(f"/api/admin/prompt-optimizer/tasks/{task_id}")
    assert first.json()["status"] == "succeeded"
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
