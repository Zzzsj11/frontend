from types import SimpleNamespace

import pytest

from app import llm_comparison


@pytest.mark.asyncio
async def test_compare_chat_models_uses_protocol_adapter_and_isolates_failure(monkeypatch):
    monkeypatch.setattr(
        llm_comparison,
        "settings",
        SimpleNamespace(llm_api_key="test-key", llm_base_url="https://ai.example.com/v1"),
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
        SimpleNamespace(llm_api_key="test-key", llm_base_url="https://ai.example.com/v1"),
    )
    assert llm_comparison._anthropic_messages_url() == "https://ai.example.com/v1/messages"
