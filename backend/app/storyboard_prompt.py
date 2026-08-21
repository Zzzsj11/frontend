from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any

from openai import AsyncOpenAI

from .config import settings
from .error_logging import log_background_error
from .media_constraints import normalize_video_duration
from .prompts import get_prompt

PROMPT_VERSION = "storyboard-v7"
SCHEMA_VERSION = "storyboard-line-v2"

STRUCTURAL_TYPES = {"intro", "interlude", "outro"}

# 大纲生成进度回调：{"phase": "planning" | "segments", "segmentsDone": int, "segmentsTotal": int}
ProgressCallback = Callable[[dict[str, Any]], Awaitable[None]]
LlmCallOverride = Callable[..., Awaitable[str]]


def _empty_ratio_rule(lyric_total: int) -> str:
    """按全歌歌词句数给出空镜占比目标区间（仅 prompt 引导，不做程序校验）。"""
    if lyric_total >= 40:
        lo, hi = 20, 30
    elif lyric_total >= 20:
        lo, hi = 15, 25
    else:
        lo, hi = 10, 20
    return (
        f"全歌共 {lyric_total} 句歌词镜头，其中空镜（不含 intro、interlude、outro 结构段）全歌目标占比约 {lo}%–{hi}%；"
        "请在本场景内依据歌词情绪节奏自然安排空镜，使全歌汇总落在该区间。"
    )


