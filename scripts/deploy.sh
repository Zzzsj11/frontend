#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
mkdir -p .deployment
exec 9>.deployment/deploy.lock
# The shell holds fd 9 until exit. Children lock the same open file description
# on both Linux and macOS, including hosts without a flock executable.
python3 - <<'LOCK'
import fcntl
try:
    fcntl.flock(9, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit("another deployment is in progress")
LOCK
version="${1:?usage: scripts/deploy.sh VERSION}"
release_pair="$(python3 - <<'STATE'
import json
from pathlib import Path

def legacy(name):
    path = Path(name)
    return path.read_text().strip() if path.is_file() else ""

record = Path(".deployment/info.json")
if record.is_file():
    state = json.loads(record.read_text())
    # Older records predate the previous field. Only that legacy format
    # needs the old rollback marker, even when an explicit new pointer is empty.
    current = state.get("version") or (legacy(".deployed-version") if "previous" not in state else "")
    previous = state["previous"] if "previous" in state else legacy(".previous-version")
else:
    current, previous = legacy(".deployed-version"), legacy(".previous-version")
print(f"{current}|{previous or ''}")
STATE
)"
IFS='|' read -r current previous <<< "$release_pair"
if [[ "$version" == "--previous" ]]; then
  version="$previous"
  test -n "$version" || { echo "no rollback version" >&2; exit 1; }
fi
if [[ "$current" != "$version" ]]; then previous="$current"; fi
env_name="${DEPLOY_ENV:-production}"
env_file=".env.${env_name}"; test -f "$env_file" || { echo "missing $env_file"; exit 1; }
if [[ "$env_name" == "production" ]]; then
  "$root/scripts/validate-secret-layout.sh"
  # Compose 文件型 secrets 保留宿主属主；应用 UID 必须能读取 0600 密钥。
  chown 10001:10001 "$root/backend/.runtime_secrets.env"
fi
# 复用上次成功部署的非敏感 TLS 配置，普通发布/回滚不应意外退回 HTTP。
if [[ -f .deployment/tls.env ]]; then
  while IFS='=' read -r setting value; do
    case "$setting" in
      DEPLOY_TLS) export DEPLOY_TLS="${DEPLOY_TLS:-$value}" ;;
      TLS_DOMAIN) export TLS_DOMAIN="${TLS_DOMAIN:-$value}" ;;
      TLS_CERT_DIR) export TLS_CERT_DIR="${TLS_CERT_DIR:-$value}" ;;
    esac
  done < .deployment/tls.env
fi
export RELEASE_VERSION="$version"
compose=(docker compose --env-file "$env_file" -f docker-compose.yml -f "docker-compose.${env_name}.yml")
if [[ "${RUN_MIGRATIONS:-1}" == "0" ]]; then
  compose+=(-f docker-compose.rollback.yml)
