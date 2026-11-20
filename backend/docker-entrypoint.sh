#!/bin/sh
set -eu

if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
  alembic upgrade head
fi
exec uvicorn app.proxy_entrypoint:create_app --factory --host 0.0.0.0 --port 8000 --no-proxy-headers
