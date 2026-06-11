#!/usr/bin/env bash
# Fetch CI failure logs for a PR.
# Backend-agnostic: delegates to hub.sh ci-logs.
#   - GitHub:  failed checks + last 200 log lines per failed run (gh run view)
#   - Forgejo: failed status contexts + target URLs (no log API ≤ v15;
#              output carries logs_available: false)
#
# Usage: ci-failure-logs.sh <pr_number>
# Output: JSON — {failed_checks: [{name, run_id, logs}], count, logs_available}

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PR_NUMBER="${1:?Usage: ci-failure-logs.sh <pr_number>}"

bash "$SCRIPT_DIR/hub.sh" ci-logs "$PR_NUMBER"
