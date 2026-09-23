"""Optional reviewed, versioned system-headshot seed overlay, shipped with its Alembic revision."""

import json
from pathlib import Path

_PATH = Path(__file__).with_name("headshot-assets.json")
HEADSHOT_ASSETS = json.loads(_PATH.read_text()) if _PATH.is_file() else {}
