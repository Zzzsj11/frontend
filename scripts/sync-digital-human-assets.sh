#!/usr/bin/env bash
set -euo pipefail

root="${PROJECT_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$root"
export RELEASE_VERSION="$(cat .deployed-version)"

docker compose --env-file .env.production \
  -f docker-compose.yml -f docker-compose.production.yml \
  exec -T backend python /srv/mvagent/scripts/ensure_asset_avatars.py
