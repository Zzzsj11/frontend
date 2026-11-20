#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
version="${1:---previous}"
export RUN_MIGRATIONS=0
exec "$root/scripts/deploy.sh" "$version"
