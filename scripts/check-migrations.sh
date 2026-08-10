#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
heads="$(.venv/bin/alembic heads | wc -l | tr -d ' ')"
test "$heads" = "1" || { echo "[FAIL] Alembic must have exactly one head"; exit 1; }
.venv/bin/alembic upgrade head
echo "[PASS] migrations have one head and upgrade successfully"
