from __future__ import annotations

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from app.ass_storyboard import AssCue, group_cues
from app.database import session_factory
from app.domain import uid
from app.media_constraints import normalize_video_duration
from app.models import (
    DigitalHumanModel,
    ProjectCastModel,
    ProjectModel,
    ProjectTaskModel,
    StoryboardLineModel,
    UserModel,
)
from app.schemas import GeneralStoryboardCreate, VideoGenerationCreate
from app.story_bible import build_ass_story_bible, build_general_story_bible, exact_durations
from app.storyboard_prompt import (
    _assign_scene_segments,
    _check_scene_plan,
    _check_segment_body,
    _extract_json,
    _placeholder_shot,
    _validate,
    finalize_shot_durations,
)


def make_outline(segments, empty_indexes=(), role_ids=("a",)):
    location_count = max(1, (len(segments) + 1) // 2)
    locations = [{"id": f"place-{index}", "name": f"场景 {index}", "purpose": "推进叙事"} for index in range(location_count)]
    shots = []
    for index, segment in enumerate(segments):
        is_empty = index in empty_indexes
        gap_after = 0.0
        if index + 1 < len(segments):
            gap_after = round(max(0.0, float(segments[index + 1].get("start") or 0) - float(segment.get("end") or 0)), 2)
        shots.append(
            {
                "index": index,
                "shotType": "empty" if is_empty else "character",
                "intent": f"intent {index}",
                "requiredCharacterIds": [] if is_empty else list(role_ids),
                "locationId": locations[min(index // 2, location_count - 1)]["id"],
                "locationChange": index % 2 == 0,
                "characterAction": "无人环境变化" if is_empty else "人物回应歌词",
                "emotionalFocus": "克制",
                "cameraPurpose": "推进叙事",
                "motifIds": ["s1.rain"] if index < 2 else [],
                "gapAfterAllocation": "current" if 0 < gap_after <= 2 else "none",
                "sceneIndex": min(index // 2, location_count - 1),
                "outlineStatus": "ready",
            }
        )
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
        "motifs": [{"id": "s1.rain", "name": "雨", "meaning": "克制", "maxAppearances": 3}],
        "scenePlan": [
            {
                "sceneIndex": 0,
                "locationId": "place-0",
                "lineStart": 0,
                "lineEnd": 1,
                "locationName": "场景 0",
                "mood": "静",
                "emotion": "克制",
                "visualTone": "冷",
                "narrativePurpose": "铺垫",
            }
        ],
        "failedSegments": [],
        "shots": shots,
    }


def make_scene(line_start, line_end, name="雨夜街道"):
    return {
        "lineStart": line_start,
        "lineEnd": line_end,
        "locationName": name,
        "mood": "潮湿安静",
        "emotion": "克制",
        "visualTone": "冷蓝夜景",
        "narrativePurpose": "推进叙事",
    }


def make_segment_shot(index, shot_type="character", role_ids=("a",), **overrides):
    shot = {
        "index": index,
        "shotType": shot_type,
        "intent": f"意图 {index}",
        "requiredCharacterIds": list(role_ids) if shot_type == "character" else [],
        "characterAction": "人物回应歌词" if shot_type == "character" else "无人环境变化",
        "emotionalFocus": "克制",
        "cameraPurpose": "推进叙事",
        "motifIds": [],
        "gapAfterAllocation": "none",
    }
    shot.update(overrides)
    return shot


def test_exact_durations_preserve_total_and_provider_limits() -> None:
    durations = exact_durations(31.7, 7)
    assert sum(durations) == pytest.approx(31.7)
    assert all(4 <= value <= 15 for value in durations)
    with pytest.raises(ValueError, match="28–105"):
        exact_durations(10, 7)


def test_ass_timeline_splits_gaps_with_two_part_rule_and_chinese_labels() -> None:
    segments = group_cues([AssCue(21.88, 25.0, "第一句"), AssCue(50.0, 53.0, "第二句")])
    assert [item["segmentType"] for item in segments] == ["intro", "intro", "lyric", "interlude", "interlude", "lyric", "outro"]
    assert [item["timelineLabel"] for item in segments] == ["前奏一", "前奏二", "第一句", "间奏一", "间奏二", "第二句", "尾奏"]
    assert (segments[0]["start"], segments[0]["end"]) == (0.0, 11.0)
    assert (segments[1]["start"], segments[1]["end"]) == (11.0, 21.88)
    assert (segments[3]["start"], segments[3]["end"]) == (25.0, 38.0)
    assert (segments[4]["start"], segments[4]["end"]) == (38.0, 50.0)
    assert segments[-1]["start"] == 53.0 and segments[-1]["end"] == 63.0
    assert [item["index"] for item in segments] == list(range(7))


def test_ass_timeline_keeps_short_gaps_single_and_splits_beyond_thirty_seconds() -> None:
    segments = group_cues([AssCue(5.0, 8.0, "A"), AssCue(48.0, 51.0, "B"), AssCue(60.0, 62.0, "C")])
    labels = [item["timelineLabel"] for item in segments]
    assert labels == ["前奏", "A", "间奏一", "间奏二", "间奏三", "B", "间奏", "C", "尾奏"]
    structural = [item for item in segments if item["segmentType"] != "lyric"]
    assert all(item["end"] - item["start"] <= 15 for item in structural)
    middle = [item for item in segments if item["timelineLabel"].startswith("间奏") and item["start"] >= 8.0 and item["end"] <= 48.0]
    assert len(middle) == 3
    assert sum(item["end"] - item["start"] for item in middle) == pytest.approx(40.0)


def test_scene_plan_requires_exact_count_and_full_coverage() -> None:
    global_visual = {
        "visualStyle": "电影写实",
        "colorPalette": "冷蓝",
        "lighting": "夜景",
        "weather": "雨",
        "timeOfDay": "夜",
        "continuityRules": ["服装不变"],
    }
    scenes = [make_scene(0, 7), make_scene(8, 15, "天台"), make_scene(16, 23, "海边"), make_scene(24, 31, "车站"), make_scene(32, 38, "房间")]
    assert _check_scene_plan({"globalVisual": global_visual, "scenes": scenes}, lyric_count=39, expected_scenes=5)["scenes"][0]["lineEnd"] == 7
    with pytest.raises(ValueError, match="必须规划 5 个大场景"):
        _check_scene_plan({"globalVisual": global_visual, "scenes": scenes[:4]}, lyric_count=39, expected_scenes=5)
    overlapped = [dict(scene) for scene in scenes]
    overlapped[1] = {**overlapped[1], "lineStart": 7}
    with pytest.raises(ValueError, match="连续覆盖"):
        _check_scene_plan({"globalVisual": global_visual, "scenes": overlapped}, lyric_count=39, expected_scenes=5)
    missing_tail = [dict(scene) for scene in scenes]
    missing_tail[-1] = {**missing_tail[-1], "lineEnd": 36}
    with pytest.raises(ValueError, match="连续覆盖"):
        _check_scene_plan({"globalVisual": global_visual, "scenes": missing_tail}, lyric_count=39, expected_scenes=5)


def test_segment_body_checks_structure_and_repairs_minor_issues() -> None:
    scene_segments = [
        {"segmentType": "intro", "start": 0.0, "end": 11.0},
        {"segmentType": "lyric", "start": 11.0, "end": 14.0},
        {"segmentType": "lyric", "start": 17.0, "end": 19.0},
    ]
    body = {
        "motifs": [{"id": "rain", "name": "雨", "meaning": "压抑", "maxAppearances": 2}],
        "shots": [
            make_segment_shot(0, "empty"),
            make_segment_shot(1, "character", ("a", "ghost"), motifIds=["rain", "unknown"], gapAfterAllocation="current"),
            make_segment_shot(2, "character", ("a",), gapAfterAllocation="bogus"),
        ],
    }
    normalized = _check_segment_body(body, segment_count=3, role_ids=["a", "b"], scene_index=0, scene_segments=scene_segments)
    assert normalized["motifs"][0]["id"] == "s1.rain"
    assert normalized["shots"][1]["requiredCharacterIds"] == ["a"]
    assert normalized["shots"][1]["motifIds"] == ["s1.rain"]
    assert normalized["shots"][1]["gapAfterAllocation"] == "none"
    assert normalized["shots"][2]["gapAfterAllocation"] == "none"
    with pytest.raises(ValueError, match="必须包含 3 条"):
        _check_segment_body({**body, "shots": body["shots"][:2]}, segment_count=3, role_ids=["a"], scene_index=0, scene_segments=scene_segments)
    with pytest.raises(ValueError, match="无人空镜"):
        _check_segment_body(
            {**body, "shots": [make_segment_shot(0, "character", ("a",))] + body["shots"][1:]}, segment_count=3, role_ids=["a"], scene_index=0, scene_segments=scene_segments
        )
    with pytest.raises(ValueError, match="至少一个已选人物"):
        _check_segment_body(
            {**body, "shots": body["shots"][:1] + [make_segment_shot(1, "character", ("ghost",))] + body["shots"][2:]},
            segment_count=3,
            role_ids=["a"],
            scene_index=0,
            scene_segments=scene_segments,
        )


def test_assign_scene_segments_attaches_structural_parts_to_neighbors() -> None:
    segments = group_cues([AssCue(21.88, 25.0, "第一句"), AssCue(50.0, 53.0, "第二句")])
    scenes = [make_scene(0, 0), make_scene(1, 1, "天台")]
    groups = _assign_scene_segments(segments, scenes)
    assert [item.get("timelineLabel") for item in groups[0]] == ["前奏一", "前奏二", "第一句"]
    assert [item.get("timelineLabel") for item in groups[1]] == ["间奏一", "间奏二", "第二句", "尾奏"]


def test_finalize_shot_durations_allocates_short_gaps() -> None:
    segments = [
        {"start": 1.0, "end": 3.0, "lyrics": "first"},
        {"start": 4.0, "end": 6.0, "lyrics": "second"},
        {"start": 9.0, "end": 11.0, "lyrics": "third"},
    ]
    shots = [make_segment_shot(index) for index in range(3)]
    shots[0]["gapAfterAllocation"] = "next"
    finalize_shot_durations(shots, segments)
    assert shots[0]["materialDuration"] == 2.0
    assert shots[0]["generationDuration"] == 4
    assert shots[1]["materialDuration"] == 3.0
    assert shots[1]["gapAfter"] == 3.0
    assert shots[1]["gapAfterAllocation"] == "none"


def test_placeholder_shot_marks_failed_outline() -> None:
    shot = _placeholder_shot()
    assert shot["outlineStatus"] == "failed"
    assert shot["shotType"] == "empty"
    assert shot["requiredCharacterIds"] == []


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
    assert bible["scenePlan"][0]["locationId"] == "place-0"
    assert bible["failedSegments"] == []
    assert bible["shots"][2]["sceneIndex"] == 1
    assert bible["shots"][2]["outlineStatus"] == "ready"

    single = build_ass_story_bible(
        segments=[{"lyrics": "single"}],
        emotion={"songCode": "1"},
        role_ids=["a", "b"],
        extra_requirement="",
        outline=make_outline([{"lyrics": "single"}], role_ids=("a", "b")),
    )
    assert single["shots"][0]["requiredCharacterIds"] == ["a", "b"]


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
    # 尾部文字不再报错（_extract_json 宽松解析）
    assert _extract_json('{"scenePrompt":"x"} trailing') == {"scenePrompt": "x"}


def test_general_storyboard_rejects_character_shots_without_cast(client) -> None:
    project = client.post("/api/projects", json={"name": "General validation"}).json()
    response = client.post(
        f"/api/projects/{project['id']}/storyboards/general",
        json={
            "genre": "流行歌曲",
            "secondary_category": "爱情消极",
            "season": "summer",
            "gender": "女",
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
        "genre": "流行歌曲",
        "secondary_category": "爱情消极",
        "season": "summer",
        "gender": "女",
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


# ---------- 场景段重试：后台任务 + 幂等 ----------


async def _make_segment_retry_task(db, with_storyboard=True):
    """创建测试任务，返回 task_id。"""
    # 注意：必须用 username 锁定 admin。`limit(1)` 无 ORDER BY 时 SQLite 可能走主键覆盖索引，
    # 返回 id 字典序最小的用户——其它测试先跑创建用户后会让归属漂移，导致 client(admin) 404。
    user = (await db.execute(select(UserModel.id).where(UserModel.username == "admin"))).scalar_one()
    dhs = (await db.execute(select(DigitalHumanModel.id).where(DigitalHumanModel.deleted_at.is_(None)).limit(2))).scalars().all()
    project = ProjectModel(id=uid("proj"), user_id=user, name="test")
    db.add(project)
    await db.flush()
    sb = {}
    if with_storyboard:
        sb = {
            "storyBible": {
                "logline": "test",
                "characterPolicy": "",
                "shots": [
                    {
                        "index": 0,
                        "shotType": "character",
                        "requiredCharacterIds": [dhs[0]],
                        "locationId": "loc-0",
                        "intent": "t",
                        "characterAction": "",
                        "emotionalFocus": "",
                        "cameraPurpose": "",
                        "gapAfterAllocation": "none",
                    },
                    {
                        "index": 1,
                        "shotType": "empty",
                        "requiredCharacterIds": [],
                        "locationId": "loc-0",
                        "intent": "t",
                        "characterAction": "",
                        "emotionalFocus": "",
                        "cameraPurpose": "",
                        "gapAfterAllocation": "none",
                    },
                ],
                "scenePlan": [
                    {
                        "sceneIndex": 0,
                        "locationId": "loc-0",
                        "lineStart": 0,
                        "lineEnd": 1,
                        "locationName": "t",
                        "mood": "c",
                        "emotion": "s",
                        "visualTone": "d",
                        "narrativePurpose": "i",
                    }
                ],
                "failedSegments": [{"sceneIndex": 0, "locationName": "t", "error": "model error"}],
                "locations": [{"id": "loc-0", "name": "t", "purpose": "i"}],
                "motifs": [],
                "globalVisual": {},
            },
        }
    task = ProjectTaskModel(
        id=uid("task"),
        project_id=project.id,
        title="test",
        storyboard_type="ass" if with_storyboard else "general",
        status="generating",
        storyboard_config=sb,
    )
    db.add(task)
    await db.flush()
    if with_storyboard:
        for i in range(2):
            db.add(
                StoryboardLineModel(
                    id=uid("line"),
                    project_task_id=task.id,
                    sort_order=i,
                    lyrics=f"line {i}",
                    start_time=float(i * 5),
                    end_time=float((i + 1) * 5),
                    shot_options={"outlineStatus": "failed" if i == 0 else "done", "segmentType": "lyric", "timelineLabel": f"line {i}"},
                    planned_duration=5,
                )
            )
        db.add(ProjectCastModel(id=uid("cast"), project_task_id=task.id, digital_human_id=dhs[0], sort_order=0))
    await db.commit()
    return task.id


@pytest.mark.asyncio
async def test_segment_retry_202_and_409(client):
    """POST segment regenerate 返回 202，重复提交返回 409。"""
    async with session_factory() as db:
        task_id = await _make_segment_retry_task(db)

    r = client.post(f"/api/tasks/{task_id}/storyboard-outline/segments/0/regenerate")
    assert r.status_code == 202
    assert r.json()["status"] == "segment_retrying"

    r2 = client.post(f"/api/tasks/{task_id}/storyboard-outline/segments/0/regenerate")
    assert r2.status_code == 409
    assert "正在重新生成" in r2.json()["detail"]

    r3 = client.post(f"/api/tasks/{task_id}/storyboard-outline/segments/99/regenerate")
    assert r3.status_code == 422

    async with session_factory() as db:
        gid = await _make_segment_retry_task(db, with_storyboard=False)
    r4 = client.post(f"/api/tasks/{gid}/storyboard-outline/segments/0/regenerate")
    assert r4.status_code == 422
    assert "ASS" in r4.json()["detail"]


@pytest.mark.asyncio
async def test_segment_retry_progress_in_task(client):
    """段重试进度可通过 GET /tasks/{id} 查询 outlineProgress。"""
    async with session_factory() as db:
        task_id = await _make_segment_retry_task(db)

    client.post(f"/api/tasks/{task_id}/storyboard-outline/segments/0/regenerate")

    r = client.get(f"/api/tasks/{task_id}")
    assert r.status_code == 200
    progress = (r.json().get("storyboardConfig") or {}).get("outlineProgress") or {}
    assert progress.get("phase") == "segment_retry"
    assert progress.get("sceneIndex") == 0


# ---------- 段重试失败路径与模型输出宽松解析 ----------


@pytest.mark.asyncio
async def test_segment_retry_failure_marks_progress(client, monkeypatch):
    """段重试后台任务失败：outlineProgress 落为 segment_retry_failed 并带回错误信息。"""
    import time

    from app import domain

    async with session_factory() as db:
        task_id = await _make_segment_retry_task(db)

    async def boom(**kwargs):
        raise RuntimeError("LLM 抖动")

    monkeypatch.setattr(domain, "regenerate_ass_scene_segment", boom)
    response = client.post(f"/api/tasks/{task_id}/storyboard-outline/segments/0/regenerate")
    assert response.status_code == 202

    deadline = time.monotonic() + 3
    progress = {}
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{task_id}").json()
        progress = (task.get("storyboardConfig") or {}).get("outlineProgress") or {}
        if progress.get("phase") == "segment_retry_failed":
            break
        time.sleep(0.01)
    assert progress.get("phase") == "segment_retry_failed"
    assert progress.get("sceneIndex") == 0
    assert "LLM 抖动" in progress.get("error", "")


def test_extract_json_accepts_fenced_and_padded_output() -> None:
    """LLM 输出的常见噪声（围栏、前导说明、尾部寒暄）都应被宽容解析。"""
    from app.storyboard_prompt import _extract_json

    assert _extract_json('{"a": 1}') == {"a": 1}
    assert _extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('```\n{"a": 1}\n```') == {"a": 1}
    assert _extract_json('好的，以下是结果：{"a": 1}') == {"a": 1}
    assert _extract_json('{"a": 1}\n希望对你有帮助') == {"a": 1}
    assert _extract_json('前言 {"a": 1} 后记 {"b": 2}') == {"a": 1}


def test_extract_json_rejects_non_object_and_garbage() -> None:
    from app.storyboard_prompt import _extract_json

    with pytest.raises(ValueError, match="不是 JSON 对象"):
        _extract_json("[1, 2, 3]")
    with pytest.raises(ValueError, match="不是 JSON 对象"):
        _extract_json('"just a string"')
    with pytest.raises(ValueError, match="不是 JSON 对象"):
        _extract_json("```json\n[1]\n```")
    with pytest.raises(ValueError, match="没有返回可解析"):
        _extract_json("完全不是 JSON 的输出")
    with pytest.raises(ValueError, match="没有返回可解析"):
        _extract_json("")


# ---------- 通用分镜：无二级分类曲风（戏曲/中文喊麦） ----------


def test_general_storyboard_create_allows_missing_secondary_category() -> None:
    """戏曲、中文喊麦等无下级分类的曲风：secondary_category 允许缺省不填。"""
    payload = GeneralStoryboardCreate(
        genre="戏曲",
        season="通用",
        gender="女",
        age_group="青年",
        visual_style="国风",
        empty_shot_count=1,
        character_shot_count=1,
        total_duration=8,
    )
    assert payload.secondary_category is None


def test_general_story_bible_logline_skips_empty_secondary_category() -> None:
    """无二级分类时 logline 不得拼出空段（「戏曲 /  风格」式脏文案）。"""
    bible = build_general_story_bible(
        config={"genre": "戏曲", "gender": "女", "season": "通用"},
        definitions=[],
        durations=[],
    )
    assert bible["logline"].startswith("戏曲 风格的完整 MV 视觉弧光")
    assert " / " not in bible["logline"]


def test_general_story_bible_logline_joins_present_categories() -> None:
    """二级分类存在时保持「一级 / 二级」拼接。"""
    bible = build_general_story_bible(
        config={"genre": "流行歌曲", "secondary_category": "爱情消极", "gender": "女", "season": "秋"},
        definitions=[],
        durations=[],
    )
    assert bible["logline"].startswith("流行歌曲 / 爱情消极 风格的完整 MV 视觉弧光")