class StoryboardPromptError(ValueError):
    def __init__(self, message: str, *, usage_records: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.usage_records = usage_records or []
        self.usage = _sum_usage(self.usage_records)
        self.request_id = self.usage_records[-1].get("requestId") if self.usage_records else None


def _check_scene_plan(body: dict[str, Any], *, lyric_count: int, expected_scenes: int, role_ids: list[str] | None = None) -> dict[str, Any]:
    """第一轮场景规划的结构完整性检查（非审美校验）。"""
    if set(body) != {"globalVisual", "scenes"}:
        raise ValueError("场景规划必须严格包含 globalVisual、scenes")
    global_visual = body["globalVisual"]
    if not isinstance(global_visual, dict) or not all(global_visual.get(key) for key in ("visualStyle", "colorPalette", "lighting", "weather", "timeOfDay", "continuityRules")):
        raise ValueError("globalVisual 缺少完整视觉连续性字段")
    if not isinstance(global_visual["continuityRules"], list) or not all(isinstance(value, str) and value.strip() for value in global_visual["continuityRules"]):
        raise ValueError("continuityRules 必须是非空字符串数组")
    scenes = body["scenes"]
    if not isinstance(scenes, list) or len(scenes) != expected_scenes:
        raise ValueError(f"必须规划 {expected_scenes} 个大场景")
    normalized = []
    allowed_roles = set(role_ids or [])
    previous_wardrobe: dict[str, str] = {}
    for scene in scenes:
        required = {"lineStart", "lineEnd", "locationName", "mood", "emotion", "visualTone", "narrativePurpose", "wardrobeByCharacter"}
        if not isinstance(scene, dict) or set(scene) != required:
            raise ValueError(f"每个场景必须严格包含：{sorted(required)}")
        if not isinstance(scene["lineStart"], int) or not isinstance(scene["lineEnd"], int) or not 0 <= scene["lineStart"] <= scene["lineEnd"] < lyric_count:
            raise ValueError(f"场景行号范围必须在 0 到 {lyric_count - 1} 之间且 lineStart 不大于 lineEnd")
        if not all(isinstance(scene.get(key), str) and scene[key].strip() for key in ("locationName", "mood", "emotion", "visualTone", "narrativePurpose")):
            raise ValueError("场景地点、意境、情绪、视觉基调与叙事功能不能为空")
        wardrobe = scene["wardrobeByCharacter"]
        if not isinstance(wardrobe, dict) or set(wardrobe) != allowed_roles:
            raise ValueError("每个大场景必须为全部已选人物提供 wardrobeByCharacter 服装方案")
        normalized_wardrobe = {}
        for human_id, outfit in wardrobe.items():
            if not isinstance(outfit, str) or not outfit.strip():
                raise ValueError("每个人物的场景服装必须是非空描述")
            normalized_outfit = outfit.strip()
            if re.search(r"换成|换上|改穿|更换为|脱下.{0,20}穿上|室内.{0,30}出门", normalized_outfit):
                raise ValueError("同一大场景内每个人物只能有一套服装，不得描述场景内换装")
            if previous_wardrobe.get(human_id) == normalized_outfit:
                raise ValueError("同一人物在相邻大场景必须更换明显不同的整套服装")
            normalized_wardrobe[human_id] = normalized_outfit
        previous_wardrobe = normalized_wardrobe
        normalized.append({**scene, "locationName": scene["locationName"].strip(), "wardrobeByCharacter": normalized_wardrobe})
    ordered = sorted(normalized, key=lambda item: item["lineStart"])
    if ordered[0]["lineStart"] != 0 or ordered[-1]["lineEnd"] != lyric_count - 1 or any(right["lineStart"] != left["lineEnd"] + 1 for left, right in zip(ordered, ordered[1:])):
        raise ValueError(f"各场景必须按顺序连续覆盖第 0 到 {lyric_count - 1} 句歌词，不得重叠或遗漏")
    return {"globalVisual": global_visual, "scenes": ordered}


def _check_segment_body(body: dict[str, Any], *, segment_count: int, role_ids: list[str], scene_index: int, scene_segments: list[dict[str, Any]]) -> dict[str, Any]:
    """第二轮场景段大纲的结构完整性检查；时长、人物、母题引用等小问题直接程序修正。"""
    if set(body) != {"motifs", "shots"}:
        raise ValueError("场景段大纲必须严格包含 motifs、shots")
    prefix = f"s{scene_index + 1}."
    motifs, motif_ids = [], set()
    for motif in body["motifs"] if isinstance(body["motifs"], list) else []:
        if not isinstance(motif, dict) or not all(isinstance(motif.get(key), str) and motif[key].strip() for key in ("id", "name", "meaning")):
            continue
        motif_id = f"{prefix}{motif['id'].strip()}"
        if motif_id in motif_ids:
            continue
        motif_ids.add(motif_id)
        max_appearances = motif.get("maxAppearances")
        motifs.append(
            {
                "id": motif_id,
                "name": motif["name"].strip(),
                "meaning": motif["meaning"].strip(),
                "maxAppearances": max_appearances if isinstance(max_appearances, int) and max_appearances >= 1 else 3,
            }
        )
    shots = body["shots"]
    if not isinstance(shots, list) or len(shots) != segment_count:
        raise ValueError(f"shots 必须包含 {segment_count} 条镜头规划")
    allowed, normalized = set(role_ids), []
    required_fields = {"index", "shotType", "intent", "requiredCharacterIds", "characterAction", "emotionalFocus", "cameraPurpose", "motifIds", "gapAfterAllocation"}
    for position, shot in enumerate(shots):
        if not isinstance(shot, dict) or set(shot) != required_fields:
            raise ValueError(f"每条镜头必须严格包含：{sorted(required_fields)}")
        shot_type = shot["shotType"]
        if shot_type not in {"empty", "character"} or not isinstance(shot["intent"], str) or not shot["intent"].strip():
            raise ValueError("镜头类型或叙事意图不合法")
        required = list(dict.fromkeys(value for value in shot["requiredCharacterIds"] if isinstance(value, str))) if isinstance(shot["requiredCharacterIds"], list) else []
        required = [value for value in required if value in allowed]
        structural = scene_segments[position].get("segmentType") in STRUCTURAL_TYPES
        if structural and shot_type != "empty":
            raise ValueError("前奏、间奏和尾奏必须规划为无人空镜")
        if structural or shot_type == "empty":
            required = []
        if shot_type == "character" and not required:
            raise ValueError("人物镜必须包含至少一个已选人物")
        if not all(isinstance(shot.get(key), str) for key in ("characterAction", "emotionalFocus", "cameraPurpose")):
            raise ValueError("镜头动作、情绪重点和镜头目的必须是字符串")
        motif_refs = [f"{prefix}{value}" for value in shot["motifIds"] if isinstance(value, str)] if isinstance(shot["motifIds"], list) else []
        gap_after = 0.0
        if position + 1 < len(scene_segments):
            gap_after = round(max(0.0, float(scene_segments[position + 1].get("start") or 0) - float(scene_segments[position].get("end") or 0)), 2)
        allocation = shot["gapAfterAllocation"]
        if allocation not in {"current", "next", "none"} or (allocation != "none" and not 0 < gap_after <= 2):
            allocation = "none"
        normalized.append(
            {
                "index": position,
                "shotType": shot_type,
                "intent": shot["intent"].strip(),
                "requiredCharacterIds": required,
                "characterAction": shot["characterAction"].strip(),
                "emotionalFocus": shot["emotionalFocus"].strip(),
                "cameraPurpose": shot["cameraPurpose"].strip(),
                "motifIds": [value for value in motif_refs if value in motif_ids],
                "gapAfterAllocation": allocation if position + 1 < len(scene_segments) else "none",
                "outlineStatus": "ready",
            }
        )
    return {"motifs": motifs, "shots": normalized}


def _placeholder_shot() -> dict[str, Any]:
    return {
        "shotType": "empty",
        "intent": "（本场景段大纲生成失败，请重新生成该段）",
        "requiredCharacterIds": [],
        "characterAction": "",
        "emotionalFocus": "",
        "cameraPurpose": "",
        "motifIds": [],
        "gapAfterAllocation": "none",
        "outlineStatus": "failed",
    }


def _assign_scene_segments(segments: list[dict[str, Any]], scenes: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """把结构段就近并入相邻歌词场景：间奏归后段开头，前奏归首段，尾奏归末段。"""
    scene_groups: list[list[dict[str, Any]]] = [[] for _ in scenes]
    pending_structural: list[dict[str, Any]] = []
    lyric_order = 0
    for segment in segments:
        if segment.get("segmentType") in STRUCTURAL_TYPES:
            pending_structural.append(segment)
            continue
        scene_position = next(position for position, scene in enumerate(scenes) if scene["lineStart"] <= lyric_order <= scene["lineEnd"])
        scene_groups[scene_position].extend(pending_structural)
        pending_structural = []
        scene_groups[scene_position].append(segment)
        lyric_order += 1
    scene_groups[-1].extend(pending_structural)
    return scene_groups


def finalize_shot_durations(shots: list[dict[str, Any]], segments: list[dict[str, Any]]) -> None:
    for index, shot in enumerate(shots):
        start, end = float(segments[index].get("start") or 0), float(segments[index].get("end") or 0)
        gap_before = round(max(0.0, start - float(segments[index - 1].get("end") or start)), 2) if index else 0.0
        gap_after = round(max(0.0, float(segments[index + 1].get("start") or end) - end), 2) if index + 1 < len(segments) else 0.0
        source_duration = round(max(0.0, end - start), 2)
        assigned_before = gap_before if index and shots[index - 1]["gapAfterAllocation"] == "next" and gap_before <= 2 else 0.0
        assigned_after = gap_after if shot["gapAfterAllocation"] == "current" and gap_after <= 2 else 0.0
        shot.update(
            sourceDuration=source_duration,
            gapBefore=gap_before,
            gapAfter=gap_after,
            materialDuration=round(source_duration + assigned_before + assigned_after, 2),
        )
        shot["generationDuration"] = normalize_video_duration(shot["materialDuration"])


async def _plan_ass_scenes(
    client: AsyncOpenAI,
    *,
    lyric_lines: list[dict[str, Any]],
    structural_notes: list[str],
    emotion: dict[str, Any],
    selected_humans: list[dict[str, Any]],
    extra_requirement: str,
    expected_scenes: int,
    usage_records: list[dict[str, Any]],
) -> dict[str, Any]:
    system_prompt = await get_prompt("ass.scene_plan.system")
    rules_prompt = await get_prompt("ass.scene_plan.rules")
    suffix_prompt = await get_prompt("common.pure_json_suffix")
    retry_prompt = await get_prompt("ass.scene_plan.retry_user")
    system = system_prompt.render(expected_scenes=expected_scenes)
    payload = {
        "songEmotion": emotion,
        "lyricLines": lyric_lines,
        "structuralSegments": structural_notes,
        "selectedCharacters": selected_humans,
        "overallRequirement": extra_requirement,
        "rules": rules_prompt.render_json(),
        "schema": {
            "globalVisual": {
                "visualStyle": "全片视觉风格",
                "colorPalette": "主色、辅色和避免色",
                "lighting": "统一光线规则",
                "weather": "统一天气",
                "timeOfDay": "统一或合理推进的时间",
                "continuityRules": ["人物面部与身份全片一致", "同一大场景内服装一致、切换大场景必须换装", "空间移动必须可解释"],
            },
            "scenes": [
                {
                    "lineStart": 0,
                    "lineEnd": 7,
                    "locationName": "明确地点",
                    "mood": "场景意境",
                    "emotion": "情绪状态",
                    "visualTone": "视觉基调",
                    "narrativePurpose": "叙事功能",
                    "wardrobeByCharacter": {role_id: "该人物在本大场景的完整服装、鞋履与配饰" for role_id in [item["id"] for item in selected_humans]},
                }
            ],
        },
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + suffix_prompt.render()},
    ]
    last_error: Exception | None = None
    for attempt in range(3):
        operation = "ass_scene_plan" if attempt == 0 else "ass_scene_plan_retry"
        try:
            text = await _call(client, messages, 2500, usage_records=usage_records, operation=operation, prompt_key=system_prompt.key, prompt_version=system_prompt.version)
        except Exception as exc:
            # API 层错误（网络、4xx/5xx）携带留痕记录后中止：重试只针对结构检查失败
            raise StoryboardPromptError(str(exc), usage_records=usage_records) from exc
        try:
            return _check_scene_plan(_extract_json(text), lyric_count=len(lyric_lines), expected_scenes=expected_scenes, role_ids=[item["id"] for item in selected_humans])
        except ValueError as exc:
            last_error = exc
            await log_background_error(
                path=f"/tasks/ass_scene_plan/{operation}",
                status_code=502,
                error_type="LLMParseError",
                message=f"场景规划第{attempt + 1}次解析失败：{exc}",
                traceback_text=text[:2000],
            )
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": retry_prompt.render(error=exc, expected_scenes=expected_scenes, last_line=len(lyric_lines) - 1),
                }
            )
    raise StoryboardPromptError(str(last_error), usage_records=usage_records)


