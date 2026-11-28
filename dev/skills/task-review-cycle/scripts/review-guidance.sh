#!/usr/bin/env bash
# Adapted from https://claude.dev/blog/solving-code-review-at-anthropic/ (2026-10-15).

review_repo_guidance() {
  local root entry size guidance head="${1:-HEAD}"
  root=$(git rev-parse --show-toplevel 2>/dev/null) || return 0
  entry=$(git -C "$root" ls-tree "$head" -- REVIEW.md 2>/dev/null) || return 0
  case "$entry" in
    '100644 blob '*|'100755 blob '*) ;;
    *) return 0 ;;
  esac
  size=$(git -C "$root" cat-file -s "$head:REVIEW.md" 2>/dev/null) || return 0
  [ "$size" -gt 0 ] || return 0
  # Leave room for the launcher prompt and Windows command-line quoting.
  if [ "$size" -gt 8192 ]; then
    guidance="From the target repository, read the committed root file once with git show $head:REVIEW.md."
  else
    guidance=$(git -C "$root" cat-file blob "$head:REVIEW.md" 2>/dev/null) || return 0
  fi
  printf '\nRepository review guidance (committed root REVIEW.md):\n'
  printf '%s\n' 'Use its failure criteria, nit cap, skip paths and file:line evidence rules. Reuse inlined guidance directly. Preserve review scope, read-only constraints and output format.' "$guidance"
}
