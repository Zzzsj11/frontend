from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app import llm_failover, storyboard_prompt


class RedisState:
    def __init__(self):
        self.value = 0
        self.ttl = None
        self.key = None

    async def get(self, _key):
        return str(self.value) if self.value else None

    async def eval(self, _script, _count, _key, _ttl):
        self.value += 1
        self.key = _key
        self.ttl = _ttl
        return self.value

    async def delete(self, _key):
        self.value = 0


@pytest.mark.asyncio
@pytest.mark.parametrize("channel", ["yseeai", "toapis"])
async def test_legacy_channels_do_not_switch_models(monkeypatch, channel):
    redis = RedisState()
    monkeypatch.setattr(llm_failover, "redis", redis)
    monkeypatch.setattr(llm_failover, "settings", replace(llm_failover.settings, llm_channel=channel))
    monkeypatch.setattr(storyboard_prompt, "settings", replace(storyboard_prompt.settings, llm_channel=channel, llm_model="gpt-6.1-sol"))
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
    assert redis.value == 0
    assert await storyboard_prompt._call(client, [], 1400, usage_records=records, operation="storyboard_line")
    assert [call.kwargs["model"] for call in create.await_args_list] == ["gpt-6.1-sol"] * 6
    assert records[-1]["model"] == "gpt-6.1-sol"
    assert redis.value == 0

    await llm_failover.record_success("gpt-6.1-sol")
    assert await llm_failover.choose_model("gpt-6.1-sol") == "gpt-6.1-sol"


@pytest.mark.asyncio
async def test_all_in_one_never_changes_selected_model(monkeypatch):
    redis = RedisState()
    monkeypatch.setattr(llm_failover, "redis", redis)
    monkeypatch.setattr(llm_failover, "settings", replace(llm_failover.settings, llm_channel="all-in-one", llm_failover_enabled=True))
    for _ in range(5):
        await llm_failover.record_failure("gemini-3.8-flash-all-in-one")
    assert redis.ttl == 2 * 60 * 60
    assert await llm_failover.choose_model("gemini-3.8-flash-all-in-one") == "gemini-3.8-flash-all-in-one"
    await llm_failover.record_success("gemini-3.8-flash-all-in-one")
    assert await llm_failover.choose_model("gemini-3.8-flash-all-in-one") == "gemini-3.8-flash-all-in-one"