async def _generate_scene_shots(
    client: AsyncOpenAI,
    *,
    scene: dict[str, Any],
    scene_segments: list[dict[str, Any]],
    global_visual: dict[str, Any],
    emotion: dict[str, Any],
    selected_humans: list[dict[str, Any]],
    extra_requirement: str,
    scene_index: int,
    role_ids: list[str],
    lyric_total: int,
    usage_records: list[dict[str, Any]],
) -> dict[str, Any]:
    system_prompt = await get_prompt("ass.scene_shots.system")
    rules_prompt = await get_prompt("ass.scene_shots.rules")
    suffix_prompt = await get_prompt("common.pure_json_suffix")
    retry_prompt = await get_prompt("ass.scene_shots.retry_user")
    system = system_prompt.render()
    segment_items = []
    for position, segment in enumerate(scene_segments):
        gap_after = 0.0
        if position + 1 < len(scene_segments):
            gap_after = round(max(0.0, float(scene_segments[position + 1].get("start") or 0) - float(segment.get("end") or 0)), 2)
        segment_items.append(
            {
                "index": position,
                "segmentType": segment.get("segmentType", "lyric"),
                "timelineLabel": segment.get("timelineLabel") or segment.get("lyrics", ""),
                "lyrics": segment.get("lyrics", ""),
                "durationSeconds": round(max(0.0, float(segment.get("end") or 0) - float(segment.get("start") or 0)), 2),
                "gapAfterSeconds": gap_after,
            }
        )
    payload = {
        "songEmotion": emotion,
        "globalVisual": global_visual,
        "sceneContext": {
            **{key: scene[key] for key in ("locationName", "mood", "emotion", "visualTone", "narrativePurpose")},
            "wardrobeByCharacter": scene.get("wardrobeByCharacter") or {},
        },
        "sceneSegments": segment_items,
        "selectedCharacters": selected_humans,
        "overallRequirement": extra_requirement,
        "rules": rules_prompt.render_json(segment_count=len(scene_segments), empty_ratio_rule=_empty_ratio_rule(lyric_total)),
        "schema": {
            "motifs": [{"id": "motif-id", "name": "视觉母题", "meaning": "象征含义", "maxAppearances": 2}],
            "shots": [
                {
                    "index": 0,
                    "shotType": "empty | character",
                    "intent": "本镜叙事意图",
                    "requiredCharacterIds": role_ids,
                    "characterAction": "人物镜写具体动作；空镜写无人物及环境变化",
                    "emotionalFocus": "本镜情绪重点",
                    "cameraPurpose": "景别与运镜服务的叙事目的",
                    "motifIds": [],
                    "gapAfterAllocation": "current | next | none",
                }
            ],
        },
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + suffix_prompt.render()},
    ]
    base = len(usage_records)
    last_error: Exception | None = None
    for attempt in range(3):
        operation = f"ass_scene_segment_{scene_index + 1}" if attempt == 0 else f"ass_scene_segment_{scene_index + 1}_retry"
        try:
            text = await _call(client, messages, 3000, usage_records=usage_records, operation=operation, prompt_key=system_prompt.key, prompt_version=system_prompt.version)
        except Exception as exc:
            for record in usage_records[base:]:
                record["operation"] = f"{record['operation']}_failed"
            raise StoryboardPromptError(str(exc), usage_records=usage_records[base:]) from exc
        try:
            return _check_segment_body(_extract_json(text), segment_count=len(scene_segments), role_ids=role_ids, scene_index=scene_index, scene_segments=scene_segments)
        except ValueError as exc:
            last_error = exc
            await log_background_error(
                path=f"/tasks/ass_scene_segment/{operation}",
                status_code=502,
                error_type="LLMParseError",
                message=f"场景段{scene_index + 1}第{attempt + 1}次解析失败：{exc}",
                traceback_text=text[:2000],
            )
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": retry_prompt.render(error=exc)})
    for record in usage_records[base:]:
        record["operation"] = f"{record['operation']}_failed"
    raise StoryboardPromptError(str(last_error), usage_records=usage_records[base:])


