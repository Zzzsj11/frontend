#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${VERSION:?Set immutable image version}"
if [[ "$VERSION" == latest || ! "$VERSION" =~ ^[a-zA-Z0-9_][a-zA-Z0-9_.-]{0,127}$ ]]; then
  echo 'VERSION must be a versioned image tag, not latest' >&2
  exit 2
fi
# Only this disposable container receives the owner credential. Do not source
# this file or use a Compose service (which would inherit runtime credentials).
if [[ ! -f "$PWD/.env.migration" ]]; then
  echo 'Prepare model-service/.env.migration with the migration owner DATABASE_URL (mode 600)' >&2
  exit 2
fi
for path in migrations alembic.ini scripts/seed.py; do
  if [[ ! -e "$PWD/$path" ]]; then
    echo "Missing migration release artifact: $path" >&2
    exit 2
  fi
done
network="${MIGRATION_DOCKER_NETWORK:-company-model-service_default}"
if [[ "${DEPLOY_MV:-0}" == 1 ]]; then
  network="${MV_DOCKER_NETWORK:-mv-agent-frontend_default}"
fi
# The release bundle and public image must be from the same version. The image
# is deliberately preloaded: this step never builds or silently pulls latest.
docker run --rm --pull never \
  --network "$network" \
  --env-file "$PWD/.env.migration" \
  --env PYTHONPATH=/service \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,source=$PWD/migrations,target=/service/migrations,readonly" \
  --mount "type=bind,source=$PWD/alembic.ini,target=/service/alembic.ini,readonly" \
  --mount "type=bind,source=$PWD/scripts/seed.py,target=/service/scripts/seed.py,readonly" \
  --workdir /service --entrypoint sh \
  "${MODEL_IMAGE_REGISTRY:-local}/model-public:$VERSION" \
  -ec 'python -m alembic -c /service/alembic.ini upgrade head && python /service/scripts/seed.py'
