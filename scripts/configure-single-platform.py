#!/usr/bin/env python3
"""Retire direct supplier credentials from production configuration, with private backups."""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREFIXES = (
    "AIGC_",
    "CHAT_COMPLETIONS_",
    "CHAT_DEFAULT_",
    "YSEEAI_",
    "TOAPIS_",
    "RUNNINGHUB_",
    "BUSINESS_",
    "PROMPT_OPTIMIZER_GEMINI_",
    "PROMPT_OPTIMIZER_MINIMAX_",
    "IMAGE_API_",
    "VIDEO_API_",
    "KLING_",
    "MODEL_GATEWAY_",
)
LEGACY_KEYS = {"LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL"}
DEFAULTS = {
    "LLM_API_MODE": "openai",
    "LLM_CHANNEL": "all-in-one",
    "ALL_IN_ONE_LLM_MODEL": "gemini-3.8-flash-all-in-one",
    "GENERAL_OUTLINE_LLM_MODEL": "gemini-3.8-flash-all-in-one",
}


def main():
    if os.getenv("DEPLOY_ENV") != "production":
        raise SystemExit("This configuration migration is only for production deployment")
    runtime = ROOT / "backend/.runtime_secrets.env"
    if not runtime.is_file():
        raise SystemExit("Missing production runtime secrets file")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = Path(os.getenv("MAINTENANCE_DATA_DIR", "/var/lib/docker/mv-agent-maintenance")) / "backups" / ("single-platform-config-" + stamp)
    backup.mkdir(parents=True, mode=0o700)
    paths = [ROOT / "backend" / name for name in (".env", ".env.chat", ".runtime_secrets.env", ".provider_config.py")]
    paths.append(ROOT / ".env.production")
    for path in paths:
        if not path.is_file():
            continue
        old = path.read_text()
        retained = []
        removed = 0
        for line in old.splitlines():
            match = re.match(r"^\s*([A-Z][A-Z0-9_]*)\s*=", line)
            key = match.group(1) if match else ""
            if key in DEFAULTS or key in LEGACY_KEYS or key.startswith(PREFIXES):
                removed += 1
                continue
            retained.append(line)
        if path == runtime:
            retained.extend(key + "=" + value for key, value in DEFAULTS.items())
        new = "\n".join(retained) + "\n"
        if old != new:
            target = backup / ("root-" if path.parent == ROOT else "backend-")
            target = target.with_name(target.name + path.name.lstrip("."))
            shutil.copy2(path, target)
            target.chmod(0o600)
            temp = path.with_name(path.name + ".single-platform.tmp")
            temp.write_text(new)
            temp.chmod(0o600)
            temp.replace(path)
            print(f"updated {path.relative_to(ROOT)}: retired {removed} legacy/config override entries")
    print(f"private configuration backup: {backup}")


if __name__ == "__main__":
    main()
