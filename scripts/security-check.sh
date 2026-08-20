#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"; cd "$root"
if git grep -nE '(JWT_SECRET|PASSWORD|SECRET_KEY)=(123456|development-only)' -- ':!scripts/security-check.sh'; then echo '[FAIL] insecure committed secret'; exit 1; fi
if git grep -nE 'yh-[A-Za-z0-9]{20,}' -- ':!scripts/security-check.sh'; then echo '[FAIL] committed provider token'; exit 1; fi
npm audit --audit-level=critical --registry=https://registry.npmjs.org
backend/.venv/bin/pip check
echo '[PASS] basic secret and dependency checks'
