#!/usr/bin/env bash
set -euo pipefail
root="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$root"
release="$(cat .deployed-version 2>/dev/null || true)"
compose=(docker compose)
if [[ -f .env.production && -n "$release" ]]; then
  export RELEASE_VERSION="$release"
  compose+=(--env-file .env.production -f docker-compose.yml -f docker-compose.production.yml)
else
  compose+=(-f docker-compose.yml -f docker-compose.local-build.yml)
fi
python3 scripts/collect-server-metrics.py | "${compose[@]}" exec -T backend python /srv/mvagent/scripts/ingest_server_metrics.py
