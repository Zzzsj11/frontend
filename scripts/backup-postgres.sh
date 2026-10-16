#!/usr/bin/env bash
set -euo pipefail
umask 077
root="$(cd "$(dirname "$0")/.." && pwd)"; out="${BACKUP_DIR:-$root/backups}"; mkdir -p "$out"
file="$out/mvagent-$(date -u +%Y%m%dT%H%M%SZ)-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:8])').dump"
cd "$root"
compose=(docker compose -f docker-compose.yml)
if [[ "${DEPLOY_ENV:-production}" == "production" && -f .env.production ]]; then
  export RELEASE_VERSION="${RELEASE_VERSION:-$(cat .deployed-version)}"
  compose+=(--env-file .env.production -f docker-compose.production.yml)
else
  compose+=(-f docker-compose.local-build.yml)
fi
trap 'rm -f "$file.partial"' EXIT
"${compose[@]}" exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$file.partial"
mv "$file.partial" "$file"
if command -v sha256sum >/dev/null; then sha256sum "$file" > "$file.sha256"; else shasum -a 256 "$file" > "$file.sha256"; fi
if [[ -n "${BACKUP_TOS_BUCKET:-}" ]]; then
  "$root/scripts/sync-backup-to-tos.sh" "$file"
else
  echo 'backup is local only: BACKUP_TOS_BUCKET is not configured' >&2
fi
find "$out" -type f \( -name 'mvagent-*.dump' -o -name 'mvagent-*.dump.sha256' \) -mtime +30 -delete
echo "$file"
