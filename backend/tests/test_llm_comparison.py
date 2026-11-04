from types import SimpleNamespace

import pytest

from app import llm_comparison


@pytest.mark.asyncio
async def test_compare_chat_models_uses_protocol_adapter_and_isolates_failure(monkeypatch):
    monkeypatch.setattr(
        llm_comparison,
        "settings",
        SimpleNamespace(llm_channel="", llm_api_key="test-key", llm_base_url="https://ai.example.com/v1"),
    )

    async def fake_openai(model, messages, temperature, max_tokens):
        assert messages[-1] == {"role": "user", "content": "同一个问题"}
        assert temperature == 0.2
        assert max_tokens == 512
        return f"{model} answer", {"prompt_tokens": 8, "completion_tokens": 5}, "openai-request"

    async def fake_anthropic(model, messages, temperature, max_tokens):
        raise RuntimeError("anthropic unavailable")

    monkeypatch.setattr(llm_comparison, "_call_openai", fake_openai)
    monkeypatch.setattr(llm_comparison, "_call_anthropic", fake_anthropic)
    results = await llm_comparison.compare_chat_models(
        models=["gpt-5.5", "claude-opus-4-8"],
        system_prompt="系统要求",
        prompt="同一个问题",
        temperature=0.2,
        max_tokens=512,
    )

    assert results[0]["status"] == "ok"
    assert results[0]["usage"]["totalTokens"] == 13
    assert results[1]["status"] == "error"
    assert "anthropic unavailable" in results[1]["error"]


def test_anthropic_messages_url_does_not_duplicate_v1(monkeypatch):
    monkeypatch.setattr(
        llm_comparison,
        "settings",
        SimpleNamespace(llm_channel="", llm_api_key="test-key", llm_base_url="https://ai.example.com/v1"),
    )
    assert llm_comparison._anthropic_messages_url() == "https://ai.example.com/v1/messages"


@pytest.mark.asyncio
async def test_comparison_channels_are_isolated_and_auto_omits_channel(monkeypatch):
    import asyncio

    from app.generation_preferences import text_selection
    from app.llm_policy import completion_options

    monkeypatch.setattr(llm_comparison, "settings", SimpleNamespace(llm_api_key="test"))
    seen = {}

    async def call(**kwargs):
        await asyncio.sleep(0)
        seen[kwargs["model"]] = completion_options(kwargs["model"], 512)
        return "ok", {}, "req"

    monkeypatch.setattr(llm_comparison, "call_chat_model", call)
    models = ["gemini-3.8-flash-all-in-one", "gpt-6.1-sol-all-in-one"]
    token = text_selection.set({"model": "other", "channel": "must-not-leak"})
    try:
        results = await llm_comparison.compare_chat_models(models=models, system_prompt="", prompt="test", temperature=0.2, max_tokens=512, channels={models[0]: "toapis"})
        assert seen[models[0]]["extra_body"] == {"channel": "toapis"}
        assert "extra_body" not in seen[models[1]]
        assert results[0]["requestedChannel"] == "toapis"
        assert text_selection.get()["channel"] == "must-not-leak"
    finally:
        text_selection.reset(token)
