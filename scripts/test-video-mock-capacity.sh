#!/usr/bin/env bash
# Run on the MV staging host after deploying the same image to backend and workers.
set -euo pipefail
cd "$(dirname "$0")/.."
export RELEASE_VERSION="$(cat .deployed-version)"
compose=(docker compose --env-file .env.production -f docker-compose.yml -f docker-compose.production.yml)
backend="$("${compose[@]}" ps -q backend)"
case "${MV_PROOF_ENV:-test}" in
  test) target=test:mv-test.epaipix.com ;;
  production) target=production:mv.epaipix.com ;;
  *) echo "Unknown MV proof environment" >&2; exit 2 ;;
esac
docker exec "$backend" sh -ec 'test "$DEPLOYMENT_TIER:$TLS_DOMAIN" = "$1"' sh "$target"
mkdir -p .deployment/mock-video
exec 9>.deployment/mock-video/acceptance.lock
flock -n 9 || { echo "another mock test is active"; exit 1; }
out="$(mktemp -d .deployment/mock-video/run-XXXXXX)"
echo "Evidence directory: $out"
docker exec -e MV_SHARDED_WINDOW=1 -e "MV_DIAGNOSTIC_VEO_SLOTS=${MV_DIAGNOSTIC_VEO_SLOTS:-500}" "$backend" python -u -m scripts.mock_video_acceptance >"$out/run.log" 2>&1 &
driver=$!
for _ in $(seq 1 500); do
  run="$(sed -n 's|^Evidence directory: /tmp/\(mv-[a-f0-9]*\)$|\1|p' "$out/run.log" | head -1)"
  if [[ "$run" =~ ^mv-[0-9a-f]{32}$ ]] && docker exec "$backend" test -f "/tmp/$run/ready.json"; then
    break
  fi
  kill -0 "$driver" 2>/dev/null || break
  sleep 1
done
if [[ "$run" =~ ^mv-[0-9a-f]{32}$ ]] && docker exec "$backend" test -f "/tmp/$run/ready.json"; then
  start=$(( $(date +%s) + 15 ))
  services=(worker-wan worker-seedance worker-media worker-export)
  pids=()
  for i in "${!services[@]}"; do
    container="$("${compose[@]}" ps -q "${services[i]}")"
    docker exec "$container" python -m scripts.mock_video_query_shard "$run" "$start" "$i" 4 "/tmp/$run-$i.json" >"$out/shard-$i.log" 2>&1 &
    pids+=("$!")
  done
  for pid in "${pids[@]}"; do wait "$pid" || true; done
  parts=()
  for i in "${!services[@]}"; do
    file="shard-$i.json"
    container="$("${compose[@]}" ps -q "${services[i]}")"
    docker cp "$container:/tmp/$run-$i.json" "$out/$file"
    docker cp "$out/$file" "$backend:/tmp/$run/$file"
    parts+=("/tmp/$run/$file")
  done
  docker exec "$backend" python -m scripts.mock_video_window "${parts[@]}" >"$out/window.json"
  docker exec -i "$backend" sh -c 'cat > "$1/window.tmp" && mv "$1/window.tmp" "$1/window.json"' sh "/tmp/$run" <"$out/window.json"
fi
rc=0
wait "$driver" || rc=$?
if [[ "$run" =~ ^mv-[0-9a-f]{32}$ ]]; then
  for file in jobs.jsonl summary.json request-ids.jsonl; do docker cp "$backend:/tmp/$run/$file" "$out/$file" || true; done
fi
cat "$out/run.log"
exit "$rc"