async def generate_ass_story_outline(
    *,
    segments: list[dict[str, Any]],
    emotion: dict[str, Any],
    selected_humans: list[dict[str, Any]],
    extra_requirement: str,
    on_progress: ProgressCallback | None = None,
) -> dict[str, Any]:
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置")
    role_ids = [item["id"] for item in selected_humans]
    lyric_only = [segment for segment in segments if segment.get("segmentType", "lyric") == "lyric"]
    lyric_lines = [{"line": order, "lyrics": segment.get("lyrics", ""), "start": segment.get("start"), "end": segment.get("end")} for order, segment in enumerate(lyric_only)]
    structural_notes: list[str] = []
    lyric_seen = 0
    for segment in segments:
        if segment.get("segmentType", "lyric") == "lyric":
            lyric_seen += 1
            continue
        label = segment.get("timelineLabel") or segment.get("segmentType", "")
        duration = round(max(0.0, float(segment.get("end") or 0) - float(segment.get("start") or 0)), 2)
        position = "歌曲开头" if lyric_seen == 0 else (f"第 {lyric_seen} 句之后" if lyric_seen < len(lyric_only) else "全曲末尾")
        structural_notes.append(f"{position}有 {duration} 秒的{label}（无人空镜素材）")
    lyric_count = len(lyric_lines)
    expected_scenes = 5 if lyric_count >= 15 else (4 if lyric_count >= 9 else max(2, min(3, lyric_count)))
    client, usage_records = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url), []
    if on_progress:
        await on_progress({"phase": "planning", "segmentsDone": 0, "segmentsTotal": 0})
    plan = await _plan_ass_scenes(
        client,
        lyric_lines=lyric_lines,
        structural_notes=structural_notes,
        emotion=emotion,
        selected_humans=selected_humans,
        extra_requirement=extra_requirement,
        expected_scenes=expected_scenes,
        usage_records=usage_records,
    )
    scenes = [{**scene, "locationId": f"loc-{position + 1}"} for position, scene in enumerate(plan["scenes"])]
    scene_groups = _assign_scene_segments(segments, scenes)
    progress = {"phase": "segments", "segmentsDone": 0, "segmentsTotal": len(scenes)}
    if on_progress:
        await on_progress(dict(progress))

    async def run_scene(position: int, scene: dict[str, Any]) -> dict[str, Any]:
        try:
            return await _generate_scene_shots(
                client,
                scene=scene,
                scene_segments=scene_groups[position],
                global_visual=plan["globalVisual"],
                emotion=emotion,
                selected_humans=selected_humans,
                extra_requirement=extra_requirement,
                scene_index=position,
                role_ids=role_ids,
                lyric_total=lyric_count,
                usage_records=usage_records,
            )
        finally:
            progress["segmentsDone"] += 1
            if on_progress:
                await on_progress(dict(progress))

    results = await asyncio.gather(*(run_scene(position, scene) for position, scene in enumerate(scenes)), return_exceptions=True)
    all_shots, all_motifs, failed_segments = [], [], []
    for position, result in enumerate(results):
        if isinstance(result, Exception):
            failed_segments.append({"sceneIndex": position, "locationName": scenes[position]["locationName"], "error": str(result)[:500]})
            segment_shots = [_placeholder_shot() for _ in scene_groups[position]]
        else:
            segment_shots = result["shots"]
            all_motifs.extend(result["motifs"])
        for local_index, shot in enumerate(segment_shots):
            shot.update(
                index=len(all_shots),
                locationId=scenes[position]["locationId"],
                locationChange=local_index == 0,
                sceneIndex=position,
                wardrobeByCharacter=scenes[position]["wardrobeByCharacter"],
            )
            all_shots.append(shot)
    finalize_shot_durations(all_shots, segments)
    return {
        "globalVisual": plan["globalVisual"],
        "locations": [{"id": scene["locationId"], "name": scene["locationName"], "purpose": scene["narrativePurpose"]} for scene in scenes],
        "motifs": all_motifs,
        "shots": all_shots,
        "scenePlan": [
            {
                "sceneIndex": position,
                "locationId": scene["locationId"],
                "lineStart": scene["lineStart"],
                "lineEnd": scene["lineEnd"],
                **{key: scene[key] for key in ("locationName", "mood", "emotion", "visualTone", "narrativePurpose", "wardrobeByCharacter")},
            }
            for position, scene in enumerate(scenes)
        ],
        "failedSegments": failed_segments,
        "usageRecords": usage_records,
        "usage": _sum_usage(usage_records),
        "requestId": usage_records[-1].get("requestId") if usage_records else None,
    }


