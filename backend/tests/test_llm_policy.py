from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import storyboard_prompt
from app.llm_policy import TemporaryLlmError, completion_options


def response(text):
    return SimpleNamespace(
        id="test-response",
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(model_dump=lambda **kwargs: {"prompt_tokens": 12, "completion_tokens": 22, "total_tokens": 34}),
    )


@pytest.mark.asyncio
async def test_busy_response_retries_and_preserves_usage(monkeypatch):
    create = AsyncMock(side_effect=[response("We're temporarily unable to respond to this volume of requests. Please try again later."), response('{"shots":[]}')])
    monkeypatch.setattr(storyboard_prompt, "retry_delay", AsyncMock())
    records = []
    text = await storyboard_prompt._call(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), [], 3400, usage_records=records, operation="test")
    assert text == '{"shots":[]}'
    assert [r["status"] for r in records] == ["error", "ok"]
    assert records[0]["usage"]["completion_tokens"] == 22
    assert create.await_count == 2


@pytest.mark.asyncio
async def test_transport_retries_are_bounded(monkeypatch):
    create = AsyncMock(side_effect=TimeoutError("upstream request timeout"))
    monkeypatch.setattr(storyboard_prompt, "retry_delay", AsyncMock())
    records = []
    with pytest.raises(TemporaryLlmError, match="自动重试"):
        await storyboard_prompt._call(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), [], 3400, usage_records=records, operation="test")
    assert create.await_count == len(records) == 3


def test_astra_completion_parameters():
    assert completion_options("gpt-6-astra", 3400) == {"max_completion_tokens": 8192, "reasoning_effort": "low"}
    assert completion_options("gpt-5.5", 3400) == {"max_tokens": 3400, "temperature": 0.2}


def test_missing_wardrobe_does_not_report_wrong_shot_count():
    with pytest.raises(ValueError, match="缺少.*wardrobeGroups") as error:
        storyboard_prompt._check_general_outline_v2({"shots": [{}] * 17}, expected_count=17, empty_count=4, character_count=13, role_ids=["person"])
    assert "shots 必须" not in str(error.value)


@pytest.mark.asyncio
async def test_outline_model_override_is_recorded_and_scoped(monkeypatch):
    import dataclasses

    monkeypatch.setattr(storyboard_prompt, "settings", dataclasses.replace(storyboard_prompt.settings, llm_model="gpt-5.5", general_outline_llm_model="gpt-6-astra"))
    create = AsyncMock(return_value=response('{"shots":[]}'))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    records = []
    await storyboard_prompt._call(client, [], 3400, usage_records=records, operation="general_story_outline_v2")
    assert create.call_args.kwargs["model"] == records[0]["model"] == "gpt-6-astra"
    assert "temperature" not in create.call_args.kwargs
    await storyboard_prompt._call(client, [], 1400, usage_records=records, operation="storyboard_line")
    assert create.call_args.kwargs["model"] == records[1]["model"] == "gpt-5.5"


@pytest.mark.asyncio
async def test_structural_and_transport_retries_share_budget(monkeypatch):
    create = AsyncMock(side_effect=TimeoutError())
    monkeypatch.setattr(storyboard_prompt, "retry_delay", AsyncMock())
    records = [{"operation": "general_story_outline_v2"}] * 4
    with pytest.raises(TemporaryLlmError):
        await storyboard_prompt._call(
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), [], 3400, usage_records=records, operation="general_story_outline_v2_retry"
        )
    assert create.await_count == 1
    assert len(records) == 5
    with pytest.raises(TemporaryLlmError, match="5 次"):
        await storyboard_prompt._call(
            SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), [], 3400, usage_records=records, operation="general_story_outline_v2_retry"
        )
    assert create.await_count == 1


@pytest.mark.asyncio
async def test_outline_repairs_structure_with_precise_feedback(monkeypatch):
    import dataclasses
    import json

    monkeypatch.setattr(storyboard_prompt, "settings", dataclasses.replace(storyboard_prompt.settings, llm_api_key="test"))
    shot = {"i": 0, "t": "e", "s": "海边", "b": "建立", "c": [], "a": "浪花起伏", "e": "平静", "m": "广角"}
    outputs = [{"wrong": []}, {"shots": []}, {"shots": [shot]}]
    calls = []

    async def call(_client, messages, _max_tokens, **kwargs):
        calls.append([dict(message) for message in messages])
        return json.dumps(outputs[len(calls) - 1])

    result = await storyboard_prompt._generate_general_story_outline_v2(
        config={"empty_shot_count": 1, "character_shot_count": 0}, selected_humans=[], on_progress=None, call_override=call
    )
    assert len(result["shots"]) == 1
    assert len(calls) == 3
    assert "缺少 ['shots']" in calls[1][-1]["content"]
    assert "实际 0 条" in calls[2][-1]["content"]
    assert "顶层必须且只能包含 shots" in calls[0][0]["content"]
