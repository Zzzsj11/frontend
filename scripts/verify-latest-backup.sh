#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
backup_dir="${BACKUP_DIR:-$root/backups}"
latest="$(find "$backup_dir" -maxdepth 1 -type f -name 'mvagent-*.dump' -print0 | xargs -0 ls -1t 2>/dev/null | head -1 || true)"
if [[ -z "$latest" ]]; then
  echo "no PostgreSQL backup found in $backup_dir" >&2
  exit 1
fi
"$root/scripts/verify-backup.sh" "$latest"