fi
if [[ "${DEPLOY_TLS:-0}" == "1" ]]; then
  : "${TLS_DOMAIN:?set TLS_DOMAIN when DEPLOY_TLS=1}"
  : "${TLS_CERT_DIR:?set TLS_CERT_DIR when DEPLOY_TLS=1}"
  [[ -r "$TLS_CERT_DIR/fullchain.pem" && -r "$TLS_CERT_DIR/privkey.pem" ]] || {
    echo "TLS_CERT_DIR must contain readable fullchain.pem and privkey.pem" >&2
    exit 1
  }
  source_tls_dir="$TLS_CERT_DIR"
  verify_name=(-verify_hostname "$TLS_DOMAIN")
  if [[ "$TLS_DOMAIN" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then verify_name=(-verify_ip "$TLS_DOMAIN"); fi
  openssl verify -purpose sslserver "${verify_name[@]}" -untrusted "$source_tls_dir/fullchain.pem" "$source_tls_dir/fullchain.pem" >/dev/null
  cert_public="$(openssl x509 -in "$source_tls_dir/fullchain.pem" -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256)"
  key_public="$(openssl pkey -in "$source_tls_dir/privkey.pem" -passin pass: -pubout -outform DER | openssl dgst -sha256)"
  [[ "$cert_public" == "$key_public" ]] || { echo 'TLS certificate and key do not match' >&2; exit 1; }
  # Let's Encrypt live/ 中的文件通常是符号链接；只挂载 live 子目录会使链接失效。
  install -d -m 700 "$root/.deployment/tls"
  if [[ "$(cd "$source_tls_dir" && pwd -P)" != "$(cd "$root/.deployment/tls" && pwd -P)" ]]; then
    install -m 600 "$source_tls_dir/fullchain.pem" "$root/.deployment/tls/fullchain.pem"
    install -m 600 "$source_tls_dir/privkey.pem" "$root/.deployment/tls/privkey.pem"
  fi
  export TLS_CERT_DIR="$root/.deployment/tls"
  compose+=(-f docker-compose.tls.yml)
fi
if [[ "${DEPLOY_SKIP_PULL:-0}" != "1" ]]; then
  "${compose[@]}" pull
fi

# 先在一次性容器验证运行配置与 Secret 读取权限；失败时不切换任何服务。
# 只导入配置，不启动应用、不执行迁移，也不会恢复或触发模型工单。
"${compose[@]}" run --rm -T --no-deps --entrypoint python backend \
  -c 'from app.config import validate_runtime_security; validate_runtime_security()'
if [[ "${DEPLOY_TLS:-0}" == "1" ]]; then
  "${compose[@]}" run --rm -T --no-deps frontend nginx -t
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

# green 以唯一容器名接入同一网络；健康后显式切换 Nginx，再重建 backend。
source "$root/scripts/switch-backend.sh"
green="mv-backend-green-$(date +%s)-$$"
green_serving=0
cleanup_green() {
  local status=$?
  if [[ "$green_serving" == "1" ]]; then
    echo "deployment interrupted; $green remains serving traffic; repair backend then switch Nginx back before removing it" >&2
  else
    docker stop --time 60 "$green" >/dev/null 2>&1 || true
    docker rm "$green" >/dev/null 2>&1 || true
  fi
  return "$status"
}
trap cleanup_green EXIT
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
  echo "aborting deploy, current version still serving" >&2
  exit 1
fi
# 切流失败时保留 green，避免响应丢失或 reload 状态不确定后误删上游。
existing_frontend="$("${compose[@]}" ps --status running -q frontend)"
if [[ -n "$existing_frontend" ]]; then
  green_serving=1
  switch_backend "$green"
fi
# 强制重建正式 backend：版本号不变的 Secret 轮换也必须让进程重新读取挂载文件；
# 旧容器停起期间流量由 green 承载。
"${compose[@]}" up -d --no-deps --force-recreate backend
for _ in {1..30}; do curl -fsS --max-time 10 http://127.0.0.1:8000/api/health >/dev/null && break; sleep 2; done
curl -fsS --max-time 10 http://127.0.0.1:8000/api/health >/dev/null
if [[ -n "$existing_frontend" ]]; then switch_backend backend; fi
green_serving=0
# SIGTERM 给已经连到 green 的请求保留与正式 API 相同的排空窗口。
docker stop --time 60 "$green" >/dev/null
docker rm "$green" >/dev/null
trap - EXIT

execution_mode="$("${compose[@]}" config --format json | python3 -c 'import json,sys; print(json.load(sys.stdin)["services"]["backend"]["environment"].get("JOB_EXECUTION_MODE", "inline"))')"
if [[ "$execution_mode" == "worker" ]]; then
# 单机逐类排空：旧进程先收到 SIGTERM、停止领取并在各自 stop_grace_period 内完成
# 在途任务，再启动同类新进程。供应商不支持创建幂等键时，不让新旧版本并行提交
# 比缩短发布耗时更重要；该类排空期间新任务继续安全留在 PostgreSQL 队列。
for worker in worker-chat worker-storyboard worker-image worker-media worker-export; do
  "${compose[@]}" up -d --no-deps --force-recreate "$worker"
  for _ in {1..60}; do
    status="$("${compose[@]}" ps --format json "$worker" 2>/dev/null | grep -o '"Health":"[^"]*"' | head -1 || true)"
    [[ "$status" == '"Health":"healthy"' ]] && break
    sleep 2
  done
  [[ "$status" == '"Health":"healthy"' ]] || { echo "$worker failed health check" >&2; exit 1; }
done

else
  # 显式服务名会越过 profiles；inline 模式必须停止遗留 Worker。
  "${compose[@]}" stop worker-chat worker-storyboard worker-image worker-media worker-export
  export COMPOSE_PROFILES=""
fi

# 兜底其余服务（postgres/redis 配置漂移等），无变化时为空操作
"${compose[@]}" up -d --remove-orphans
probe=(curl -fsS --connect-timeout 3 --max-time 10 --retry 5 --retry-delay 1 --retry-connrefused)
if [[ "${DEPLOY_TLS:-0}" == "1" ]]; then
  "${compose[@]}" exec -T frontend nginx -t
  "${compose[@]}" exec -T frontend nginx -s reload
  frontend_origin="https://$TLS_DOMAIN"
  probe+=(--resolve "$TLS_DOMAIN:443:127.0.0.1")
else
  binding="$("${compose[@]}" port frontend 80 | head -1)"
  frontend_port="${binding##*:}"
  [[ "$frontend_port" =~ ^[0-9]+$ ]] || { echo "frontend has no published HTTP port" >&2; exit 1; }
  frontend_origin="http://127.0.0.1:$frontend_port"
fi
for path in / /api/health; do
  status="$("${probe[@]}" -o /dev/null -w '%{http_code}' "$frontend_origin$path")"
  [[ "$status" == "200" ]] || { echo "frontend readiness failed: $path HTTP $status" >&2; exit 1; }
done
if [[ "$env_name" == "production" ]]; then ./scripts/retire-legacy-service-cron.sh; fi
if [[ "${DEPLOY_TLS:-0}" == "1" ]]; then
  (umask 077; printf 'DEPLOY_TLS=1\nTLS_DOMAIN=%s\nTLS_CERT_DIR=%s\n' "$TLS_DOMAIN" "$source_tls_dir" > .deployment/tls.env.tmp)
  mv .deployment/tls.env.tmp .deployment/tls.env
fi
deployed_at="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
python3 - "$version" "$deployed_at" "$previous" > .deployment/info.json.tmp <<'PYINFO'
import json, sys
print(json.dumps(dict(zip(("version", "deployedAt", "previous"), sys.argv[1:]))))
PYINFO
mv .deployment/info.json.tmp .deployment/info.json
printf '%s\n' "$previous" > .previous-version.tmp && mv .previous-version.tmp .previous-version
printf '%s\n' "$version" > .deployed-version.tmp && mv .deployed-version.tmp .deployed-version
echo "deployed $version ($env_name); previous=$previous"
