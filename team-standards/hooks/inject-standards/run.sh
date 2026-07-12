#!/usr/bin/env bash
# SessionStart hook: injects the team's agent working standards as system
# context (stdout of a SessionStart hook is added to context, invisible to
# the user in the transcript UI). Lets every session start from the same
# baseline without each person maintaining their own global CLAUDE.md.
set -u

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" 2>/dev/null && pwd -P)
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT:-}}"
if [[ -z "$PLUGIN_ROOT" ]] && [[ -n "$SCRIPT_DIR" ]]; then
  PLUGIN_ROOT=$(cd -- "$SCRIPT_DIR/../.." 2>/dev/null && pwd -P)
fi

STANDARDS_FILE="${PLUGIN_ROOT}/standards/AGENT-STANDARDS.md"
[[ -f "$STANDARDS_FILE" ]] || exit 0

cat "$STANDARDS_FILE"
exit 0
