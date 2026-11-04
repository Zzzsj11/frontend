#!/usr/bin/env bash
# 由 deploy.sh source；仅在目标健康后改变运行中的 Nginx 配置。
switch_backend() {
  local target="${1:?backend container name}"
  [[ "$target" =~ ^[a-zA-Z0-9_-]+$ ]] || return 1
  "${compose[@]}" exec -T frontend sh -eu -s -- "$target" <<'NGINX'
target="$1"
wget -qO- "http://$target:8000/api/health" >/dev/null
config=/etc/nginx/conf.d/default.conf
cp "$config" "$config.previous"
sed "s|set \$backend_upstream http://[a-zA-Z0-9_-]*:8000;|set \$backend_upstream http://$target:8000;|" "$config.previous" > "$config"
if ! grep -q "set \$backend_upstream http://$target:8000;" "$config" || ! nginx -t || ! nginx -s reload; then
  cp "$config.previous" "$config"
  nginx -s reload || true
  exit 1
fi
rm "$config.previous"
NGINX
}
