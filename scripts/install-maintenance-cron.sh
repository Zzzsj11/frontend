#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; logs="${MAINTENANCE_LOG_DIR:-$root/logs}"; backups="${BACKUP_DIR:-$root/backups}"
mkdir -p "$logs" "$backups"
marker="# mv-agent-maintenance"
current="$(crontab -l 2>/dev/null | grep -v "$marker" || true)"
{
  printf '%s\n' "$current"
  printf '*/5 * * * * PROJECT_DIR=%q %q >> %q 2>&1 %s\n' "$root" "$root/scripts/online-health-check.sh" "$logs/health-cron.log" "$marker"
  if ! systemctl is-enabled mv-agent-metrics.timer >/dev/null 2>&1; then
    printf '* * * * * PROJECT_DIR=%q %q >> %q 2>&1 %s\n' "$root" "$root/scripts/collect-server-metrics.sh" "$logs/server-metrics-cron.log" "$marker"
  fi
  printf '15 3 * * * BACKUP_DIR=%q %q >> %q 2>&1 %s\n' "$backups" "$root/scripts/backup-postgres.sh" "$logs/backup-cron.log" "$marker"
  printf '15 4 * * 0 BACKUP_DIR=%q %q >> %q 2>&1 %s\n' "$backups" "$root/scripts/verify-latest-backup.sh" "$logs/backup-verify-cron.log" "$marker"
} | crontab -
echo "installed health, backup, restore verification, and metrics cron fallback (systemd timer preferred)"
