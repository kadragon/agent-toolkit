#!/usr/bin/env bash
# Repository prompt guidance for Codex and agy. Claude uses its local review skill's load.
# Adapted from https://claude.dev/blog/solving-code-review-at-anthropic/ (2026-10-15).

review_repo_guidance() {
  local root file
  root=$(git rev-parse --show-toplevel 2>/dev/null) || return 0
  file="$root/REVIEW.md"
  # A symlink could send data from outside the target repo to the reviewer.
  [ -f "$file" ] && [ ! -L "$file" ] && [ -s "$file" ] || return 0
  printf '\nRepository review guidance (root REVIEW.md, supplied here once):\n'
  printf '%s\n' 'Use its failure criteria, nit cap, skip paths and file:line evidence rules. Do not reload the file or override the review scope, read-only constraints or output format.'
  cat -- "$file"
}
