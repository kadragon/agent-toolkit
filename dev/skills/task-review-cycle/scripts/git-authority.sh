#!/usr/bin/env bash
# Check the existing branch contract before a Git write. Source from action scripts.
# The source is verified by the orchestrator against the user message, not by a flag.
require_git_authority() {
  local authority_dir authority_state authority_python
  authority_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
  authority_state="$authority_dir/../../task-next/scripts/cycle_state.py"
  authority_python=$(command -v python3 || command -v python || true)
  if [[ ! -r "$authority_state" || -z "$authority_python" ]]; then
    echo "Git authority denied: bundled contract checker or Python unavailable" >&2
    return 1
  fi
  "$authority_python" "$authority_state" authorize "$@" >/dev/null
}
