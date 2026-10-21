#!/usr/bin/env python3
"""Retire direct supplier credentials from production configuration, with private backups."""

from __future__ import annotations

import base64
import secrets
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
    "TOS_REFERENCE_PREFIX": "mv/production/references",
    "TOS_VIDEO_ARCHIVE_PREFIX": "mv/production/videos",
    "LLM_API_MODE": "openai",
    "LLM_CHANNEL": "all-in-one",
    "ALL_IN_ONE_LLM_MODEL": "gemini-3.8-flash-all-in-one",
    "GENERAL_OUTLINE_LLM_MODEL": "gemini-3.8-flash-all-in-one",
}


def main():
    if os.getenv("DEPLOY_ENV") != "production":
        raise SystemExit("This configuration migration is only for production deployment")
    deploy_file = ROOT / ".env.production"
    deployment = dict(line.split("=", 1) for line in deploy_file.read_text().splitlines() if "=" in line and not line.startswith("#")) if deploy_file.is_file() else {}
    tier = os.getenv("DEPLOYMENT_TIER") or deployment.get("DEPLOYMENT_TIER", "production")
    if tier not in {"production", "test"}:
        raise SystemExit("DEPLOYMENT_TIER must be production or test")
    expected_domain = "mv-test.epaipix.com" if tier == "test" else "mv.epaipix.com"
    domain = os.getenv("TLS_DOMAIN") or deployment.get("TLS_DOMAIN", expected_domain)
    if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", domain):
        raise SystemExit("invalid TLS_DOMAIN")
    if domain != expected_domain:
        raise SystemExit("TLS_DOMAIN does not match DEPLOYMENT_TIER")
    defaults = dict(DEFAULTS)
    defaults["ALL_IN_ONE_BASE_URL"] = "https://mg-test.epaipix.com" if tier == "test" else "https://mg.epaipix.com"
    defaults["TOS_REFERENCE_PREFIX"] = f"mv/{tier}/references"
    defaults["TOS_VIDEO_ARCHIVE_PREFIX"] = f"mv/{tier}/videos"
    if os.getenv("DEPLOY_TLS") == "1":
        defaults["REFRESH_COOKIE_SECURE"] = "true"
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
            if key in defaults or key in LEGACY_KEYS or key.startswith(PREFIXES):
                removed += 1
                continue
            retained.append(line)
        if path == ROOT / ".env.production" and os.getenv("DEPLOY_TLS") == "1":
            retained = [line for line in retained if not line.startswith("APP_CORS_ORIGINS=")]
            retained.append("APP_CORS_ORIGINS=https://" + domain)
        if path == runtime:
            if not any(line.startswith("BACKUP_TOS_ENCRYPTION_KEY=") for line in retained):
                retained.append("BACKUP_TOS_ENCRYPTION_KEY=" + base64.b64encode(secrets.token_bytes(32)).decode())
            if not any(re.match(r"^\s*AGENT_TEST_USERNAMES\s*=", line) for line in retained):
                retained.append("AGENT_TEST_USERNAMES=dev01")
            retained.extend(key + "=" + value for key, value in defaults.items())
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
