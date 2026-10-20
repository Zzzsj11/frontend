from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_comparison, llm_failover, storyboard_prompt, text_recovery
from app.llm_policy import UncertainLlmError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,points,message,safe",
    [
        ("reserved", None, "Chat submission unavailable; billing may be uncertain", False),
        ("settled", "0.000000", "Provider connection unavailable; no supplier request submitted", True),
        ("settled", "1", "Provider connection unavailable; no supplier request submitted", False),
    ],
)
async def test_recovery_requires_confirmed_zero_cost_rejection(monkeypatch, status, points, message, safe):
    error = RuntimeError("platform failure")
    error.body = {"error": {"job_id": "synthetic-platform-job"}}
    monkeypatch.setattr(text_recovery, "query_task", AsyncMock(return_value={"status": "FAILED", "billing": {"status": status, "points": points}, "error": message}))
    if safe:
        assert await text_recovery.reconcile(error) is None
    else:
        with pytest.raises(UncertainLlmError, match="待核对") as exc:
            await text_recovery.reconcile(error)
        assert exc.value.platform_job_id == "synthetic-platform-job"
        assert exc.value.platform_usage["platformBilling"]["status"] == status


@pytest.mark.asyncio
async def test_safe_platform_retries_keep_gemini_and_record_each_attempt(monkeypatch):
    settings = replace(storyboard_prompt.settings, llm_channel="all-in-one", llm_model="gemini-3.8-flash-all-in-one")
    monkeypatch.setattr(storyboard_prompt, "settings", settings)
    monkeypatch.setattr(llm_failover, "settings", replace(settings, llm_failover_enabled=False))
    error = RuntimeError("unsubmitted")
    error.status_code = 502
    error.body = {"error": {"job_id": "synthetic-platform-job"}}
    call = AsyncMock(side_effect=[error, ("{}", {"total_tokens": 12}, "success")])
    monkeypatch.setattr(llm_comparison, "call_chat_model", call)
    monkeypatch.setattr(
        text_recovery,
        "query_task",
        AsyncMock(
            return_value={"status": "FAILED", "error": "Provider connection unavailable; no supplier request submitted", "billing": {"status": "settled", "points": "0.000000"}}
        ),
    )
    monkeypatch.setattr(storyboard_prompt, "retry_delay", AsyncMock())
    from app import text_admission

    monkeypatch.setattr(text_admission, "cooldown", AsyncMock())
    records = []
    assert await storyboard_prompt._call(None, [], 1400, operation="storyboard_line", usage_records=records) == "{}"
    assert [record["status"] for record in records] == ["error", "ok"]
    assert records[0]["requestId"] == "synthetic-platform-job"
    assert all(call.kwargs["model"] == "gemini-3.8-flash-all-in-one" for call in call.await_args_list)


@pytest.mark.asyncio
async def test_disabled_failover_keeps_primary_after_failures(monkeypatch):
    monkeypatch.setattr(llm_failover, "settings", replace(llm_failover.settings, llm_channel="all-in-one", llm_failover_enabled=False))
    monkeypatch.setattr(llm_failover, "redis", SimpleNamespace(get=AsyncMock(return_value="99")))
    assert await llm_failover.choose_model("gemini-3.8-flash-all-in-one") == "gemini-3.8-flash-all-in-one"


@pytest.mark.asyncio
async def test_wardrobe_is_compiled_without_paid_repair(client, monkeypatch):
    import json

    call = AsyncMock(return_value=json.dumps({"scenePrompt": "雪夜车站", "shotPrompt": "人物回头，镜头缓推", "digitalHumanIds": ["a"]}))

    async def recorded(*args, **kwargs):
        kwargs["usage_records"].append({"requestId": "synthetic", "usage": {}})
        return await call(*args, **kwargs)

    monkeypatch.setattr(storyboard_prompt, "_call", recorded)
    result = await storyboard_prompt.generate_storyboard_line(
        source="general",
        current={"shotType": "character", "plannedDigitalHumanIds": ["a"], "outline": {"wardrobeByCharacter": {"a": "深蓝羽绒服、羊毛长裤与防滑短靴"}}},
        full_context={},
        allowed_humans=[{"id": "a", "name": "角色A"}],
    )
    assert "角色A：深蓝羽绒服、羊毛长裤与防滑短靴" in result["shotPrompt"]
    call.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_submission_is_not_retried_and_preserves_billing(monkeypatch):
    monkeypatch.setattr(storyboard_prompt, "settings", replace(storyboard_prompt.settings, llm_model="gemini-3.8-flash-all-in-one"))
    error = RuntimeError("uncertain submission")
    error.status_code = 502
    error.body = {"error": {"job_id": "synthetic-uncertain"}}
    call = AsyncMock(side_effect=error)
    monkeypatch.setattr(llm_comparison, "call_chat_model", call)
    monkeypatch.setattr(
        text_recovery, "query_task", AsyncMock(return_value={"status": "FAILED", "billing": {"status": "reserved", "points": None}, "error": "billing may be uncertain"})
    )
    records = []
    with pytest.raises(UncertainLlmError):
        await storyboard_prompt._call(None, [], 1400, operation="storyboard_line", usage_records=records)
    call.assert_awaited_once()
    assert records[0]["requestId"] == "synthetic-uncertain"
    assert records[0]["usage"]["platformBilling"]["status"] == "reserved"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403])
async def test_settled_provider_auth_failure_stops_without_uncertain_billing(monkeypatch, status):
    monkeypatch.setattr(storyboard_prompt, "settings", replace(storyboard_prompt.settings, llm_model="gemini-3.8-flash-all-in-one"))
    error = RuntimeError("provider rejected")
    error.status_code = 502
    error.body = {"error": {"job_id": "synthetic-rejected"}}
    call = AsyncMock(side_effect=error)
    monkeypatch.setattr(llm_comparison, "call_chat_model", call)
    monkeypatch.setattr(
        text_recovery,
        "query_task",
        AsyncMock(
            return_value={"status": "FAILED", "billing": {"status": "settled", "points": "0.000000"}, "error": f"Provider HTTP {status}: Provider rejected the chat request"}
        ),
    )
    monkeypatch.setattr(storyboard_prompt, "log_background_error", AsyncMock())
    records = []
    with pytest.raises(RuntimeError, match="鉴权或额度异常，本次未计费") as rejected:
        await storyboard_prompt._call(None, [], 1400, operation="storyboard_line", usage_records=records)
    assert not isinstance(rejected.value, UncertainLlmError)
    call.assert_awaited_once()
    assert records[0]["requestId"] == "synthetic-rejected"
    assert records[0]["usage"]["platformBilling"] == {"status": "settled", "points": "0.000000"}


@pytest.mark.asyncio
async def test_stream_setup_retries_only_confirmed_unsubmitted(monkeypatch):
    error = RuntimeError("capacity")
    error.status_code = 429
    create = AsyncMock(side_effect=[error, "synthetic-stream"])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(text_recovery, "retry_delay", AsyncMock())
    from app import text_admission

    monkeypatch.setattr(text_admission, "cooldown", AsyncMock())
    on_retry = AsyncMock()
    assert await text_recovery.create_stream(client, {}, key="stable", on_retry=on_retry) == "synthetic-stream"
    assert [call.kwargs["extra_headers"]["Idempotency-Key"] for call in create.await_args_list] == ["stable-0", "stable-1"]
    on_retry.assert_awaited_once()
