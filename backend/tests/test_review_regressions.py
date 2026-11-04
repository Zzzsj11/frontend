"""异常恢复与计费回归；所有供应商均为内存替身，不调用真实模型。"""

import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app import all_in_one, chat, config, creative, llm_failover, model_gateway, optimizer_media, prompt_optimizer
from app.database import session_factory
from app.jobs import jobs
from app.models import ChatMessageModel, GenerationJobModel, LlmCallLogModel, PromptOptimizationTaskModel, TokenUsageModel

PRIMARY = "gemini-3.8-flash-all-in-one"


def platform_settings(monkeypatch):
    settings = replace(config.settings, llm_channel="all-in-one", llm_model=PRIMARY)
    for module in (config, chat, creative, llm_failover, prompt_optimizer):
        monkeypatch.setattr(module, "settings", settings)
    monkeypatch.setattr(optimizer_media, "content_parts", AsyncMock(return_value=[]))
    from app import generation_preferences

    monkeypatch.setattr(generation_preferences, "settings", settings)
    return settings


def response(text="complete prompt"):
    return SimpleNamespace(
        id="synthetic-response",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(model_dump=lambda **_: {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17}),
    )


def client_factory(create):
    class Client:
        chat = SimpleNamespace(completions=SimpleNamespace(create=create))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def close(self):
            pass

    return Client


def test_optimizer_replay_freezes_input_and_reuses_accepted_request(client, monkeypatch):
    platform_settings(monkeypatch)
    user_id = client.get("/api/auth/me").json()["id"]
    monkeypatch.setattr(model_gateway, "current_owner", lambda: user_id)
    keys, payloads = [], []
    accepted = response()

    async def create(**payload):
        payloads.append(payload)
        if len(payloads) == 1:
            # 模拟平台已受理，但返回前连接中断；第二次按相同键返回同一结果。
            raise TimeoutError("synthetic connection lost after acceptance")
        return accepted

    def factory(**kwargs):
        keys.append(kwargs["idempotency_key"])
        return client_factory(create)()

    monkeypatch.setattr(all_in_one, "chat_client", factory)

    async def verify():
        async with session_factory() as db:
            job = await jobs.enqueue(db, "prompt_optimization", {}, user_id=user_id)
            await db.commit()
        monkeypatch.setattr(model_gateway, "current_job_id", lambda: job.id)
        args = dict(prompt="original intent", duration=5, ratio="16:9", media=[], agent_name="code-agent", agent_run_id="synthetic-replay")
        with pytest.raises(prompt_optimizer.OptimizationCallError):
            await prompt_optimizer._call_platform(**args)
        # 重启后故障计数、配置、素材解析都可能变化；必须使用入库快照。
        monkeypatch.setattr(llm_failover, "choose_model", AsyncMock(side_effect=AssertionError("must reuse frozen model")))
        monkeypatch.setattr(optimizer_media, "content_parts", AsyncMock(side_effect=AssertionError("must reuse frozen media")))
        second = await prompt_optimizer._call_platform(**{**args, "prompt": "changed after restart"})
        third = await prompt_optimizer._call_platform(**args)
        assert second["requestId"] == third["requestId"] == accepted.id
        assert keys == [f"aio-{job.id}:prompt-optimization:v1"] * 2
        assert payloads[0] == payloads[1]
        assert second["model"] == PRIMARY
        assert second["usage"]["total_tokens"] == 17
        async with session_factory() as db:
            row = await db.get(GenerationJobModel, job.id)
            assert row.request["_optimizationRequest"]["model"] == PRIMARY
            assert row.idempotency_key == keys[0]
            assert row.request["_optimizationResponse"]["requestId"] == accepted.id

    asyncio.run(verify())


def test_completed_optimizer_replay_never_calls_supplier_or_duplicates_usage(client, monkeypatch):
    platform_settings(monkeypatch)
    create = AsyncMock(return_value=response())
    monkeypatch.setattr(all_in_one, "chat_client", lambda **_: client_factory(create)())
    created = client.post("/api/creative/optimizations", json={"provider": "gemini", "prompt": "synthetic successful replay"})
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    from tests.test_prompt_optimizer import wait_for_task

    wait_for_task(client, f"/api/creative/optimizations/{task_id}")

    async def verify():
        async with session_factory() as db:
            row = await db.scalar(select(GenerationJobModel).where(GenerationJobModel.request["optimization_task_id"].as_string() == task_id))
            job = jobs._from_model(row)
        assert await creative.run_prompt_optimization_job(job) == {"optimizationTaskId": task_id, "provider": "all-in-one"}
        assert create.await_count == 1
        async with session_factory() as db:
            usages = list((await db.scalars(select(TokenUsageModel).where(TokenUsageModel.generation_job_id == job.id))).all())
            logs = list((await db.scalars(select(LlmCallLogModel).where(LlmCallLogModel.generation_job_id == job.id))).all())
            assert len(usages) == len(logs) == 1

    asyncio.run(verify())


