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

# Resolve the interpreter instead of hardcoding python3: on Windows the dispatcher
# replaced a `commandWindows` entry that deliberately called `python`, and installs
# without a python3 shim would drop the nudge silently (`|| true` hides the error).
PY=$(command -v python3 || command -v python || true)

if [[ -f "$NUDGE" && -n "$PY" ]]; then
  "$PY" "$NUDGE" || true
fi

exit 0
