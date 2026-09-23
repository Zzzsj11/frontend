from app.video_prompt_policy import IDENTITY_REFERENCE_MARKER, compile_identity_safe_video_prompt


def test_identity_reference_policy_replaces_vague_reference_and_applies_storyboard_wardrobe() -> None:
    result = compile_identity_safe_video_prompt(
        "人物严格参考人物参考图，在雨夜街头回头。",
        {"human-1": "深蓝防水风衣、黑色长裤和皮靴"},
        season="冬",
    )

    assert "严格参考人物参考图" not in result
    assert IDENTITY_REFERENCE_MARKER in result
    assert "五官、脸型、肤色、年龄感和发型" in result
    assert "不得从头肩照推断或锁定全身身体比例" in result
    assert "发型和身体比例" not in result
    assert "儿童不得成人化" in result
    assert "卡通人物保持卡通风格" in result
    assert "纯白圆领T恤、中性灰背景" in result
    assert "历史身份卡中的浅灰棉质短裤" in result
    assert "多视图排版" in result
    assert "深蓝防水风衣、黑色长裤和皮靴" in result
    assert "严格符合冬季" in result


def test_identity_reference_policy_is_idempotent_and_has_contextual_fallback() -> None:
    first = compile_identity_safe_video_prompt("人物走入爵士酒吧")
    second = compile_identity_safe_video_prompt(first)

    assert first == second
    assert first.count(IDENTITY_REFERENCE_MARKER) == 1
    assert "用户明确要求 > 季节 > 曲风" in first
