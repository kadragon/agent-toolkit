#!/usr/bin/env bash
# Review-recall run: both review slots on each fixture's original introducing diff.
#
# Usage: run.sh <out-dir> [fixture-id ...]
#   out-dir      where <id>-claude.json, <id>-codex.txt and <id>-meta.txt land
#   fixture-id   ids from fixtures.tsv (default: all), run in parallel
#
# Per fixture: a worktree at the introducing commit on branch bench/<id>, with
# bench-base/<id> at its parent, then claude-review.sh (default effort, no
# contract) and codex-review.sh against that base — the same calls the cycle
# makes. Worktrees and branches are removed at the end. Scoring is by hand
# against README.md → Fixtures; see RESULTS.md for the last run.
set -euo pipefail

OUT="${1:?Usage: run.sh <out-dir> [fixture-id ...]}"
shift

HERE=$(cd "$(dirname "$0")" && pwd)
[[ -n "$HERE" ]] || { echo "ERROR: cannot resolve script dir" >&2; exit 1; }
SCRIPTS=$(cd "$HERE/../../scripts" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
[[ -f "$SCRIPTS/claude-review.sh" && -f "$SCRIPTS/codex-review.sh" ]] \
  || { echo "ERROR: review scripts not found under $SCRIPTS" >&2; exit 1; }

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
WT_ROOT=$(mktemp -d -t review-recall.XXXXXX)
[[ -d "$WT_ROOT" ]] || { echo "ERROR: mktemp failed" >&2; exit 1; }

run_one() {
  local id="$1" sha="$2"
  local base="bench-base/$id" wt="$WT_ROOT/$id"
  git -C "$REPO" branch -f "$base" "${sha}^" >/dev/null
  git -C "$REPO" worktree add -q -B "bench/$id" "$wt" "$sha"

  local preflight codex_mode companion t0
  preflight=$(cd "$wt" && bash "$SCRIPTS/preflight.sh" "")
  codex_mode=$(jq -r '.codex_mode' <<<"$preflight")
  companion=$(jq -r '.codex_companion_path' <<<"$preflight")

  {
    echo "id=$id"
    echo "sha=$sha"
    echo "base=$(git -C "$REPO" rev-parse --short "${sha}^")"
    git -C "$REPO" show --stat --format= "$sha" | tail -1
    echo "claude_version=$(claude --version 2>/dev/null | head -1)"
    echo "codex_mode=$codex_mode"
    echo "started=$(date -u +%FT%TZ)"
  } >"$OUT/$id-meta.txt"

  t0=$(date +%s)
  (cd "$wt" && bash "$SCRIPTS/claude-review.sh" "$base" "" "") \
    >"$OUT/$id-claude.json" 2>"$OUT/$id-claude.err" || echo "claude_exit=$?" >>"$OUT/$id-meta.txt"
  echo "claude_seconds=$(( $(date +%s) - t0 ))" >>"$OUT/$id-meta.txt"

  t0=$(date +%s)
  (cd "$wt" && bash "$SCRIPTS/codex-review.sh" "$codex_mode" "$base" "$companion") \
    >"$OUT/$id-codex.txt" 2>"$OUT/$id-codex.err" || echo "codex_exit=$?" >>"$OUT/$id-meta.txt"
  echo "codex_seconds=$(( $(date +%s) - t0 ))" >>"$OUT/$id-meta.txt"
  echo "finished=$(date -u +%FT%TZ)" >>"$OUT/$id-meta.txt"
}

cleanup() {
  local id
  for id in "${IDS[@]}"; do
    git -C "$REPO" worktree remove --force "$WT_ROOT/$id" 2>/dev/null || true
    git -C "$REPO" branch -D "bench/$id" "bench-base/$id" >/dev/null 2>&1 || true
  done
  rm -rf "$WT_ROOT"
}

IDS=()
SHAS=()
while IFS=$'\t' read -r id sha _fix; do
  [[ "$id" == "id" ]] && continue
  if [[ $# -eq 0 ]] || [[ " $* " == *" $id "* ]]; then
    IDS+=("$id")
    SHAS+=("$sha")
  fi
done <"$HERE/fixtures.tsv"
[[ ${#IDS[@]} -gt 0 ]] || { echo "ERROR: no matching fixtures" >&2; exit 1; }
trap cleanup EXIT

# Each fixture has its own worktree, so the runs do not share a lock and can overlap.
for i in "${!IDS[@]}"; do
  run_one "${IDS[$i]}" "${SHAS[$i]}" &
done
wait
echo "done: ${#IDS[@]} fixture(s) → $OUT"
