from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_failover, storyboard_prompt


class RedisState:
    def __init__(self):
        self.value = 0

    async def get(self, _key):
        return str(self.value) if self.value else None

    async def eval(self, _script, _count, _key, _ttl):
        self.value += 1
        return self.value

    async def delete(self, _key):
        self.value = 0


@pytest.mark.asyncio
async def test_five_primary_failures_switch_later_storyboard_calls_to_fallback(monkeypatch):
    redis = RedisState()
    monkeypatch.setattr(llm_failover, "redis", redis)
    monkeypatch.setattr(llm_failover, "settings", replace(llm_failover.settings, llm_channel="yseeai"))
    monkeypatch.setattr(storyboard_prompt, "settings", replace(storyboard_prompt.settings, llm_channel="yseeai", llm_model="gpt-6.1-sol"))
    monkeypatch.setattr(storyboard_prompt, "log_background_error", AsyncMock())
    success = SimpleNamespace(
        id="fallback-response",
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"scenePrompt":"河边","shotPrompt":"慢推","digitalHumanIds":[]}'))],
        usage=SimpleNamespace(model_dump=lambda **_kwargs: {"total_tokens": 12}),
    )
    create = AsyncMock(side_effect=[RuntimeError("supplier failed") for _ in range(5)] + [success])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    records = []

    for _ in range(5):
        with pytest.raises(RuntimeError, match="supplier failed"):
            await storyboard_prompt._call(client, [], 1400, usage_records=records, operation="storyboard_line")
    assert redis.value == 5
    assert await storyboard_prompt._call(client, [], 1400, usage_records=records, operation="storyboard_line")
    assert [call.kwargs["model"] for call in create.await_args_list] == ["gpt-6.1-sol"] * 5 + ["gpt-6-sol"]
    assert records[-1]["model"] == "gpt-6-sol"
    assert redis.value == 5

    await llm_failover.record_success("gpt-6.1-sol")
    assert await llm_failover.choose_model("gpt-6.1-sol") == "gpt-6.1-sol"
