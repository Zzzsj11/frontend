#!/usr/bin/env bash
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/mv-agent-frontend}"
DOMAIN="${DOMAIN:-}"
failures=0

pass() { printf '[PASS] %s\n' "$1"; }
fail() { printf '[FAIL] %s\n' "$1"; failures=$((failures + 1)); }

cd "$PROJECT_DIR" || { printf '[FAIL] project directory: %s\n' "$PROJECT_DIR"; exit 1; }
env_file=".env.${DEPLOY_ENV:-production}"
export RELEASE_VERSION="${RELEASE_VERSION:-$(cat .deployed-version 2>/dev/null || true)}"
compose=(docker compose --env-file "$env_file" -f docker-compose.yml -f "docker-compose.${DEPLOY_ENV:-production}.yml")

for service in postgres redis backend frontend; do
  container_id="$("${compose[@]}" ps -q "$service" 2>/dev/null)"
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

if grep -Eq '^JOB_EXECUTION_MODE=worker$' "$env_file"; then
  for service in worker-media worker-export worker-chat worker-storyboard; do
    container_id="$("${compose[@]}" ps -q "$service")"
    status="$(docker inspect --format '{{.State.Status}}/{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$container_id" 2>/dev/null || true)"
    [[ "$status" == 'running/healthy' ]] && pass "container $service: healthy" || fail "container $service: $status"
  done
fi

BACKEND_PORT="${BACKEND_PORT:-8000}"
curl -fsS --max-time 10 "http://127.0.0.1:$BACKEND_PORT/api/health" >/dev/null \
  && pass "backend API on 127.0.0.1:$BACKEND_PORT" \
  || fail "backend API on 127.0.0.1:$BACKEND_PORT"

"${compose[@]}" exec -T postgres sh -lc 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' >/dev/null 2>&1 \
  && pass 'PostgreSQL accepts connections' \
  || fail 'PostgreSQL connection'

[ "$("${compose[@]}" exec -T redis redis-cli ping 2>/dev/null | tr -d '\r')" = 'PONG' ] \
  && pass 'Redis responds PONG' \
  || fail 'Redis connection'

if [ -n "$DOMAIN" ]; then
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
else
  pass 'domain/HTTPS checks skipped (DOMAIN not set)'
fi

if [ "$failures" -eq 0 ]; then
  printf '\nAll online checks passed.\n'
  exit 0
fi

printf '\n%d online check(s) failed.\n' "$failures"
exit 1
