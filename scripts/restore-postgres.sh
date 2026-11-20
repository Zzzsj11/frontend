#!/usr/bin/env bash
set -euo pipefail

# Shared with the scheduled verification. Resolve the caller's path before cd.
prepare_restore() {
  local input="${1:?a custom-format PostgreSQL dump is required}"
  test -f "$input"
  file="$(cd "$(dirname "$input")" && pwd)/$(basename "$input")"
  local expected actual
  expected="$(awk 'NR==1 {print $1}' "$file.sha256")"
  if command -v sha256sum >/dev/null; then actual="$(sha256sum < "$file")"; else actual="$(shasum -a 256 < "$file")"; fi
  [[ "$expected" =~ ^[0-9a-f]{64}$ && "$expected" == "${actual%% *}" ]] || { echo "backup checksum mismatch" >&2; return 1; }
  cd "$(dirname "${BASH_SOURCE[0]}")/.."
  compose=(docker compose -f docker-compose.yml)
  if [[ -f .env.production ]]; then
    if [[ -f .deployment/info.json ]]; then
      RELEASE_VERSION="$(python3 -c 'import json; print(json.load(open(".deployment/info.json"))["version"] or "")')"
    else
      RELEASE_VERSION="${RELEASE_VERSION:-$(cat .deployed-version 2>/dev/null || true)}"
      : "${RELEASE_VERSION:?set RELEASE_VERSION when restoring on a fresh server}"
    fi
    export RELEASE_VERSION
    compose+=(--env-file .env.production -f docker-compose.production.yml)
  else
    compose+=(-f docker-compose.local-build.yml)
  fi
}

verify_in_new_database() (
  local db count revision
  db="mvagent_restore_verify_$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
  db_exec() { "${compose[@]}" exec -T postgres sh -ec "$1" sh "$db"; }
  # Only the process whose CREATE DATABASE succeeded may drop that database.
  db_exec 'createdb -U "$POSTGRES_USER" "$1"'
  drop_verification_database() {
    db_exec 'dropdb -U "$POSTGRES_USER" "$1"' || { echo "failed to remove verification database $db" >&2; exit 1; }
  }
  trap drop_verification_database EXIT
  trap 'exit 130' INT
  trap 'exit 143' TERM
  db_exec 'pg_restore -U "$POSTGRES_USER" -d "$1" --exit-on-error --single-transaction' < "$file"
  count="$(db_exec 'psql -X -U "$POSTGRES_USER" -d "$1" -Atc "select count(*) from users"')"
  revision="$(db_exec 'psql -X -U "$POSTGRES_USER" -d "$1" -Atc "select version_num from alembic_version"')"
  [[ "$count" =~ ^[0-9]+$ && -n "$revision" ]] || { echo "missing user count or migration revision" >&2; exit 1; }
  echo "[PASS] backup restored in isolated database; users=$count revision=$revision"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  test "${CONFIRM_RESTORE:-}" = RESTORE || { echo "set CONFIRM_RESTORE=RESTORE" >&2; exit 1; }
  prepare_restore "${1:?usage: scripts/restore-postgres.sh BACKUP.dump}"
  verify_in_new_database
  "${compose[@]}" exec -T postgres sh -ec 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --clean --if-exists --exit-on-error --single-transaction' < "$file"
fi
