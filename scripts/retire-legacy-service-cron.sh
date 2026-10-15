#!/usr/bin/env bash
# Remove only the retired supplier asset registration job; preserve other maintenance.
set -euo pipefail
if command -v crontab >/dev/null 2>&1; then
  current="$(crontab -l 2>/dev/null || true)"
  cleaned="$(printf '%s\n' "$current" | sed '/sync-digital-human-assets\.sh/d; /ensure_asset_avatars\.py/d')"
  if [[ "$current" != "$cleaned" ]]; then
    backup="${MAINTENANCE_DATA_DIR:-/var/lib/docker/mv-agent-maintenance}/backups/retired-asset-cron"
    install -d -m 700 "$backup"
    previous="$backup/crontab-$(date -u +%Y%m%dT%H%M%SZ).before"
    (umask 077; printf '%s\n' "$current" > "$previous")
    printf '%s\n' "$cleaned" | crontab -
    echo "removed retired supplier asset registration cron"
  fi
fi
