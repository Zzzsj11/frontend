from app.video_prompt_policy import IDENTITY_REFERENCE_MARKER, compile_identity_safe_video_prompt


def test_identity_reference_policy_replaces_vague_reference_and_applies_storyboard_wardrobe() -> None:
    result = compile_identity_safe_video_prompt(
        "人物严格参考人物参考图，在雨夜街头回头。",
        {"human-1": "深蓝防水风衣、黑色长裤和皮靴"},
        season="冬",
    )

    assert "严格参考人物参考图" not in result
    assert IDENTITY_REFERENCE_MARKER in result
    assert "纯白圆领T恤、浅灰棉质短裤" in result
    assert "深蓝防水风衣、黑色长裤和皮靴" in result
    assert "严格符合冬季" in result


def test_identity_reference_policy_is_idempotent_and_has_contextual_fallback() -> None:
    first = compile_identity_safe_video_prompt("人物走入爵士酒吧")
    second = compile_identity_safe_video_prompt(first)

    assert first == second
    assert first.count(IDENTITY_REFERENCE_MARKER) == 1
    assert "用户明确要求 > 季节 > 曲风" in first
