from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.ass_storyboard import AssCue, group_cues
from app.media_constraints import normalize_video_duration
from app.schemas import VideoGenerationCreate
from app.story_bible import build_ass_story_bible, exact_durations
from app.storyboard_prompt import _extract_json, _validate, _validate_ass_outline


def make_outline(segments, empty_indexes=(), role_ids=("a",)):
    location_count = max(1, (len(segments) + 1) // 2)
    locations = [{"id": f"place-{index}", "name": f"场景 {index}", "purpose": "推进叙事"} for index in range(location_count)]
    return {
        "globalVisual": {
            "visualStyle": "电影写实",
            "colorPalette": "冷蓝",
            "lighting": "统一夜景",
            "weather": "细雨",
            "timeOfDay": "夜晚",
            "continuityRules": ["服装不变"],
        },
        "locations": locations,
        "motifs": [{"id": "rain", "name": "雨", "meaning": "克制", "maxAppearances": max(2, (len(segments) + 4) // 5)}],
        "shots": [
            {
                "index": index,
                "shotType": "empty" if index in empty_indexes else "character",
                "intent": f"intent {index}",
                "requiredCharacterIds": [] if index in empty_indexes else list(role_ids),
                "locationId": locations[min(index // 2, location_count - 1)]["id"],
                "locationChange": index == 0 or index % 2 == 0,
                "characterAction": "无人环境变化" if index in empty_indexes else "人物回应歌词",
                "emotionalFocus": "克制",
                "cameraPurpose": "推进叙事",
                "motifIds": ["rain"] if index < max(2, (len(segments) + 4) // 5) else [],
                "gapAfterAllocation": "current"
                if index + 1 < len(segments) and 0 < float(segments[index + 1].get("start") or 0) - float(_segment.get("end") or 0) <= 2
                else "none",
            }
            for index, _segment in enumerate(segments)
        ],
    }


def test_exact_durations_preserve_total_and_provider_limits() -> None:
    durations = exact_durations(31.7, 7)
    assert sum(durations) == pytest.approx(31.7)
    assert all(4 <= value <= 15 for value in durations)
    with pytest.raises(ValueError, match="28–105"):
        exact_durations(10, 7)


def test_ass_timeline_adds_intro_and_splits_long_interludes() -> None:
    segments = group_cues([AssCue(5, 8, "第一句"), AssCue(39, 42, "第二句")])
    assert [item["segmentType"] for item in segments] == ["intro", "lyric", "interlude", "interlude", "interlude", "lyric"]
    assert [item["timelineLabel"] for item in segments[2:5]] == ["间奏 1/3", "间奏 2/3", "间奏 3/3"]
    assert all(item["end"] - item["start"] <= 15 for item in segments)
    assert [item["index"] for item in segments] == list(range(6))
    structural_indexes = {index for index, item in enumerate(segments) if item["segmentType"] != "lyric"}
    outline = make_outline(segments, structural_indexes, ("a",))
    normalized = _validate_ass_outline(outline, segments=segments, role_ids=["a"])
    assert all(normalized["shots"][index]["shotType"] == "empty" for index in structural_indexes)
    invalid = {**outline, "shots": [dict(item) for item in outline["shots"]]}
    invalid["shots"][0] = {**invalid["shots"][0], "shotType": "character", "requiredCharacterIds": ["a"]}
    with pytest.raises(ValueError, match="前奏、间奏和尾奏"):
        _validate_ass_outline(invalid, segments=segments, role_ids=["a"])


def test_video_duration_accepts_full_provider_range_and_normalizes_plans() -> None:
    assert VideoGenerationCreate(prompt="test", duration=4).duration == 4
    assert VideoGenerationCreate(prompt="test", duration=15).duration == 15
    for invalid in (3, 16):
        with pytest.raises(ValidationError):
            VideoGenerationCreate(prompt="test", duration=invalid)
    assert normalize_video_duration(1.2) == 4
    assert normalize_video_duration(9.6) == 10
    assert normalize_video_duration(20) == 15


def test_ass_story_bible_has_shared_arc_and_character_plan() -> None:
    bible = build_ass_story_bible(
        segments=[{"lyrics": str(index)} for index in range(6)],
        emotion={"songCode": "10012204", "songName": "他不爱我", "materialCategory": "流行歌曲-爱情消极-失恋", "seasons": "冬", "atmosphere": "冷色调"},
        role_ids=["a", "b"],
        extra_requirement="电影感",
        outline=make_outline([{"lyrics": str(index)} for index in range(6)], {0, 3}, ("a", "b")),
    )
    assert bible["shots"][0]["requiredCharacterIds"] == []
    assert bible["shots"][-1]["requiredCharacterIds"] == ["a", "b"]
    assert bible["shots"][1]["shotType"] == "character"
    assert bible["visualContinuity"]["season"] == "冬"

    single = build_ass_story_bible(
        segments=[{"lyrics": "single"}],
        emotion={"songCode": "1"},
        role_ids=["a", "b"],
        extra_requirement="",
        outline=make_outline([{"lyrics": "single"}], role_ids=("a", "b")),
    )
    assert single["shots"][0]["requiredCharacterIds"] == ["a", "b"]


def test_ass_outline_rejects_too_many_or_consecutive_empty_shots() -> None:
    segments = [{"lyrics": str(index)} for index in range(5)]
    valid = make_outline(segments, {1, 3})
    assert len(_validate_ass_outline(valid, segments=segments, role_ids=["a"])["shots"]) == 5
    invalid = {**valid, "shots": [dict(item) for item in valid["shots"]]}
    invalid["shots"][2] = {**invalid["shots"][2], "shotType": "empty", "requiredCharacterIds": [], "characterAction": "无人环境变化"}
    with pytest.raises(ValueError, match="人物镜不能少于|连续空镜"):
        _validate_ass_outline(invalid, segments=segments, role_ids=["a"])


def test_ass_outline_allocates_short_lyric_gaps_to_material_duration() -> None:
    segments = [
        {"start": 1.0, "end": 3.0, "lyrics": "first"},
        {"start": 4.0, "end": 6.0, "lyrics": "second"},
        {"start": 9.0, "end": 11.0, "lyrics": "third"},
    ]
    outline = make_outline(segments, role_ids=("a",))
    outline["shots"][0]["gapAfterAllocation"] = "next"
    normalized = _validate_ass_outline(outline, segments=segments, role_ids=["a"])
    assert normalized["shots"][0]["materialDuration"] == 2.0
    assert normalized["shots"][0]["generationDuration"] == 4
    assert normalized["shots"][1]["materialDuration"] == 3.0
    assert normalized["shots"][1]["generationDuration"] == 4
    assert normalized["shots"][1]["gapAfter"] == 3.0
    assert normalized["shots"][1]["gapAfterAllocation"] == "none"


def test_ass_outline_requires_character_actions_and_location_variety() -> None:
    segments = [
        {"lyrics": "不是说好拥抱过后一起放手"},
        {"lyrics": "两个人沿着街一直走"},
        {"lyrics": "但是我们依然牵着手"},
        {"lyrics": "求求你不要再看着我"},
        {"lyrics": "我们微笑约定"},
        {"lyrics": "时间一点点走过"},
    ]
    valid = make_outline(segments, {5})
    assert len(_validate_ass_outline(valid, segments=segments, role_ids=["a"])["locations"]) >= 3
    wrong_type = {**valid, "shots": [dict(item) for item in valid["shots"]]}
    wrong_type["shots"][2] = {**wrong_type["shots"][2], "shotType": "empty", "requiredCharacterIds": [], "characterAction": "无人空镜"}
    with pytest.raises(ValueError, match="必须规划为人物镜"):
        _validate_ass_outline(wrong_type, segments=segments, role_ids=["a"])
    repeated_location = {**valid, "shots": [{**item, "locationId": "place-0"} for item in valid["shots"]]}
    with pytest.raises(ValueError, match="至少需要 3 个有效场景"):
        _validate_ass_outline(repeated_location, segments=segments, role_ids=["a"])


def test_storyboard_output_schema_is_strict() -> None:
    humans = [{"id": "a"}]
    valid = _validate({"scenePrompt": "scene", "shotPrompt": "shot", "digitalHumanIds": ["a"]}, source="general", current={"plannedDigitalHumanIds": ["a"]}, allowed_humans=humans)
    assert valid["digitalHumanIds"] == ["a"]
    with pytest.raises(ValueError, match="字段必须严格"):
        _validate(
            {"scenePrompt": "scene", "shotPrompt": "shot", "digitalHumanIds": ["a"], "extra": True},
            source="general",
            current={"plannedDigitalHumanIds": ["a"]},
            allowed_humans=humans,
        )
    with pytest.raises(ValueError, match="不可用角色"):
        _validate({"scenePrompt": "scene", "shotPrompt": "shot", "digitalHumanIds": ["x"]}, source="ass", current={}, allowed_humans=humans)
    with pytest.raises(ValueError, match="预分配人物不一致"):
        _validate({"scenePrompt": "scene", "shotPrompt": "shot", "digitalHumanIds": []}, source="ass", current={"plannedDigitalHumanIds": ["a"]}, allowed_humans=humans)
    with pytest.raises(ValueError, match="额外内容"):
        _extract_json('{"scenePrompt":"x"} trailing')


def test_general_storyboard_rejects_character_shots_without_cast(client) -> None:
    project = client.post("/api/projects", json={"name": "General validation"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        json={
            "genre": "pop",
            "secondary_category": "positive",
            "season": "summer",
            "age_group": "young",
            "visual_style": "cinematic",
            "empty_shot_count": 0,
            "character_shot_count": 2,
            "total_duration": 10,
            "digital_human_ids": [],
        },
    )
    assert response.status_code == 422
    assert "至少需要选择一个角色" in response.json()["detail"]


def test_general_storyboard_enforces_four_to_fifteen_seconds_per_shot(client) -> None:
    project = client.post("/api/projects", json={"name": "Duration validation"}).json()
    base = {
        "genre": "pop",
        "secondary_category": "positive",
        "season": "summer",
        "age_group": "young",
        "visual_style": "cinematic",
        "empty_shot_count": 2,
        "character_shot_count": 0,
        "digital_human_ids": [],
    }
    too_short = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        json={**base, "total_duration": 7},
    )
    assert too_short.status_code == 422
    assert "8–30" in too_short.json()["detail"]

    too_long = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        json={**base, "total_duration": 31},
    )
    assert too_long.status_code == 422
    assert "8–30" in too_long.json()["detail"]

    valid = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        json={**base, "total_duration": 8},
    )
    assert valid.status_code == 201
    task = client.get(f"/api/tasks/{valid.json()['taskId']}").json()
    assert task["storyboardConfig"]["resolution"] == "720p"
    assert task["storyboardConfig"]["image_model"] == "gpt-image-2"
    assert task["storyboardConfig"]["video_model"] == "doubao-seedance-2.0"
    assert all(line["shotOptions"]["resolution"] == "720p" for line in task["lines"])
