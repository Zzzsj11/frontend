from __future__ import annotations

from typing import Any

from .media_constraints import MAX_VIDEO_DURATION, MIN_VIDEO_DURATION

STORY_BIBLE_VERSION = "story-bible-v1"


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


def build_ass_story_bible(*, segments: list[dict[str, Any]], emotion: dict[str, Any], role_ids: list[str], extra_requirement: str) -> dict[str, Any]:
    total = len(segments)
    shots = []
    for index, segment in enumerate(segments):
        if total == 1:
            roles = role_ids[:]
        else:
            roles = [] if not role_ids or index == 0 else [role_ids[(index - 1) % len(role_ids)]]
        if total > 1 and index == total - 1 and len(role_ids) > 1:
            roles = role_ids[:]
        shots.append({"index": index, "stage": _stage(index, total), "lyrics": segment.get("lyrics", ""), "preferredCharacterIds": roles})
    return {
        "version": STORY_BIBLE_VERSION,
        "logline": f"{emotion.get('songName') or emotion.get('songCode')} 的情绪化 MV，以 {emotion.get('materialCategory') or '歌曲情感'} 为叙事核心。",
        "visualContinuity": {"season": emotion.get("seasons"), "atmosphere": emotion.get("atmosphere"), "stylePriority": extra_requirement or "保持同一时间线、主色调和空间逻辑"},
        "characterPolicy": "用户未选角色时全部生成无人空镜；用户选择角色后，首镜优先建立环境，中段只在所选角色内轮换，收束镜允许所选角色多人同框；不得引入其他人物，也不得改变人物身份和服装。",
        "shots": shots,
    }


def build_general_story_bible(*, config: dict[str, Any], definitions: list[tuple[str, tuple[str, str], list[str]]]) -> dict[str, Any]:
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
            {"index": index, "shotType": shot_type, "stage": _stage(index, total), "outlineScene": outline[0], "outlineShot": outline[1], "requiredCharacterIds": roles}
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
