#!/usr/bin/env bash
set -euo pipefail
project_dir="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
service=/etc/systemd/system/mv-agent-metrics.service
timer=/etc/systemd/system/mv-agent-metrics.timer
install -m 0644 /dev/stdin "$service" <<EOF
[Unit]
Description=MV Agent host and workload metrics sample
After=docker.service

[Service]
Type=oneshot
WorkingDirectory=$project_dir
ExecStart=$project_dir/scripts/collect-server-metrics.sh
Nice=10
IOSchedulingClass=idle
EOF
install -m 0644 /dev/stdin "$timer" <<'EOF'
[Unit]
Description=Collect MV Agent metrics every 30 seconds

[Timer]
OnBootSec=30s
OnUnitActiveSec=30s
AccuracySec=2s
Persistent=true

[Install]
WantedBy=timers.target
EOF
systemctl daemon-reload
systemctl enable --now mv-agent-metrics.timer
# systemd timer supersedes only the old minute-level metric cron; other maintenance jobs remain.
crontab -l 2>/dev/null | grep -v 'collect-server-metrics.sh.*# mv-agent-maintenance' | crontab - || true
systemctl list-timers mv-agent-metrics.timer --no-pager
