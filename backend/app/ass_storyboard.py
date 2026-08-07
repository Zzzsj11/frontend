from __future__ import annotations

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
