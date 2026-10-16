"""供应商内容拒绝必须保留用量并终止，不应额外付费做 JSON 修复。"""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

from app import llm_comparison, storyboard_prompt
from app.llm_policy import LlmContentPolicyError, check_provider_text

REFUSAL = (
    "The prompt could not be submitted. The prompt contains sensitive words that violate Google's "
    "[Generative AI Prohibited Use policy](https://policies.google.com/terms/generative-ai/use-policy). Try rephrasing the prompt."
)


def test_provider_content_refusal_is_distinct_from_structured_story_content():
    with pytest.raises(LlmContentPolicyError, match="内容审核未通过"):
        check_provider_text(REFUSAL)
    check_provider_text('{"scenePrompt": "The prompt could not be submitted is an error label", "shotPrompt": "都市街景"}')


@pytest.mark.asyncio
async def test_content_refusal_preserves_usage_without_repair_or_availability_failover(client, monkeypatch):
    monkeypatch.setattr(storyboard_prompt, "settings", replace(storyboard_prompt.settings, llm_channel="all-in-one", llm_model="gemini-3.8-flash-all-in-one"))
    call = AsyncMock(return_value=(REFUSAL, {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}, "synthetic-refusal"))
    monkeypatch.setattr(llm_comparison, "call_chat_model", call)
    failure = AsyncMock()
    monkeypatch.setattr(storyboard_prompt, "record_failure", failure)
    monkeypatch.setattr(storyboard_prompt, "log_background_error", AsyncMock())
    with pytest.raises(storyboard_prompt.StoryboardPromptError, match="内容审核未通过") as error:
        await storyboard_prompt.generate_storyboard_line(
            source="ass",
            current={"shotType": "character", "plannedDigitalHumanIds": ["adult"], "outline": {"wardrobeByCharacter": {"adult": "黑色牛仔外套"}}},
            full_context={},
            allowed_humans=[{"id": "adult", "name": "青年人物"}],
        )
    assert call.await_count == 1
    failure.assert_not_awaited()
    assert error.value.usage == {"input_tokens": 100, "output_tokens": 20}
    assert error.value.request_id == "synthetic-refusal"
    assert error.value.usage_records[0]["responseText"] == REFUSAL
