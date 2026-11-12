#!/usr/bin/env bash
# Review-recall run: both review slots on each fixture's original introducing diff.
#
# Usage: run.sh <out-dir> [fixture-id ...]
#   out-dir      where <id>-claude.json, <id>-codex.txt and <id>-meta.txt land
#   fixture-id   ids from fixtures.tsv (default: all); fixtures run in parallel
# Env:
#   REVIEW_RECALL_EFFORT  effort passed to claude-review.sh (default: medium). Pinned because
#                         an empty effort makes code-review reuse the caller's last typed level.
#
# Each fixture runs in its own throwaway clone holding only the introducing commit and its
# parent (depth-2 fetch by sha): the reviewer cannot reach the fix commit or this
# directory's gold table, and nothing in the source repo's refs is created or touched.
# The clone has branch `base` at the parent and `HEAD` at the introducing commit, then
# claude-review.sh and codex-review.sh run against `base` — the same calls the cycle makes.
# Exit 1 when any fixture failed to produce its outputs. Scoring is by hand against
# README.md → Fixtures; see RESULTS.md.
set -euo pipefail

OUT="${1:?Usage: run.sh <out-dir> [fixture-id ...]}"
shift
EFFORT="${REVIEW_RECALL_EFFORT:-medium}"

HERE=$(cd "$(dirname "$0")" && pwd)
[[ -n "$HERE" ]] || { echo "ERROR: cannot resolve script dir" >&2; exit 1; }
SCRIPTS=$(cd "$HERE/../../scripts" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
[[ -f "$SCRIPTS/claude-review.sh" && -f "$SCRIPTS/codex-review.sh" ]] \
  || { echo "ERROR: review scripts not found under $SCRIPTS" >&2; exit 1; }

# Preflight once, locally: only the Codex mode and companion path are needed, and a hub
# preflight per fixture would race `git fetch` on the source repo.
PREFLIGHT=$(cd "$REPO" && bash "$SCRIPTS/preflight.sh" --no-hub)
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")
COMPANION=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")
[[ -n "$CODEX_MODE" && "$CODEX_MODE" != "null" ]] || { echo "ERROR: preflight gave no codex_mode" >&2; exit 1; }

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/review-recall.XXXXXX")
[[ -d "$WORK" ]] || { echo "ERROR: mktemp failed" >&2; exit 1; }

run_one() {
  local id="$1" sha="$2"
  local full clone t0
  full=$(git -C "$REPO" rev-parse --verify "${sha}^{commit}")
  clone="$WORK/$id"
  git init -q "$clone"
  git -C "$clone" -c protocol.version=2 fetch -q --depth=2 "file://$REPO" "$full"
  git -C "$clone" checkout -q -b bench FETCH_HEAD
  git -C "$clone" branch base HEAD^

  {
    echo "id=$id"
    echo "sha=$sha"
    echo "base=$(git -C "$clone" rev-parse --short base)"
    git -C "$clone" diff --shortstat base...HEAD
    echo "claude_version=$(claude --version 2>/dev/null | head -1)"
    echo "claude_effort=$EFFORT"
    echo "codex_mode=$CODEX_MODE"
    echo "started=$(date -u +%FT%TZ)"
  } >"$OUT/$id-meta.txt"

  t0=$(date +%s)
  (cd "$clone" && bash "$SCRIPTS/claude-review.sh" base "$EFFORT" "") \
    >"$OUT/$id-claude.json" 2>"$OUT/$id-claude.err" || echo "claude_exit=$?" >>"$OUT/$id-meta.txt"
  echo "claude_seconds=$(( $(date +%s) - t0 ))" >>"$OUT/$id-meta.txt"

  t0=$(date +%s)
  (cd "$clone" && bash "$SCRIPTS/codex-review.sh" "$CODEX_MODE" base "$COMPANION") \
    >"$OUT/$id-codex.txt" 2>"$OUT/$id-codex.err" || echo "codex_exit=$?" >>"$OUT/$id-meta.txt"
  echo "codex_seconds=$(( $(date +%s) - t0 ))" >>"$OUT/$id-meta.txt"
  echo "finished=$(date -u +%FT%TZ)" >>"$OUT/$id-meta.txt"
}

PIDS=()
cleanup() {
  local pid
  # ${arr[@]+...}: bash 3.2 (macOS) treats an empty array as unbound under set -u.
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  rm -rf "$WORK"
}
trap cleanup EXIT

KNOWN=()
IDS=()
SHAS=()
while IFS=$'\t' read -r id sha _fix; do
  [[ "$id" == "id" ]] && continue
  KNOWN+=("$id")
  if [[ $# -eq 0 ]] || [[ " $* " == *" $id "* ]]; then
    IDS+=("$id")
    SHAS+=("$sha")
  fi
done <"$HERE/fixtures.tsv"
for want in "$@"; do
  [[ " ${KNOWN[*]} " == *" $want "* ]] || { echo "ERROR: unknown fixture id: $want (known: ${KNOWN[*]})" >&2; exit 1; }
done
[[ ${#IDS[@]} -gt 0 ]] || { echo "ERROR: no matching fixtures" >&2; exit 1; }

# Each fixture has its own clone, so the runs share no lock or ref and can overlap.
for i in "${!IDS[@]}"; do
  run_one "${IDS[$i]}" "${SHAS[$i]}" &
  PIDS+=("$!")
done

failed=()
for i in "${!PIDS[@]}"; do
  wait "${PIDS[$i]}" || failed+=("${IDS[$i]}")
done
PIDS=()

if [[ ${#failed[@]} -gt 0 ]]; then
  echo "FAILED: ${failed[*]} — see $OUT/<id>-meta.txt and *.err" >&2
  exit 1
fi
echo "done: ${#IDS[@]} fixture(s) → $OUT"
