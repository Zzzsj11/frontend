#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

env_name="${DEPLOY_ENV:-production}"
env_file=".env.${env_name}"
test -f "$env_file" || { echo "missing $env_file"; exit 1; }
test -z "$(git status --porcelain)" || { echo "working tree must be clean"; exit 1; }

sha="$(git rev-parse HEAD)"
version="git-${sha}"
export RELEASE_VERSION="$version"

echo "building immutable local images for $version"
docker compose \
  --env-file "$env_file" \
  -f docker-compose.yml \
  -f docker-compose.local-release.yml \
  build frontend backend

echo "deploying $version without a remote registry pull"
DEPLOY_ENV="$env_name" DEPLOY_SKIP_PULL=1 ./scripts/deploy.sh "$version"
