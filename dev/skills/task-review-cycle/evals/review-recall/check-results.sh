#!/usr/bin/env bash
# Adapted from https://claude.dev/blog/solving-code-review-at-anthropic/ (2026-10-15).
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
# Hash normalized text with Git so CRLF checkouts and Linux CI agree. All launcher changes are
# tracked: flags, tool selection and shared guidance can change the review as much as prose.
INPUTS=(../../scripts/{claude-review,codex-review,agy-review,review-guidance}.sh
  ../../references/comment-rules.md fixtures.tsv run.sh)
# A launcher outside INPUTS could change the review with the fingerprint still fresh, so every
# `*-review.sh` under scripts/ must be listed there.
for launcher in ../../scripts/*-review.sh; do
  [[ " ${INPUTS[*]} " == *" $launcher "* ]] || {
    echo "ERROR: $launcher is a reviewer launcher missing from the fingerprint INPUTS in check-results.sh." >&2
    exit 1
  }
done
input_hashes() {
  local file hash
  for file in "${INPUTS[@]}"; do
    hash=$(sed $'s/\r$//' "$file" | git hash-object --stdin) || return 1
    printf '%s\n' "$hash"
  done
}
FINGERPRINT=$(input_hashes | git hash-object --stdin)
if [[ "${1:-}" == --fingerprint ]]; then
  printf '%s\n' "$FINGERPRINT"
  exit 0
fi

LATEST=$(grep '^Review recall fingerprint: ' RESULTS.md | tail -1 || true)
if [[ "${LATEST%$'\r'}" != "Review recall fingerprint: $FINGERPRINT" ]]; then
  echo 'ERROR: review-recall/RESULTS.md does not cover the current reviewer inputs.' >&2
  echo 'Run review-recall/run.sh on all fixtures, score the outputs, and copy the fingerprint beside the new scores.' >&2
  exit 1
fi
if [[ -n "${1:-}" ]]; then
  CHANGED_INPUTS=$(git diff --name-only "$1" -- "${INPUTS[@]}")
  CHANGED_RESULTS=$(git diff --name-only "$1" -- RESULTS.md)
  if [[ -n "$CHANGED_INPUTS" && -z "$CHANGED_RESULTS" ]]; then
    echo 'ERROR: reviewer inputs changed without a RESULTS.md update.' >&2
    exit 1
  fi
fi
echo 'OK: review-recall scorecard matches the current reviewer inputs.'
