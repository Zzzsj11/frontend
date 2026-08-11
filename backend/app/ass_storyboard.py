from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

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


CN_NUMERALS = ("一", "二", "三", "四", "五", "六", "七", "八", "九", "十")
OUTRO_PLACEHOLDER_DURATION = 10.0


def _gap_durations(duration: float, max_duration: float) -> list[float]:
    """结构空档拆分：不超过 max_duration 一段；两倍以内拆两段（前段取整到秒、拿余数）；更长则按不超过 max_duration 均分多段。"""
    if duration <= max_duration:
        return [duration]
    if duration <= max_duration * 2:
        front = float(math.ceil(duration / 2))
        return [front, round(duration - front, 2)]
    count = math.ceil(duration / max_duration)
    span = duration / count
    return [round(span, 2)] * (count - 1) + [round(duration - span * (count - 1), 2)]


def group_cues(cues: list[AssCue], max_duration: float = 15.0) -> list[dict[str, Any]]:
    """每句歌词独立成镜；超过 2 秒的前奏、间奏拆成结构性空镜，末尾追加一个尾奏占位段。"""
    max_duration = min(15.0, max(4.0, max_duration or 15.0))
    segments: list[dict[str, Any]] = []

    def append_gap(start: float, end: float, segment_type: str) -> None:
        duration = round(end - start, 2)
        if duration <= 2:
            return
        parts = _gap_durations(duration, max_duration)
        label = {"intro": "前奏", "interlude": "间奏", "outro": "尾奏"}[segment_type]
        cursor = start
        for part_index, part_duration in enumerate(parts):
            part_end = round(end, 2) if part_index == len(parts) - 1 else round(cursor + part_duration, 2)
            part_label = label
            if len(parts) > 1:
                numeral = CN_NUMERALS[part_index] if part_index < len(CN_NUMERALS) else str(part_index + 1)
                part_label = f"{label}{numeral}"
            segments.append(
                {
                    "start": round(cursor, 2),
                    "end": part_end,
                    "lyrics": "",
                    "segmentType": segment_type,
                    "timelineLabel": part_label,
                }
            )
            cursor = part_end

    append_gap(0.0, cues[0].start, "intro")
    for index, cue in enumerate(cues):
        segments.append(
            {
                "start": round(cue.start, 2),
                "end": round(cue.end, 2),
                "lyrics": cue.text,
                "segmentType": "lyric",
                "timelineLabel": cue.text,
            }
        )
        if index + 1 < len(cues):
            append_gap(cue.end, cues[index + 1].start, "interlude")
    outro_start = round(cues[-1].end, 2)
    segments.append(
        {
            "start": outro_start,
            "end": round(outro_start + OUTRO_PLACEHOLDER_DURATION, 2),
            "lyrics": "",
            "segmentType": "outro",
            "timelineLabel": "尾奏",
        }
    )
    return [{"index": index, **segment} for index, segment in enumerate(segments)]
