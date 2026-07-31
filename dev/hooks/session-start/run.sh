#!/usr/bin/env bash
# SessionStart dispatcher: run independent harness maintenance and staleness nudge checks.
# Each component is best-effort; neither may block session startup.

set -uo pipefail

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)
MAINTENANCE="$SCRIPT_DIR/harness-maintenance.sh"
NUDGE="$SCRIPT_DIR/task-audit-nudge.py"

if [[ -f "$MAINTENANCE" ]]; then
  bash "$MAINTENANCE" || true
fi

if [[ -f "$NUDGE" ]]; then
  python3 "$NUDGE" || true
fi

exit 0
