from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI

from .config import settings


TIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})[.](\d{2})$")
TAG_RE = re.compile(r"{[^}]*}")


@dataclass
class AssCue:
    start: float
    end: float
    text: str


def decode_ass(content: bytes) -> tuple[str, str]:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("ASS 文件编码不受支持，仅支持 UTF-8、UTF-8 BOM 或 GB18030")


def parse_time(value: str) -> float:
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"非法 ASS 时间戳：{value}")
    hour, minute, second, centisecond = map(int, match.groups())
    if minute >= 60 or second >= 60:
        raise ValueError(f"非法 ASS 时间范围：{value}")
    return hour * 3600 + minute * 60 + second + centisecond / 100


def parse_ass(content: bytes) -> tuple[list[AssCue], str]:
    text, encoding = decode_ass(content)
    for section in ("[Script Info]", "[V4+ Styles]", "[Events]"):
        if section not in text:
            raise ValueError(f"ASS 文件缺少必要区段：{section}")
    cues: list[AssCue] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(":", 1)[1].lstrip().split(",", 9)
        if len(fields) != 10:
            raise ValueError(f"ASS 第 {line_number} 行 Dialogue 字段数量不是 10")
        start, end = parse_time(fields[1]), parse_time(fields[2])
        lyric = TAG_RE.sub("", fields[9]).replace(r"\N", " ").strip()
        if end <= start:
            raise ValueError(f"ASS 第 {line_number} 行结束时间不晚于开始时间")
        if lyric:
            cues.append(AssCue(start, end, lyric))
    if not cues:
        raise ValueError("ASS 文件中没有有效 Dialogue 歌词")
    if any(current.start < previous.start for previous, current in zip(cues, cues[1:])):
        raise ValueError("ASS Dialogue 时间轴没有按升序排列")
    return cues, encoding


def group_cues(cues: list[AssCue], max_duration: float = 10.0) -> list[dict[str, Any]]:
    groups: list[list[AssCue]] = []
    current: list[AssCue] = []
    for cue in cues:
        if current and (cue.start - current[-1].end > 1.5 or cue.end - current[0].start > max_duration):
            groups.append(current)
            current = []
        current.append(cue)
    if current:
        groups.append(current)
    return [
        {
            "index": index,
            "start": round(group[0].start, 2),
            "end": round(group[-1].end, 2),
            "lyrics": " ".join(item.text for item in group),
        }
        for index, group in enumerate(groups)
    ]


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.IGNORECASE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("模型没有返回 JSON")
        return json.loads(match.group(0))


async def generate_ass_storyboard(
    *, song_id: str, content: bytes, digital_human_ids: list[str], extra_requirement: str
) -> dict[str, Any]:
    cues, encoding = parse_ass(content)
    segments = group_cues(cues)
    if not settings.llm_api_key:
        raise RuntimeError("LLM_API_KEY 未配置")
    prompt = f"""你是专业 MV 分镜导演。请根据以下 ASS 歌词时间段生成完整分镜。
歌曲编号：{song_id}
角色 ID：{json.dumps(digital_human_ids, ensure_ascii=False)}
额外要求：{extra_requirement or '无'}

每个输入段必须且只能返回一个分镜，保持 index 一致。scenePrompt 描述环境、时间、光线与美术；shotPrompt 描述人物表演、构图、镜头运动、色调，并明确无字幕、无水印、无 Logo。没有角色 ID 时允许空镜头；有角色时可按顺序轮换。

仅返回 JSON：
{{"title":"ASS 分镜 · {song_id}","lines":[{{"index":0,"scenePrompt":"...","shotPrompt":"...","digitalHumanIds":[]}}]}}

输入时间段：
{json.dumps(segments, ensure_ascii=False)}
"""
    client = AsyncOpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": "严格输出可解析 JSON，不要输出 Markdown。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
        max_tokens=8000,
    )
    body = _extract_json(response.choices[0].message.content or "")
    generated = {int(item["index"]): item for item in body.get("lines", []) if "index" in item}
    if len(generated) != len(segments):
        raise ValueError(f"模型返回 {len(generated)} 个分镜，期望 {len(segments)} 个")
    lines = []
    for segment in segments:
        item = generated[segment["index"]]
        role_ids = [value for value in item.get("digitalHumanIds", []) if value in digital_human_ids]
        lines.append(
            {
                "lyrics": segment["lyrics"],
                "start": segment["start"],
                "end": segment["end"],
                "scenePrompt": str(item.get("scenePrompt", "")).strip(),
                "shotPrompt": str(item.get("shotPrompt", "")).strip(),
                "digitalHumanIds": role_ids,
            }
        )
    return {
        "title": str(body.get("title") or f"ASS 分镜 · {song_id}"),
        "cast": digital_human_ids,
        "lines": lines,
        "meta": {"encoding": encoding, "dialogues": len(cues), "segments": len(segments)},
    }