async def regenerate_ass_scene_segment(
    *,
    segments: list[dict[str, Any]],
    scene_plan: list[dict[str, Any]],
    scene_index: int,
    global_visual: dict[str, Any],
    emotion: dict[str, Any],
    selected_humans: list[dict[str, Any]],
    extra_requirement: str,
) -> dict[str, Any]:
    """段级重试：保留第一轮场景规划，仅重跑指定场景段的第二轮生成。"""
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置")
    if not 0 <= scene_index < len(scene_plan):
        raise ValueError("场景段序号超出范围")
    role_ids = [item["id"] for item in selected_humans]
    lyric_total = sum(1 for segment in segments if segment.get("segmentType", "lyric") == "lyric")
    scene_groups = _assign_scene_segments(segments, scene_plan)
    client, usage_records = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url), []
    result = await _generate_scene_shots(
        client,
        scene=scene_plan[scene_index],
        scene_segments=scene_groups[scene_index],
        global_visual=global_visual,
        emotion=emotion,
        selected_humans=selected_humans,
        extra_requirement=extra_requirement,
        scene_index=scene_index,
        role_ids=role_ids,
        lyric_total=lyric_total,
        usage_records=usage_records,
    )
    shots = []
    for local_index, shot in enumerate(result["shots"]):
        shot.update(
            locationId=scene_plan[scene_index]["locationId"],
            locationChange=local_index == 0,
            sceneIndex=scene_index,
            wardrobeByCharacter=scene_plan[scene_index].get("wardrobeByCharacter") or {},
        )
        shots.append(shot)
    return {
        "shots": shots,
        "motifs": result["motifs"],
        "shotStart": sum(len(group) for group in scene_groups[:scene_index]),
        "shotCount": len(shots),
        "usageRecords": usage_records,
        "usage": _sum_usage(usage_records),
        "requestId": usage_records[-1].get("requestId") if usage_records else None,
    }


def _usage_dict(response: Any) -> dict[str, Any]:
    return response.usage.model_dump(mode="json") if response.usage else {}


