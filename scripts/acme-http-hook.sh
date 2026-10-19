#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
[[ "${CERTBOT_DOMAIN:-}" == "mv.epaipix.com" ]]
[[ "${CERTBOT_TOKEN:-}" =~ ^[A-Za-z0-9_-]+$ ]]
path="$root/.deployment/acme/.well-known/acme-challenge"
mkdir -p "$path"
printf '%s' "$CERTBOT_VALIDATION" > "$path/$CERTBOT_TOKEN"
container="$(docker ps -q --filter label=com.docker.compose.project=mv-agent-frontend --filter label=com.docker.compose.service=frontend)"
test -n "$container"
docker exec "$container" mkdir -p /usr/share/nginx/html/.well-known/acme-challenge
docker cp "$path/$CERTBOT_TOKEN" "$container:/usr/share/nginx/html/.well-known/acme-challenge/$CERTBOT_TOKEN"
