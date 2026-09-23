from app.video_prompt_policy import IDENTITY_REFERENCE_MARKER, compile_identity_safe_video_prompt


def test_identity_reference_policy_replaces_vague_reference_and_applies_storyboard_wardrobe() -> None:
    result = compile_identity_safe_video_prompt(
        "人物严格参考人物参考图，在雨夜街头回头。",
        {"human-1": "深蓝防水风衣、黑色长裤和皮靴"},
        season="冬",
    )

    assert "严格参考人物参考图" not in result
    assert IDENTITY_REFERENCE_MARKER in result
    assert "五官、脸型、肤色和年龄感" in result
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


def test_quality_requirements_are_shot_specific_and_survive_silent_h3():
    from app.h3_prompt_compiler import compile_h3_prompt
    from app.schemas import VideoGenerationCreate
    from app.video_prompt_policy import append_shot_quality_requirements

    for shot_type in ("character", "empty"):
        for source in ("雨夜街头", "integrated_multimodal_description: 雨夜街头\noverall_soundscape: 雨声\nnon_diegetic_music: N/A"):
            prompt = append_shot_quality_requirements(source, shot_type=shot_type)
            assert append_shot_quality_requirements(prompt, shot_type=shot_type) == prompt
            assert prompt.count("视频整体画质类似实拍视频") == 1
            assert ("人物表情自然不僵硬" in prompt) == (shot_type == "character")
            compiled = compile_h3_prompt(VideoGenerationCreate(prompt=prompt, generate_audio=False)).prompt
            assert "视频整体画质类似实拍视频" in compiled
            assert ("人物表情自然不僵硬" in compiled) == (shot_type == "character")


def test_generated_direction_removes_defaults_but_respects_explicit_solo_and_hair():
    from app.video_prompt_policy import relax_generated_character_direction

    source = "【人物镜*单人*老年男性】保持五官、脸型、肤色、年龄感和发型不变。仅此一人出镜，无其他人物。穿蓝色风衣，走过车站。"
    relaxed = relax_generated_character_direction(source)
    assert "主角1人" in relaxed
    assert "发型不变" not in relaxed
    assert "无其他人物" not in relaxed
    assert "仅此一人出镜" not in relaxed
    assert "穿蓝色风衣，走过车站" in relaxed
    explicit = relax_generated_character_direction(source, user_requirement="单人独处，发型不变")
    assert "无其他人物" in explicit
    assert "发型不变" in explicit