def _sum_usage(records: list[dict[str, Any]]) -> dict[str, int]:
    def value(usage: dict[str, Any], *keys: str) -> int:
        return next((int(usage[key] or 0) for key in keys if key in usage), 0)

    return {
        "input_tokens": sum(value(item.get("usage") or {}, "input_tokens", "prompt_tokens") for item in records),
        "output_tokens": sum(value(item.get("usage") or {}, "output_tokens", "completion_tokens") for item in records),
    }


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    # 1) 尝试从 ``` 围栏中提取
    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, re.DOTALL | re.IGNORECASE)
    if fence_match:
        cleaned = fence_match.group(1).strip()
    # 2) 找到第一个 { 或 [，从那里开始解析
    start = next((i for i, ch in enumerate(cleaned) if ch in "{["), 0)
    if start > 0:
        cleaned = cleaned[start:]
    decoder = json.JSONDecoder()
    last_error = None
    while cleaned:
        try:
            value, end = decoder.raw_decode(cleaned)
        except json.JSONDecodeError as exc:
            last_error = exc
            # 跳过当前字符重试（处理 LLM 在 JSON 前插了非 JSON 文本的情况）
            cleaned = cleaned[1:]
            continue
        # JSON 解析成功即可接受，忽略后面的额外文字
        if not isinstance(value, dict):
            raise ValueError("模型返回值不是 JSON 对象")
        return value
    if last_error:
        raise ValueError("模型没有返回可解析的 JSON 对象") from last_error
    raise ValueError("模型没有返回可解析的 JSON 对象")


def _validate(body: dict[str, Any], *, source: str, current: dict[str, Any], allowed_humans: list[dict[str, Any]]) -> dict[str, Any]:
    if set(body) != {"scenePrompt", "shotPrompt", "digitalHumanIds"}:
        raise ValueError("模型返回字段必须严格为 scenePrompt、shotPrompt、digitalHumanIds")
    scene_prompt, shot_prompt, role_ids = body["scenePrompt"], body["shotPrompt"], body["digitalHumanIds"]
    if not isinstance(scene_prompt, str) or not scene_prompt.strip() or not isinstance(shot_prompt, str) or not shot_prompt.strip():
        raise ValueError("scenePrompt 和 shotPrompt 必须是非空字符串")
    if not isinstance(role_ids, list) or not all(isinstance(value, str) for value in role_ids):
        raise ValueError("digitalHumanIds 必须是字符串数组")
    if len(role_ids) != len(set(role_ids)):
        raise ValueError("digitalHumanIds 不能包含重复角色")
    allowed_ids = {item["id"] for item in allowed_humans}
    unknown = set(role_ids) - allowed_ids
    if unknown:
        raise ValueError(f"模型返回了不可用角色：{sorted(unknown)}")
    planned = current.get("plannedDigitalHumanIds") or []
    if role_ids != planned:
        raise ValueError("模型返回人物顺序或集合与本镜预分配人物不一致")
    return {"scenePrompt": scene_prompt.strip(), "shotPrompt": shot_prompt.strip(), "digitalHumanIds": role_ids}


async def _call(
    client: AsyncOpenAI,
    messages: list[dict[str, str]],
    max_tokens: int,
    *,
    usage_records: list[dict[str, Any]],
    operation: str,
    prompt_key: str = "",
    prompt_version: int = 0,
) -> str:
    """发起一次 LLM 调用并留痕：无论成功失败都向 usage_records 追加记录，
    携带请求消息快照（调用时点，后续重试追加的消息不会污染）、返回原文、耗时与用量。"""
    snapshot = [dict(message) for message in messages]
    started = time.perf_counter()
    try:
        response = await client.chat.completions.create(model=settings.llm_model, messages=messages, temperature=0.2, max_tokens=max_tokens)
    except Exception as exc:
        usage_records.append(
            {
                "operation": operation,
                "status": "error",
                "error": str(exc)[:2000],
                "durationMs": round((time.perf_counter() - started) * 1000),
                "requestMessages": snapshot,
                "responseText": "",
                "usage": {},
                "requestId": getattr(exc, "request_id", None),
                "promptKey": prompt_key,
                "promptVersion": prompt_version,
            }
        )
        await log_background_error(
            path=f"/llm/{operation}",
            status_code=502,
            error_type="LLMCallError",
            message=f"LLM 调用失败（{operation}）：{exc}",
        )
        raise
    text = response.choices[0].message.content or ""
    usage_records.append(
        {
            "operation": operation,
            "status": "ok",
            "durationMs": round((time.perf_counter() - started) * 1000),
            "requestMessages": snapshot,
            "responseText": text,
            "usage": _usage_dict(response),
            "requestId": getattr(response, "id", None),
            "promptKey": prompt_key,
            "promptVersion": prompt_version,
        }
    )
    return text


