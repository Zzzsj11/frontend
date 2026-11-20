#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/restore-postgres.sh"
prepare_restore "${1:?usage: scripts/verify-backup.sh BACKUP.dump}"
verify_in_new_database