@pytest.mark.parametrize("reply", ["模型繁忙", ""])
def test_optimizer_busy_response_preserves_failure_usage_and_audit(client, monkeypatch, reply):
    platform_settings(monkeypatch)
    completion = response(reply)
    if not reply:
        completion.choices = []
    create = AsyncMock(return_value=completion)
    monkeypatch.setattr(all_in_one, "chat_client", lambda **_: client_factory(create)())
    created = client.post("/api/creative/optimizations", json={"provider": "gemini", "prompt": "synthetic busy response"})
    assert created.status_code == 201, created.text
    task_id = created.json()["id"]
    from tests.test_prompt_optimizer import wait_for_task

    wait_for_task(client, f"/api/creative/optimizations/{task_id}", "failed")

    async def verify():
        async with session_factory() as db:
            task = await db.get(PromptOptimizationTaskModel, task_id)
            job = await db.scalar(select(GenerationJobModel).where(GenerationJobModel.request["optimization_task_id"].as_string() == task_id))
            usages = list((await db.scalars(select(TokenUsageModel).where(TokenUsageModel.generation_job_id == job.id))).all())
            logs = list((await db.scalars(select(LlmCallLogModel).where(LlmCallLogModel.generation_job_id == job.id))).all())
            assert task.request_id == "synthetic-response"
            assert task.usage_data["total_tokens"] == 17
            assert len(usages) == len(logs) == 1
            assert usages[0].total_tokens == logs[0].total_tokens == 17
            assert usages[0].model == logs[0].model == PRIMARY
            assert usages[0].provider == "all-in-one"
            assert logs[0].request_messages and logs[0].response_text == reply
            assert logs[0].request_id == usages[0].request_id == "synthetic-response"
            assert job.generation_origin == "agent_test" and job.agent_name == "code-agent"
            replay = jobs._from_model(job)
        # 模拟失败记录已提交、工单终态尚未提交时进程中断，再次领取同一工单。
        with pytest.raises(prompt_optimizer.OptimizationCallError) as caught:
            await model_gateway.run_with_context(replay, creative.run_prompt_optimization_job)
        assert caught.value.usage_recorded
        assert create.await_count == 1
        async with session_factory() as db:
            assert len(list(await db.scalars(select(TokenUsageModel).where(TokenUsageModel.generation_job_id == replay.id)))) == 1
            assert len(list(await db.scalars(select(LlmCallLogModel).where(LlmCallLogModel.generation_job_id == replay.id)))) == 1

    # 业务状态先写，费用由工单异常处理随后写入；等待工单真正完成。
    import time

    for _ in range(100):

        async def terminal():
            async with session_factory() as db:
                row = await db.scalar(select(GenerationJobModel).where(GenerationJobModel.request["optimization_task_id"].as_string() == task_id))
                return row.status == "failed"

        if asyncio.run(terminal()):
            break
        time.sleep(0.02)
    asyncio.run(verify())


def test_chat_busy_text_counts_failures_without_changing_model(client, monkeypatch):
    platform_settings(monkeypatch)
    monkeypatch.setattr(llm_failover, "settings", replace(llm_failover.settings, llm_failover_enabled=True))
    user_id = client.get("/api/auth/me").json()["id"]
    monkeypatch.setattr(chat, "redis", SimpleNamespace(get=AsyncMock(return_value=None)))
    events = AsyncMock()
    monkeypatch.setattr(chat, "append_chat_event", events)
    from tests.test_llm_failover import RedisState

    state = RedisState()
    monkeypatch.setattr(llm_failover, "redis", state)
    models = []

    async def create(**kwargs):
        models.append(kwargs["model"])

        async def chunks():
            yield SimpleNamespace(
                id=f"synthetic-chat-{len(models)}", usage=None, choices=[SimpleNamespace(delta=SimpleNamespace(content="模型繁忙" if len(models) <= 5 else "正常回复"))]
            )
            yield SimpleNamespace(id=None, choices=[], usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5})

        return chunks()

    monkeypatch.setattr(all_in_one, "chat_client", lambda **_: client_factory(create)())

    async def verify():
        session = await chat.chat_manager.create(user_id, "synthetic test")
        for _ in range(6):
            await chat.chat_manager._run(session)
        assert models == ["gemini-3.8-flash"] * 6
        assert state.value == 0
        assert sum(call.args[1] == "error" for call in events.await_args_list) == 5
        assert sum(call.args[1] == "assistant_done" for call in events.await_args_list) == 1
        async with session_factory() as db:
            messages = list((await db.scalars(select(ChatMessageModel).where(ChatMessageModel.session_id == session.id, ChatMessageModel.role == "assistant"))).all())
            usage = list((await db.scalars(select(TokenUsageModel).where(TokenUsageModel.chat_session_id == session.id))).all())
            assert [item.content for item in messages] == ["正常回复"]
            assert len(usage) == 6 and all(item.total_tokens == 5 for item in usage)

    asyncio.run(verify())
