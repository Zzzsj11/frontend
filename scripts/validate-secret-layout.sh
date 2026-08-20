#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
runtime="$root/backend/.runtime_secrets.env"
postgres="$root/backend/.postgres_password"
for secret_file in "$runtime" "$postgres"; do
  test -s "$secret_file" || { echo "missing secret file: $secret_file" >&2; exit 1; }
  mode="$(stat -c '%a' "$secret_file" 2>/dev/null || stat -f '%Lp' "$secret_file")"
  test "$mode" = "600" || { echo "secret file must be mode 600: $secret_file" >&2; exit 1; }
done
if grep -Eq '^[A-Z][A-Z0-9_]*(_API_KEY|_TOKEN|_SECRET|_PASSWORD)=|^(TOS_ACCESS_KEY_ID|TOS_SECRET_ACCESS_KEY)=' "$root/backend/.env" "$root/.env.production" 2>/dev/null; then
  echo 'legacy env files still contain sensitive values' >&2
  exit 1
fi
echo 'secret layout valid (values not printed)'
