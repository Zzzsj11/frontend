#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
version="${1:?usage: scripts/deploy.sh VERSION}"; env_name="${DEPLOY_ENV:-production}"
env_file=".env.${env_name}"; test -f "$env_file" || { echo "missing $env_file"; exit 1; }
if [[ "$env_name" == "production" ]]; then "$root/scripts/validate-secret-layout.sh"; fi
previous="$(cat .deployed-version 2>/dev/null || true)"
printf '%s\n' "$previous" > .previous-version
mkdir -p .deployment
if [[ ! -f .deployment/info.json ]]; then
  printf '{"version":null,"deployedAt":null}\n' > .deployment/info.json
fi
export RELEASE_VERSION="$version"
compose=(docker compose --env-file "$env_file" -f docker-compose.yml -f "docker-compose.${env_name}.yml")
if [[ "${DEPLOY_SKIP_PULL:-0}" != "1" ]]; then
  "${compose[@]}" pull
fi

# A brand-new server has no data containers yet. Start durable dependencies
# before the green backend so DNS, migrations, and health checks work on the
# first deployment as well as on later rolling deployments.
"${compose[@]}" up -d postgres redis
for _ in {1..60}; do
  postgres_status="$("${compose[@]}" ps --format json postgres 2>/dev/null | grep -o '"Health":"[^"]*"' | head -1 || true)"
  redis_status="$("${compose[@]}" ps --format json redis 2>/dev/null | grep -o '"Health":"[^"]*"' | head -1 || true)"
  [[ "$postgres_status" == '"Health":"healthy"' && "$redis_status" == '"Health":"healthy"' ]] && break
  sleep 2
done
"${compose[@]}" exec -T postgres pg_isready -U "${POSTGRES_USER:-mvagent}" -d "${POSTGRES_DB:-mvagent}" >/dev/null
"${compose[@]}" exec -T redis redis-cli ping | grep -qx PONG

# 先更新 frontend：新的 nginx（运行时解析 backend 上游）就绪后，后续 backend 切换才不会 502
"${compose[@]}" up -d --no-deps frontend

# 平滑切换 backend：用新版本起 green 一次性容器（compose run 继承服务的环境/密钥/网络别名），
# 健康后再重建正式容器 —— 整个窗口内始终有健康上游，消除 502 窗口
green="mv-backend-green"
docker rm -f "$green" >/dev/null 2>&1 || true
"${compose[@]}" run -d --no-deps --name "$green" backend >/dev/null
green_ok=0
for _ in {1..60}; do
  if docker exec "$green" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health')" >/dev/null 2>&1; then
    green_ok=1
    break
  fi
  sleep 2
done
if [[ "$green_ok" != "1" ]]; then
  echo "green backend health check failed; last logs:" >&2
  docker logs --tail=100 "$green" >&2 || true
  docker rm -f "$green" >/dev/null 2>&1 || true
  echo "aborting deploy, current version still serving" >&2
  exit 1
fi
# 重建正式 backend：旧容器停起期间流量由 green 承载
"${compose[@]}" up -d --no-deps backend
for _ in {1..30}; do curl -fsS http://127.0.0.1:8000/api/health >/dev/null && break; sleep 2; done
curl -fsS http://127.0.0.1:8000/api/health >/dev/null
docker rm -f "$green" >/dev/null || echo "warn: failed to remove $green" >&2

# 兜底其余服务（postgres/redis 配置漂移等），无变化时为空操作
"${compose[@]}" up -d --remove-orphans
printf '%s\n' "$version" > .deployed-version
deployed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
printf '{"version":"%s","deployedAt":"%s"}\n' "$version" "$deployed_at" > .deployment/info.json.tmp
mv .deployment/info.json.tmp .deployment/info.json
echo "deployed $version ($env_name); previous=$previous"
