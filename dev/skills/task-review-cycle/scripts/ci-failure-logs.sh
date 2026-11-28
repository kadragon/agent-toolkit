#!/usr/bin/env bash
# Fetch CI failure logs for a PR.
# Backend-agnostic: delegates to hub.sh ci-logs.
#   - GitHub:  failed checks + last 200 log lines per failed run (gh run view)
#   - Forgejo: failed status contexts + target URLs (no log API ≤ v15;
#              output carries logs_available: false)
#
# Usage: ci-failure-logs.sh <pr_number> [--expected-head <sha> (GitHub only)]
# Output: JSON — {failed_checks: [{name, run_id, logs}], count, logs_available, reason?}

set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

: "${1:?Usage: ci-failure-logs.sh <pr_number> [--expected-head <sha>]}"

bash "$SCRIPT_DIR/hub.sh" ci-logs "$@"
