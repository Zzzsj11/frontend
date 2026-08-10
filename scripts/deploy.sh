#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
version="${1:?usage: scripts/deploy.sh VERSION}"; env_name="${DEPLOY_ENV:-production}"
env_file=".env.${env_name}"; test -f "$env_file" || { echo "missing $env_file"; exit 1; }
previous="$(cat .deployed-version 2>/dev/null || true)"
printf '%s\n' "$previous" > .previous-version
export RELEASE_VERSION="$version"
docker compose --env-file "$env_file" -f docker-compose.yml -f "docker-compose.${env_name}.yml" pull
docker compose --env-file "$env_file" -f docker-compose.yml -f "docker-compose.${env_name}.yml" up -d --remove-orphans
for _ in {1..30}; do curl -fsS http://127.0.0.1:8000/api/health >/dev/null && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/api/health >/dev/null
printf '%s\n' "$version" > .deployed-version
echo "deployed $version ($env_name); previous=$previous"
