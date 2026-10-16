#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
file="${1:?usage: scripts/sync-backup-to-tos.sh FILE.dump}"
: "${BACKUP_TOS_BUCKET:?configure a separate private encrypted backup bucket}"
test -s "$file" && test -s "$file.sha256"
checksum="$(awk '{print $1; exit}' "$file.sha256")"
compose=(docker compose -f docker-compose.yml)
if [[ "${DEPLOY_ENV:-production}" == "production" && -f .env.production ]]; then
  export RELEASE_VERSION="${RELEASE_VERSION:-$(cat .deployed-version)}"
  compose+=(--env-file .env.production -f docker-compose.production.yml)
else
  compose+=(-f docker-compose.local-build.yml)
fi
# 挂载受版本控制的上传器，应用回滚到旧镜像后依旧可备份。
"${compose[@]}" run --rm -T --no-deps --entrypoint python \
  -v "$root/backend/app/backup_archive.py:/srv/mvagent/app/backup_archive.py:ro" \
  -v "$root/backend/scripts/backup_to_tos.py:/srv/mvagent/scripts/backup_to_tos.py:ro" \
  backend scripts/backup_to_tos.py \
  --bucket "$BACKUP_TOS_BUCKET" --prefix "${BACKUP_TOS_PREFIX:-mv-agent/database}" \
  --name "$(basename "$file")" --sha256 "$checksum" < "$file"
