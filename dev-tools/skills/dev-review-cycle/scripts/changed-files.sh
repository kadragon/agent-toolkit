#!/usr/bin/env bash
# Detect files to stage: tracked changes against HEAD + untracked new files.
#
# Usage: changed-files.sh
# Output: One file path per line to stdout.

set -euo pipefail

# git diff --name-only HEAD fails on first commit (no HEAD yet); fall back to --cached.
tracked=$(git diff --name-only HEAD 2>/dev/null \
  || git diff --cached --name-only 2>/dev/null \
  || true)
untracked=$(git ls-files --others --exclude-standard 2>/dev/null || true)

# grep -v exits 1 when every line is filtered out (clean tree → empty output).
# That is not an error here — no changed files is a valid result — so `|| true`
# keeps the pipeline from tripping `set -euo pipefail` and exiting non-zero.
printf '%s\n%s\n' "$tracked" "$untracked" \
  | grep -v '^[[:space:]]*$' \
  | sort -u \
  || true
