from __future__ import annotations

from typing import Any

from .media_constraints import MAX_VIDEO_DURATION, MIN_VIDEO_DURATION, normalize_video_duration

STORY_BIBLE_VERSION = "story-bible-v4"


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


def build_ass_story_bible(*, segments: list[dict[str, Any]], emotion: dict[str, Any], role_ids: list[str], extra_requirement: str, outline: dict[str, Any]) -> dict[str, Any]:
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
        "logline": f"{emotion.get('songName') or emotion.get('songCode')} 的情绪化 MV，以 {emotion.get('materialCategory') or '歌曲情感'} 为叙事核心。",
        "globalVisual": outline["globalVisual"],
        "locations": outline["locations"],
        "motifs": outline["motifs"],
        "visualContinuity": {
            "season": emotion.get("seasons"),
            "atmosphere": emotion.get("atmosphere"),
            "stylePriority": extra_requirement or "统一时间、天气、色彩与人物服装，通过合理空间移动形成场景变化",
        },
        "characterPolicy": "逐镜类型、人物、地点与动作均由全局大纲确定。单条生成必须严格沿用 requiredCharacterIds、shotType、locationId 和 characterAction；不得临时改为空镜、替换人物、引入其他人物或改变人物身份服装。",
        "technicalPolicy": {
            "negativeConstraints": ["无字幕", "无水印", "无 Logo", "不得出现未指定人物", "不得改变人物服装与身份"],
            "locationRule": "同一故事世界允许跨多个关联地点推进；一致性来自时间、天气、色彩、服装和空间衔接，而非所有镜头固定在同一地点。",
        },
        "shots": shots,
    }


def build_general_story_bible(*, config: dict[str, Any], definitions: list[tuple[str, tuple[str, str], list[str]]], durations: list[float]) -> dict[str, Any]:
    total = len(definitions)
    return {
        "version": STORY_BIBLE_VERSION,
        "logline": f"{config.get('genre')} / {config.get('secondary_category')} 风格的完整 MV 视觉弧光。",
        "visualContinuity": {
            "season": config.get("season"),
            "visualStyle": config.get("visual_style"),
            "ratio": config.get("ratio"),
            "overallPrompt": config.get("overall_prompt"),
        },
        "characterPolicy": "空镜严禁人物；人物镜必须完整使用本镜预分配角色，角色顺序不得改变。",
        "shots": [
            {
                "index": index,
                "shotType": shot_type,
                "stage": _stage(index, total),
                "outlineScene": outline[0],
                "outlineShot": outline[1],
                "requiredCharacterIds": roles,
                "materialDuration": durations[index],
                "generationDuration": normalize_video_duration(durations[index]),
            }
            for index, (shot_type, outline, roles) in enumerate(definitions)
        ],
    }


def exact_durations(total_duration: float, count: int) -> list[float]:
    if count < 1 or total_duration < count * MIN_VIDEO_DURATION or total_duration > count * MAX_VIDEO_DURATION:
        raise ValueError(f"总时长必须在 {count * MIN_VIDEO_DURATION}–{count * MAX_VIDEO_DURATION} 秒之间，才能保证每镜 {MIN_VIDEO_DURATION}–{MAX_VIDEO_DURATION} 秒")
    units = round(total_duration * 10)
    base, remainder = divmod(units, count)
    values = [base + (1 if index < remainder else 0) for index in range(count)]
    return [value / 10 for value in values]
