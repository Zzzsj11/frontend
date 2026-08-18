import pytest

from app import general_outline_comparison as comparison


@pytest.mark.asyncio
async def test_general_outline_comparison_injects_model_without_changing_default(monkeypatch):
    captured = []

    async def fake_call_chat_model(**kwargs):
        captured.append((kwargs["model"], kwargs["protocol"]))
        return "{}", {"input_tokens": 3, "output_tokens": 4}, "req-1"

    async def fake_generate(*, config, selected_humans, call_override):
        records = []
        await call_override(
            None,
            [{"role": "user", "content": "same prompt"}],
            4000,
            usage_records=records,
            operation="general_story_outline",
        )
        return {
            "shots": [{"index": 0, "shotType": "empty"}],
            "usage": {"input_tokens": 3, "output_tokens": 4},
        }

    monkeypatch.setattr(comparison, "call_chat_model", fake_call_chat_model)
    monkeypatch.setattr(comparison, "generate_general_story_outline", fake_generate)
    results = await comparison.compare_general_outlines(
        models=["gpt-5.5", "claude-opus-4-8"],
        config={"empty_shot_count": 1},
        selected_humans=[],
    )
    assert captured == [("gpt-5.5", "openai"), ("claude-opus-4-8", "anthropic")]
    assert all(item["status"] == "ok" and item["usage"]["totalTokens"] == 7 for item in results)
