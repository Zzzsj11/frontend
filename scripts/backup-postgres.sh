#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; out="${BACKUP_DIR:-$root/backups}"; mkdir -p "$out"
file="$out/mvagent-$(date -u +%Y%m%dT%H%M%SZ).dump"
cd "$root"; docker compose exec -T postgres sh -lc 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$file"
if command -v sha256sum >/dev/null; then sha256sum "$file" > "$file.sha256"; else shasum -a 256 "$file" > "$file.sha256"; fi
find "$out" -type f \( -name 'mvagent-*.dump' -o -name 'mvagent-*.dump.sha256' \) -mtime +30 -delete
echo "$file"
