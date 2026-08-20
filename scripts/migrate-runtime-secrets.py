#!/usr/bin/env python3
"""Consolidate legacy production secrets without printing values."""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXACT_SECRET_NAMES = {"JWT_SECRET", "POSTGRES_PASSWORD", "TOS_ACCESS_KEY_ID", "TOS_SECRET_ACCESS_KEY"}


def sensitive(name: str) -> bool:
    return name in EXACT_SECRET_NAMES or name.endswith(("_API_KEY", "_TOKEN", "_SECRET", "_PASSWORD"))


def env_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def provider_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    return {key: value for key, _, value in re.findall(r"(?m)^([A-Z][A-Z0-9_]*)\s*=\s*([\"'])(.*?)\2\s*$", path.read_text())}


def sanitize(path: Path) -> None:
    if not path.exists():
        return
    kept = []
    for raw in path.read_text().splitlines():
        stripped = raw.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped else ""
        if key and sensitive(key):
            continue
        kept.append(raw)
    path.write_text("\n".join(kept).rstrip() + "\n")
    path.chmod(0o600)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate sources without writing files")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    env_files = (root / ".env.production", root / "backend/.env")
    provider_file = root / "backend/.provider_config.py"
    runtime_file = root / "backend/.runtime_secrets.env"
    postgres_file = root / "backend/.postgres_password"
    values: dict[str, str] = {}
    for path in env_files:
        values.update({key: value for key, value in env_values(path).items() if sensitive(key) and value})
    # Preserve the provider configuration group as one atomic file so token,
    # endpoint and default model cannot drift during rotation.
    values.update({key: value for key, value in provider_values(provider_file).items() if value})
    missing = [name for name in ("JWT_SECRET", "POSTGRES_PASSWORD", "AIGC_TOKEN", "TOS_SECRET_ACCESS_KEY") if not values.get(name)]
    if missing:
        print("missing required secrets: " + ", ".join(missing), file=sys.stderr)
        return 1
    if args.check:
        print(f"ready to migrate {len(values)} configuration names; values were not printed")
        return 0
    runtime_file.write_text("".join(f"{key}={value}\n" for key, value in sorted(values.items())))
    runtime_file.chmod(0o600)
    postgres_file.write_text(values["POSTGRES_PASSWORD"])
    postgres_file.chmod(0o600)
    for path in env_files:
        sanitize(path)
    print(f"migrated {len(values)} secret names; values were not printed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
