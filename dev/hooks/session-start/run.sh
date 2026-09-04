#!/usr/bin/env bash
# SessionStart dispatcher: daily-debounced harness maintenance. Best-effort — never blocks startup.

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)
MAINTENANCE="$SCRIPT_DIR/harness-maintenance.sh"

if [[ -f "$MAINTENANCE" ]]; then
  bash "$MAINTENANCE" || true
fi

exit 0
