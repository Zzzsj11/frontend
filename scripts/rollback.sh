#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
version="${1:-$(cat .previous-version 2>/dev/null || true)}"; test -n "$version" || { echo "no rollback version"; exit 1; }
export RUN_MIGRATIONS=0
exec "$root/scripts/deploy.sh" "$version"
