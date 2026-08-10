#!/usr/bin/env bash
set -euo pipefail
file="${1:?usage: scripts/restore-postgres.sh BACKUP.dump}"; test -f "$file"
test "${CONFIRM_RESTORE:-}" = "RESTORE" || { echo "set CONFIRM_RESTORE=RESTORE"; exit 1; }
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
docker compose exec -T postgres sh -lc 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists' < "$file"
