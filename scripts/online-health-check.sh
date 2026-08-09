#!/usr/bin/env bash
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mv-agent-frontend}"
DOMAIN="${DOMAIN:-mv.yangxiaren.club}"
failures=0

pass() { printf '[PASS] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failures=$((failures + 1)); }

cd "$PROJECT_DIR" || { printf '[FAIL] project directory: %s\n' "$PROJECT_DIR"; exit 1; }

for service in postgres redis backend frontend; do
  container_id="$(docker compose ps -q "$service" 2>/dev/null)"
  if [ -z "$container_id" ]; then
    fail "container $service is missing"
    continue
  fi
  state="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' "$container_id" 2>/dev/null)"
  if [ "$state" = "healthy" ] || [ "$state" = "running" ]; then
    pass "container $service: $state"
  else
    fail "container $service: ${state:-unknown}"
  fi
done

curl -fsS --max-time 10 http://127.0.0.1:8000/api/health >/dev/null \
  && pass 'backend API on 127.0.0.1:8000' \
  || fail 'backend API on 127.0.0.1:8000'

docker compose exec -T postgres pg_isready -U mvagent -d mvagent >/dev/null 2>&1 \
  && pass 'PostgreSQL accepts connections' \
  || fail 'PostgreSQL connection'

[ "$(docker compose exec -T redis redis-cli ping 2>/dev/null | tr -d '\r')" = 'PONG' ] \
  && pass 'Redis responds PONG' \
  || fail 'Redis connection'

http_code="$(curl -sS -o /dev/null --max-time 10 -w '%{http_code}' "http://$DOMAIN" || true)"
[ "$http_code" = '301' ] || [ "$http_code" = '308' ] \
  && pass "HTTP redirects to HTTPS ($http_code)" \
  || fail "HTTP redirect for $DOMAIN (status ${http_code:-000})"

https_code="$(curl -sS -o /dev/null --max-time 15 -w '%{http_code}' "https://$DOMAIN" || true)"
[ "$https_code" = '200' ] \
  && pass "HTTPS frontend ($https_code)" \
  || fail "HTTPS frontend for $DOMAIN (status ${https_code:-000})"

api_code="$(curl -sS -o /dev/null --max-time 15 -w '%{http_code}' "https://$DOMAIN/api/health" || true)"
[ "$api_code" = '200' ] \
  && pass "HTTPS API ($api_code)" \
  || fail "HTTPS API for $DOMAIN (status ${api_code:-000})"

if [ "$failures" -eq 0 ]; then
  printf '\nAll online checks passed.\n'
  exit 0
fi

printf '\n%d online check(s) failed.\n' "$failures"
exit 1
