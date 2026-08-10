from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.media_constraints import normalize_video_duration
from app.schemas import VideoGenerationCreate
from app.story_bible import build_ass_story_bible, exact_durations
from app.storyboard_prompt import _extract_json, _validate, _validate_ass_outline


def test_exact_durations_preserve_total_and_provider_limits() -> None:
    durations = exact_durations(31.7, 7)
    assert sum(durations) == pytest.approx(31.7)
    assert all(4 <= value <= 15 for value in durations)
    with pytest.raises(ValueError, match="28–105"):
        exact_durations(10, 7)


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
        shot_plan=[
            {"index": index, "shotType": "empty" if index in {0, 3} else "character", "intent": f"intent {index}", "requiredCharacterIds": [] if index in {0, 3} else ["a", "b"]}
            for index in range(6)
        ],
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
        shot_plan=[{"index": 0, "shotType": "character", "intent": "人物回应歌词", "requiredCharacterIds": ["a", "b"]}],
    )
    assert single["shots"][0]["requiredCharacterIds"] == ["a", "b"]


def test_ass_outline_rejects_too_many_or_consecutive_empty_shots() -> None:
    segments = [{"lyrics": str(index)} for index in range(5)]
    valid = {
        "shots": [
            {"index": index, "shotType": "empty" if index in {1, 3} else "character", "intent": f"intent {index}", "requiredCharacterIds": [] if index in {1, 3} else ["a"]}
            for index in range(5)
        ]
    }
    assert len(_validate_ass_outline(valid, segments=segments, role_ids=["a"])) == 5
    invalid = {"shots": [dict(item) for item in valid["shots"]]}
    invalid["shots"][2] = {"index": 2, "shotType": "empty", "intent": "empty", "requiredCharacterIds": []}
    with pytest.raises(ValueError, match="人物镜不能少于|连续空镜"):
        _validate_ass_outline(invalid, segments=segments, role_ids=["a"])


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
