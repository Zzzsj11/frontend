from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path


TIME_RE = re.compile(r"^(\d+):(\d{2}):(\d{2})[.](\d{2})$")


@dataclass
class ValidationResult:
    path: Path
    encoding: str
    dialogues: int
    first_start: float
    last_end: float


def decode_ass(path: Path) -> tuple[str, str]:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("不支持的文本编码，仅支持 UTF-8/UTF-8 BOM/GB18030")


def parse_time(value: str) -> float:
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"非法时间戳：{value}")
    hour, minute, second, centisecond = map(int, match.groups())
    if minute >= 60 or second >= 60:
        raise ValueError(f"非法时间范围：{value}")
    return hour * 3600 + minute * 60 + second + centisecond / 100


def validate(path: Path) -> ValidationResult:
    text, encoding = decode_ass(path)
    required = ("[Script Info]", "[V4+ Styles]", "[Events]")
    missing = [section for section in required if section not in text]
    if missing:
        raise ValueError(f"缺少区段：{', '.join(missing)}")

    event_format = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"
    if event_format not in text:
        raise ValueError("[Events] Format 字段不符合标准 ASS 格式")

    starts: list[float] = []
    ends: list[float] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.startswith("Dialogue:"):
            continue
        fields = line.split(":", 1)[1].lstrip().split(",", 9)
        if len(fields) != 10:
            raise ValueError(f"第 {line_number} 行 Dialogue 字段数量不是 10")
        start = parse_time(fields[1])
        end = parse_time(fields[2])
        if end <= start:
            raise ValueError(f"第 {line_number} 行结束时间不晚于开始时间")
        if not re.sub(r"{[^}]*}", "", fields[9]).strip():
            raise ValueError(f"第 {line_number} 行歌词为空")
        starts.append(start)
        ends.append(end)

    if not starts:
        raise ValueError("没有 Dialogue 行")
    if any(current < previous for previous, current in zip(starts, starts[1:])):
        raise ValueError("Dialogue 开始时间未按升序排列")

    return ValidationResult(path, encoding, len(starts), starts[0], ends[-1])


if __name__ == "__main__":
    failed = False
    for argument in sys.argv[1:]:
        target = Path(argument)
        try:
            result = validate(target)
            print(
                f"PASS {target.name}: encoding={result.encoding}, "
                f"dialogues={result.dialogues}, range={result.first_start:.2f}s-{result.last_end:.2f}s"
            )
        except ValueError as exc:
            failed = True
            print(f"FAIL {target.name}: {exc}", file=sys.stderr)
    raise SystemExit(1 if failed else 0)
