#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${VERSION:?Set immutable image version}"
if [[ "$VERSION" == latest || ! "$VERSION" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]; then
  echo 'VERSION must be a versioned image tag, not latest' >&2
  exit 2
fi
case "${1:-}" in
  public) services=(public-api worker) ;;
  user) services=(user-web) ;;
  admin) services=(admin-api admin-web) ;;
  *) echo 'Usage: VERSION=<version> [DEPLOY_MV=1] [DEPLOY_SKIP_PULL=1] scripts/deploy.sh public|admin|user'; exit 2 ;;
esac
wait_timeout="${DEPLOY_WAIT_TIMEOUT:-120}"
if [[ ! "$wait_timeout" =~ ^[1-9][0-9]*$ ]]; then
  echo 'DEPLOY_WAIT_TIMEOUT must be a positive number of seconds' >&2
  exit 2
fi
compose=(docker compose -f "$PWD/docker-compose.yml")
if [[ "${DEPLOY_MV:-0}" == 1 ]]; then
  compose+=(-f "$PWD/docker-compose.mv.yml")
fi
# Schema migrations are an explicit release step, never executed by restarting admin.
if [[ "${DEPLOY_SKIP_PULL:-0}" != 1 ]]; then
  "${compose[@]}" pull "${services[@]}"
fi
# Never build, implicitly pull, or restart an unselected service. A failed health
# check makes this release fail; do not auto-rollback or replay generation jobs.
"${compose[@]}" up -d --no-deps --no-build --pull never --wait --wait-timeout "$wait_timeout" "${services[@]}"
"${compose[@]}" ps "${services[@]}"
