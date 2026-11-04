#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 scripts/local_runtime.py heads
python3 scripts/local_runtime.py migration