async def generate_storyboard_line(*, source: str, current: dict[str, Any], full_context: dict[str, Any], allowed_humans: list[dict[str, Any]]) -> dict[str, Any]:
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置")
    planned = current.get("plannedDigitalHumanIds") or []
    # KV-cache 前缀稳定化：payload 中任务级静态字段（source/globalContext/allowedCharacters/outputSchema/requirements）全部前置且
    # 不含逐句差异文本，逐句变化的 currentShot 与 roleConstraint 固定后置；同任务 N 次逐句调用的 prompt 前缀字节级一致，
    # 让供应商侧前缀缓存可命中（cachedInputTokens > 0），降低时延与成本。
    system_prompt = await get_prompt("storyboard_line.system")
    requirements_prompt = await get_prompt("storyboard_line.requirements")
    role_constraint_prompt = await get_prompt("storyboard_line.role_constraint")
    repair_system_prompt = await get_prompt("storyboard_line.repair.system")
    suffix_prompt = await get_prompt("common.pure_json_suffix")
    # DB 已发布版本用 prompt-v{N} 标注；内置兜底沿用 PROMPT_VERSION 常量，保持与旧行为一致。
    version_label = f"prompt-v{system_prompt.version}" if system_prompt.source == "db" else PROMPT_VERSION
    role_constraint = role_constraint_prompt.render(planned_ids=json.dumps(planned, ensure_ascii=False))
    system = system_prompt.render(prompt_version=version_label, schema_version=SCHEMA_VERSION)
    payload = {
        "source": source,
        "globalContext": full_context,
        "allowedCharacters": allowed_humans,
        "outputSchema": {"scenePrompt": "string", "shotPrompt": "string", "digitalHumanIds": ["allowed character id"]},
        "requirements": requirements_prompt.render_json(),
        "currentShot": current,
        "roleConstraint": role_constraint,
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + suffix_prompt.render()},
    ]
    client, usage_records = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url), []
    try:
        text = await _call(client, messages, 1400, usage_records=usage_records, operation="storyboard_line", prompt_key=system_prompt.key, prompt_version=system_prompt.version)
    except Exception as exc:
        raise StoryboardPromptError(str(exc), usage_records=usage_records) from exc
    try:
        result = _validate(_extract_json(text), source=source, current=current, allowed_humans=allowed_humans)
    except ValueError as first_error:
        await log_background_error(
            path="/api/tasks/storyboard-lines/generate",
            status_code=502,
            error_type="LLMParseError",
            message=f"逐句提示词初次解析失败（将自动修复）：{first_error}",
            traceback_text=text[:2000],
        )
        repair = [
            {"role": "system", "content": repair_system_prompt.render()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "error": str(first_error),
                        "invalidOutput": text,
                        "allowedCharacterIds": [item["id"] for item in allowed_humans],
                        "requiredCharacterIds": planned,
                        "schema": payload["outputSchema"],
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        try:
            repaired = await _call(
                client,
                repair,
                1400,
                usage_records=usage_records,
                operation="storyboard_line_repair",
                prompt_key=repair_system_prompt.key,
                prompt_version=repair_system_prompt.version,
            )
        except Exception as exc:
            raise StoryboardPromptError(str(exc), usage_records=usage_records) from exc
        try:
            result = _validate(_extract_json(repaired), source=source, current=current, allowed_humans=allowed_humans)
        except Exception as exc:
            raise StoryboardPromptError(str(exc), usage_records=usage_records) from exc
    return {**result, "usage": _sum_usage(usage_records), "usageRecords": usage_records, "requestId": usage_records[-1].get("requestId")}


# ---------------------------------------------------------------------------
# 通用分镜大纲生成（无歌词，单轮 LLM 调用）
# ---------------------------------------------------------------------------


def _check_general_outline(body: dict[str, Any], *, expected_count: int, empty_count: int, character_count: int, role_ids: list[str]) -> dict[str, Any]:
    """通用分镜大纲的结构完整性检查。"""
    if set(body) != {"shots"}:
        raise ValueError("大纲必须严格只包含 shots 字段")
    shots = body["shots"]
    if not isinstance(shots, list) or len(shots) != expected_count:
        raise ValueError(f"shots 必须包含 {expected_count} 条镜头规划")
    allowed = set(role_ids)
    required_fields = {"index", "shotType", "outlineScene", "outlineShot", "requiredCharacterIds", "intent", "characterAction", "emotionalFocus", "cameraPurpose"}
    normalized = []
    for position, shot in enumerate(shots):
        if not isinstance(shot, dict) or set(shot) != required_fields:
            raise ValueError(f"每条镜头必须严格包含：{sorted(required_fields)}")
        shot_type = shot["shotType"]
        if shot_type not in {"empty", "character"}:
            raise ValueError("shotType 必须为 empty 或 character")
        for key in ("outlineScene", "outlineShot", "intent", "characterAction", "emotionalFocus", "cameraPurpose"):
            if not isinstance(shot[key], str) or not shot[key].strip():
                raise ValueError(f"{key} 必须是非空字符串")
        required = [value for value in shot["requiredCharacterIds"] if isinstance(value, str)] if isinstance(shot["requiredCharacterIds"], list) else []
        required = [value for value in required if value in allowed]
        if shot_type == "empty":
            required = []
        elif shot_type == "character" and not required:
            raise ValueError("人物镜必须包含至少一个已选人物")
        normalized.append(
            {
                "index": position,
                "shotType": shot_type,
                "outlineScene": shot["outlineScene"].strip(),
                "outlineShot": shot["outlineShot"].strip(),
                "requiredCharacterIds": required,
                "intent": shot["intent"].strip(),
                "characterAction": shot["characterAction"].strip(),
                "emotionalFocus": shot["emotionalFocus"].strip(),
                "cameraPurpose": shot["cameraPurpose"].strip(),
            }
        )
    actual_empty = sum(shot["shotType"] == "empty" for shot in normalized)
    actual_character = len(normalized) - actual_empty
    if actual_empty != empty_count or actual_character != character_count:
        raise ValueError(f"镜头类型配额不一致：要求空镜 {empty_count} 条、人物镜 {character_count} 条，实际为空镜 {actual_empty} 条、人物镜 {actual_character} 条")
    return {"shots": normalized}


async def generate_general_story_outline(
    *,
    config: dict[str, Any],
    selected_humans: list[dict[str, Any]],
    on_progress: ProgressCallback | None = None,
    call_override: LlmCallOverride | None = None,
) -> dict[str, Any]:
    """通用分镜大纲生成：单轮 LLM 调用，根据曲风/季节/人物/镜头数量规划完整 MV 分镜。"""
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置")
    empty_count: int = config.get("empty_shot_count", 0)
    character_count: int = config.get("character_shot_count", 0)
    expected_count = empty_count + character_count
    role_ids = [item["id"] for item in selected_humans]
    total_duration: float = config.get("total_duration", 0)
    if on_progress:
        await on_progress({"phase": "generating", "shotsDone": 0, "shotsTotal": expected_count})
    system_prompt = await get_prompt("general.story_outline.system")
    rules_prompt = await get_prompt("general.story_outline.rules")
    suffix_prompt = await get_prompt("common.pure_json_suffix")
    retry_prompt = await get_prompt("general.story_outline.retry_user")
    system = system_prompt.render()
    payload = {
        "config": {
            "genre": config.get("genre"),
            "secondaryCategory": config.get("secondary_category"),
            "tertiaryCategory": config.get("tertiary_category"),
            "season": config.get("season"),
            "gender": config.get("gender"),
            "ageGroup": config.get("age_group"),
            "visualStyle": config.get("visual_style"),
            "emptyShotCount": empty_count,
            "characterShotCount": character_count,
            "totalDuration": total_duration,
            "extraRequirement": config.get("extra_requirement", ""),
            "overallPrompt": config.get("overall_prompt", ""),
        },
        "selectedCharacters": selected_humans,
        "rules": rules_prompt.render_json(expected_count=expected_count, empty_count=empty_count, character_count=character_count),
        "schema": {
            "shots": [
                {
                    "index": 0,
                    "shotType": "empty | character",
                    "outlineScene": "场景描述（环境、时间、光线、色彩、美术风格）",
                    "outlineShot": "镜头描述（人物表演、构图、景别、运镜、镜头内节奏）",
                    "requiredCharacterIds": role_ids,
                    "intent": "叙事意图",
                    "characterAction": "人物镜写具体动作；空镜写环境变化",
                    "emotionalFocus": "情绪重点",
                    "cameraPurpose": "景别与运镜目的",
                }
            ]
        },
    }
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + suffix_prompt.render()},
    ]
    client, usage_records = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url), []
    last_error: Exception | None = None
    for attempt in range(3):
        operation = "general_story_outline" if attempt == 0 else "general_story_outline_retry"
        if on_progress and attempt > 0:
            await on_progress({"phase": "retry", "shotsDone": 0, "shotsTotal": expected_count, "attempt": attempt + 1})
        try:
            call = call_override or _call
            text = await call(client, messages, 4000, usage_records=usage_records, operation=operation, prompt_key=system_prompt.key, prompt_version=system_prompt.version)
        except Exception as exc:
            raise StoryboardPromptError(str(exc), usage_records=usage_records) from exc
        try:
            return {
                "shots": _check_general_outline(
                    _extract_json(text),
                    expected_count=expected_count,
                    empty_count=empty_count,
                    character_count=character_count,
                    role_ids=role_ids,
                )["shots"],
                "usageRecords": usage_records,
                "usage": _sum_usage(usage_records),
                "requestId": usage_records[-1].get("requestId") if usage_records else None,
            }
        except ValueError as exc:
            last_error = exc
            await log_background_error(
                path=f"/tasks/general_story_outline/{operation}",
                status_code=502,
                error_type="LLMParseError",
                message=f"通用分镜大纲第{attempt + 1}次解析失败：{exc}",
                traceback_text=text[:2000],
            )
            messages.append({"role": "assistant", "content": text})
            messages.append(
                {
                    "role": "user",
                    "content": retry_prompt.render(error=exc, expected_count=expected_count, empty_count=empty_count, character_count=character_count),
                }
            )
    raise StoryboardPromptError(str(last_error), usage_records=usage_records)
