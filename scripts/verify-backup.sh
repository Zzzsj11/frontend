#!/usr/bin/env bash
set -euo pipefail
file="${1:?usage: scripts/verify-backup.sh BACKUP.dump}"; test -f "$file"
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
compose=(docker compose -f docker-compose.yml)
if [[ -f .env.production ]]; then
  export RELEASE_VERSION="${RELEASE_VERSION:-$(cat .deployed-version)}"
  compose+=(--env-file .env.production -f docker-compose.production.yml)
else
  compose+=(-f docker-compose.local-build.yml)
fi
db="mvagent_restore_verify_$(date +%s)"
cleanup(){ "${compose[@]}" exec -T postgres sh -lc "dropdb -U \"\$POSTGRES_USER\" --if-exists '$db'" >/dev/null 2>&1 || true; }; trap cleanup EXIT
"${compose[@]}" exec -T postgres sh -lc "createdb -U \"\$POSTGRES_USER\" '$db'"
"${compose[@]}" exec -T postgres sh -lc "pg_restore -U \"\$POSTGRES_USER\" -d '$db' --exit-on-error" < "$file"
count="$("${compose[@]}" exec -T postgres sh -lc "psql -U \"\$POSTGRES_USER\" -d '$db' -Atc 'select count(*) from users'" | tr -d '\r')"
echo "[PASS] backup restored in isolated database; users=$count"
