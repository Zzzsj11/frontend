#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
lineage="${RENEWED_LINEAGE:-/etc/letsencrypt/live/mv.epaipix.com}"
openssl verify -purpose sslserver -verify_hostname mv.epaipix.com -untrusted "$lineage/fullchain.pem" "$lineage/fullchain.pem"
install -d -m 700 "$root/.deployment/tls"
install -m 600 "$lineage/fullchain.pem" "$root/.deployment/tls/fullchain.pem"
install -m 600 "$lineage/privkey.pem" "$root/.deployment/tls/privkey.pem"
container="$(docker ps -q --filter label=com.docker.compose.project=mv-agent-frontend --filter label=com.docker.compose.service=frontend)"
test -n "$container"
docker exec "$container" nginx -t
docker exec "$container" nginx -s reload
