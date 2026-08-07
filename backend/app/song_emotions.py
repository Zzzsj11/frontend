from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SOURCE = Path(__file__).with_name("data") / "song_emotions.json"
_DOCUMENT: dict[str, Any] = json.loads(_SOURCE.read_text(encoding="utf-8"))
SONG_EMOTIONS: dict[str, dict[str, Any]] = _DOCUMENT["歌曲"]
