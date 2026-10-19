#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
if [[ -f "$root/.deployment/tls.env" ]]; then
  while IFS='=' read -r setting value; do
    case "$setting" in
      TLS_DOMAIN) domain="$value" ;;
      TLS_CERT_DIR) cert_dir="$value" ;;
    esac
  done < "$root/.deployment/tls.env"
fi
domain="${domain:-mv.epaipix.com}"
[[ "$domain" == "mv.epaipix.com" || "$domain" == "mv-test.epaipix.com" ]]
lineage="${RENEWED_LINEAGE:-${cert_dir:-/etc/letsencrypt/live/$domain}}"
openssl verify -purpose sslserver -verify_hostname "$domain" -untrusted "$lineage/fullchain.pem" "$lineage/fullchain.pem"
install -d -m 700 "$root/.deployment/tls"
install -m 600 "$lineage/fullchain.pem" "$root/.deployment/tls/fullchain.pem"
install -m 600 "$lineage/privkey.pem" "$root/.deployment/tls/privkey.pem"
container="$(docker ps -q --filter label=com.docker.compose.project=mv-agent-frontend --filter label=com.docker.compose.service=frontend)"
test -n "$container"
docker exec "$container" nginx -t
docker exec "$container" nginx -s reload
