from __future__ import annotations

from typing import Any

from .media_constraints import MAX_VIDEO_DURATION, MIN_VIDEO_DURATION, normalize_video_duration
from .prompts import get_prompt

STORY_BIBLE_VERSION = "story-bible-v6"


def _stage(index: int, total: int) -> str:
    if index == 0:
        return "建立世界与情绪"
    if index == total - 1:
        return "留白、回应与收束"
    position = (index + 0.5) / max(1, total)
    if position <= 0.2:
        return "建立世界与情绪"
    if position <= 0.45:
        return "引入人物与关系"
    if position <= 0.75:
        return "推进行动与情感升温"
    if position <= 0.9:
        return "情绪高点与视觉高潮"
    return "留白、回应与收束"


async def build_ass_story_bible(*, segments: list[dict[str, Any]], emotion: dict[str, Any], role_ids: list[str], extra_requirement: str, outline: dict[str, Any]) -> dict[str, Any]:
    # 策略文案由提示词注册中心提供（后台可编辑/回滚）；or 缺省逻辑留在代码
    logline_prompt = await get_prompt("story_bible.ass.logline")
    style_priority_prompt = await get_prompt("story_bible.ass.style_priority_default")
    character_policy_prompt = await get_prompt("story_bible.ass.character_policy")
    negative_constraints_prompt = await get_prompt("story_bible.ass.negative_constraints")
    location_rule_prompt = await get_prompt("story_bible.ass.location_rule")
    total = len(segments)
    shots = [
        {
            **plan,
            "index": index,
            "stage": _stage(index, total),
            "lyrics": segment.get("lyrics", ""),
            "segmentType": segment.get("segmentType", "lyric"),
            "timelineLabel": segment.get("timelineLabel") or segment.get("lyrics", ""),
            "requiredCharacterIds": list(plan["requiredCharacterIds"]),
            "sourceDuration": plan.get("sourceDuration", round(max(0.0, float(segment.get("end") or 0) - float(segment.get("start") or 0)), 2)),
            "gapBefore": plan.get("gapBefore", 0.0),
            "gapAfter": plan.get("gapAfter", 0.0),
            "gapAfterAllocation": plan.get("gapAfterAllocation", "none"),
            "materialDuration": plan.get("materialDuration", round(max(0.0, float(segment.get("end") or 0) - float(segment.get("start") or 0)), 2)),
            "generationDuration": plan.get(
                "generationDuration",
                normalize_video_duration(plan.get("materialDuration", float(segment.get("end") or 0) - float(segment.get("start") or 0))),
            ),
        }
        for index, (segment, plan) in enumerate(zip(segments, outline["shots"], strict=True))
    ]
    return {
        "version": STORY_BIBLE_VERSION,
        "logline": logline_prompt.render(song_name=emotion.get("songName") or emotion.get("songCode"), material_category=emotion.get("materialCategory") or "歌曲情感"),
        "globalVisual": outline["globalVisual"],
        "locations": outline["locations"],
        "motifs": outline["motifs"],
        "scenePlan": outline.get("scenePlan") or [],
        "failedSegments": outline.get("failedSegments") or [],
        "visualContinuity": {
            "season": emotion.get("seasons"),
            "atmosphere": emotion.get("atmosphere"),
            "stylePriority": extra_requirement or style_priority_prompt.render(),
        },
        "characterPolicy": character_policy_prompt.render(),
        "technicalPolicy": {
            "negativeConstraints": negative_constraints_prompt.render_json(),
            "locationRule": location_rule_prompt.render(),
        },
        "shots": shots,
    }


async def build_general_story_bible(*, config: dict[str, Any], shots: list[dict[str, Any]], durations: list[float]) -> dict[str, Any]:
    logline_prompt = await get_prompt("story_bible.general.logline")
    character_policy_prompt = await get_prompt("story_bible.general.character_policy")
    total = len(shots)
    # 部分曲风（戏曲、中文喊麦）没有二级分类，拼接风格路径时跳过空段
    category_path = " / ".join(part for part in (config.get("genre"), config.get("secondary_category")) if part)
    return {
        "version": STORY_BIBLE_VERSION,
        "logline": logline_prompt.render(category_path=category_path, gender=config.get("gender") or "女"),
        "visualContinuity": {
            "season": config.get("season"),
            "singerGender": config.get("gender"),
            "visualStyle": config.get("visual_style"),
            "ratio": config.get("ratio"),
            "overallPrompt": config.get("overall_prompt"),
        },
        "characterPolicy": character_policy_prompt.render(),
        "shots": [
            {
                "index": index,
                "shotType": shot["shotType"],
                "stage": _stage(index, total),
                "outlineScene": shot["outlineScene"],
                "outlineShot": shot["outlineShot"],
                "requiredCharacterIds": shot["requiredCharacterIds"],
                "intent": shot["intent"],
                "characterAction": shot["characterAction"],
                "emotionalFocus": shot["emotionalFocus"],
                "cameraPurpose": shot["cameraPurpose"],
                "materialDuration": durations[index],
                "generationDuration": normalize_video_duration(durations[index]),
            }
            for index, shot in enumerate(shots)
        ],
    }


def exact_durations(total_duration: float, count: int) -> list[float]:
    if count < 1 or total_duration < count * MIN_VIDEO_DURATION or total_duration > count * MAX_VIDEO_DURATION:
        raise ValueError(f"总时长必须在 {count * MIN_VIDEO_DURATION}–{count * MAX_VIDEO_DURATION} 秒之间，才能保证每镜 {MIN_VIDEO_DURATION}–{MAX_VIDEO_DURATION} 秒")
    units = round(total_duration * 10)
    base, remainder = divmod(units, count)
    values = [base + (1 if index < remainder else 0) for index in range(count)]
    return [value / 10 for value in values]
