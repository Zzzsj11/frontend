"""分镜 LLM 调用全量留痕：_call 记录请求快照/返回原文/耗时/错误，admin 只读接口可查询。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app import storyboard_prompt
from app.database import session_factory
from app.token_usage import add_llm_call_log


def _fake_client(*, text: str = '{"ok": true}', error: Exception | None = None):
    async def create(**kwargs):
        if error:
            raise error
        usage = SimpleNamespace(model_dump=lambda mode: {"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))], usage=usage, id="req-test-1")

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_call_records_request_snapshot_response_and_duration() -> None:
    records: list[dict] = []
    messages = [{"role": "user", "content": "原始提示词"}]
    text = asyncio.run(storyboard_prompt._call(_fake_client(), messages, 100, usage_records=records, operation="storyboard_line"))
    assert text == '{"ok": true}'
    assert len(records) == 1
    record = records[0]
    assert record["operation"] == "storyboard_line"
    assert record["status"] == "ok"
    assert record["requestMessages"] == [{"role": "user", "content": "原始提示词"}]
    assert record["responseText"] == '{"ok": true}'
    assert record["requestId"] == "req-test-1"
    assert record["durationMs"] >= 0
    assert record["usage"]["input_tokens"] == 10
    # 快照不受后续重试追加消息污染
    messages.append({"role": "assistant", "content": "后续追加"})
    assert len(record["requestMessages"]) == 1


def test_call_records_api_error_with_snapshot() -> None:
    records: list[dict] = []
    with pytest.raises(RuntimeError):
        asyncio.run(
            storyboard_prompt._call(
                _fake_client(error=RuntimeError("upstream 404")),
                [{"role": "user", "content": "失败前的提示词"}],
                100,
                usage_records=records,
                operation="ass_scene_plan",
            )
        )
    assert len(records) == 1
    record = records[0]
    assert record["status"] == "error"
    assert "upstream 404" in record["error"]
    assert record["requestMessages"][0]["content"] == "失败前的提示词"
    assert record["responseText"] == ""


async def _insert_log() -> str:
    async with session_factory() as session:
        item = add_llm_call_log(
            session,
            operation="storyboard_line",
            provider="openai-compatible",
            model="gpt-5.5",
            usage={"input_tokens": 3, "output_tokens": 2},
            request_id="req-admin-test",
            duration_ms=123,
            request_messages=[{"role": "user", "content": "提示词快照"}],
            response_text="模型返回原文",
        )
        await session.commit()
        return item.id


def test_admin_llm_call_logs_list_filter_and_detail(client) -> None:
    log_id = asyncio.run(_insert_log())
    listed = client.get("/api/admin/llm-calls", params={"operation": "storyboard_line"})
    assert listed.status_code == 200
    row = next(x for x in listed.json()["items"] if x["id"] == log_id)
    assert "requestMessages" not in row  # 列表不含原文，详情接口才返回
    assert row["durationMs"] == 123
    assert client.get("/api/admin/llm-calls", params={"requestId": "req-admin-test"}).json()["total"] >= 1
    assert client.get("/api/admin/llm-calls", params={"status": "error", "requestId": "req-admin-test"}).json()["total"] == 0
    detail = client.get(f"/api/admin/llm-calls/{log_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["requestMessages"] == [{"role": "user", "content": "提示词快照"}]
    assert body["responseText"] == "模型返回原文"
    assert body["inputTokens"] == 3 and body["outputTokens"] == 2
    assert client.get("/api/admin/llm-calls/llm-nonexistent").status_code == 404


def test_non_admin_cannot_read_llm_call_logs(client) -> None:
    created = client.post("/api/admin/users", json={"username": "llm-log-reader", "password": "secure-pass-123"}).json()
    login = client.post("/api/auth/login", json={"username": "llm-log-reader", "password": "secure-pass-123"}).json()
    headers = {"Authorization": f"Bearer {login['accessToken']}"}
    assert client.get("/api/admin/llm-calls", headers=headers).status_code == 403
    client.delete(f"/api/admin/users/{created['id']}")
    # 恢复共享 TestClient 的管理员会话
    restored = client.post("/api/auth/login", json={"username": "admin", "password": "secure-admin-123"})
    client.headers["Authorization"] = f"Bearer {restored.json()['accessToken']}"
