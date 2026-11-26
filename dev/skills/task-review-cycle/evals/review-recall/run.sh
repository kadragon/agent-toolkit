#!/usr/bin/env bash
# Review-recall run: all review slots on each fixture's original introducing diff.
# Full re-scoring adapted from https://claude.dev/blog/solving-code-review-at-anthropic/ (2026-10-15).
#
# Usage: run.sh <out-dir> [fixture-id ...]
#   out-dir      where the per-fixture findings, metadata and full-run fingerprint land
#   fixture-id   ids from fixtures.tsv (default: all); fixtures run in parallel
# Env:
#   REVIEW_RECALL_EFFORT  effort passed to claude-review.sh (default: medium). Pinned because
#                         an empty effort makes code-review reuse the caller's last typed level.
#
# Each fixture runs in its own throwaway clone holding only the introducing commit and its
# parent (depth-2 fetch by sha): the reviewer cannot reach the fix commit or this
# directory's gold table, and nothing in the source repo's refs is created or touched.
# The clone has branch `base` at the parent and `HEAD` at the introducing commit, then
# the production reviewers run against `base` — the same calls the cycle makes.
# One run per out-dir: a second run on the same out-dir is refused while the first is alive.
# Codex's stdout is head+tail truncated past CODEX_REVIEW_MAX_BYTES; a truncated arm is graded
# from the full review in <id>-codex-result/ (the codex-review.sh sidecar) instead.
# Exit 1 when any fixture failed to produce its outputs. Scoring is by hand against
# README.md → Fixtures; see RESULTS.md.
set -euo pipefail

OUT="${1:?Usage: run.sh <out-dir> [fixture-id ...]}"
shift
FULL_RUN=$#
EFFORT="${REVIEW_RECALL_EFFORT:-medium}"

HERE=$(cd "$(dirname "$0")" && pwd)
[[ -n "$HERE" ]] || { echo "ERROR: cannot resolve script dir" >&2; exit 1; }
SCRIPTS=$(cd "$HERE/../../scripts" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
FINGERPRINT=$(bash "$HERE/check-results.sh" --fingerprint)

# Preflight once, locally: only the Codex mode and companion path are needed, and a hub
# preflight per fixture would race `git fetch` on the source repo.
PREFLIGHT=$(cd "$REPO" && bash "$SCRIPTS/preflight.sh" --no-hub)
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")
COMPANION=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")
[[ -n "$CODEX_MODE" && "$CODEX_MODE" != "null" ]] || { echo "ERROR: preflight gave no codex_mode" >&2; exit 1; }

PIDS=()
WORK=""
LOCK=""
cleanup() {
  local pid
  # ${arr[@]+...}: bash 3.2 (macOS) treats an empty array as unbound under set -u.
  for pid in ${PIDS[@]+"${PIDS[@]}"}; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
  if [[ -n "$LOCK" ]]; then rm -rf "$LOCK"; fi
  if [[ -n "$WORK" ]]; then
    # A Windows reviewer broker can keep its clone directory open after finishing.
    rm -rf "$WORK" || printf 'WARN: could not remove all temporary fixture clones under %s\n' "$WORK" >&2
  fi
}
trap cleanup EXIT

mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
# Two runs on one out-dir would overwrite each other's reviewer outputs and interleave the meta
# files. mkdir is the atomic claim; a lock whose owner pid is gone is left by a killed run.
if ! mkdir "$OUT/.run.lock" 2>/dev/null; then
  HOLDER=$(cat "$OUT/.run.lock/pid" 2>/dev/null || true)
  if [[ -z "$HOLDER" ]]; then
    echo "ERROR: $OUT/.run.lock has no owner pid — remove it if no run is active" >&2
    exit 1
  fi
  if kill -0 "$HOLDER" 2>/dev/null; then
    echo "ERROR: another run.sh (pid $HOLDER) is writing to $OUT — use a separate out-dir" >&2
    exit 1
  fi
  rm -rf "$OUT/.run.lock"
  mkdir "$OUT/.run.lock" || { echo "ERROR: cannot take $OUT/.run.lock" >&2; exit 1; }
fi
LOCK="$OUT/.run.lock"
printf '%s\n' "$$" >"$LOCK/pid"
WORK=$(mktemp -d "${TMPDIR:-/tmp}/review-recall.XXXXXX")
[[ -d "$WORK" ]] || { echo "ERROR: mktemp failed" >&2; exit 1; }
rm -f "$OUT/fingerprint.txt"

run_reviewer() {
  local id="$1" name="$2" extension="$3" t0 status=0
  shift 3
  t0=$(date +%s)
  "$@" >"$OUT/$id-$name.$extension" 2>"$OUT/$id-$name.err" || status=$?
  printf '%s_exit=%s\n%s_seconds=%s\n' "$name" "$status" "$name" "$(( $(date +%s) - t0 ))" \
    >>"$OUT/$id-meta.txt"
  [[ "$status" -eq 0 && -s "$OUT/$id-$name.$extension" ]] || return 1
  if [[ "$extension" == json ]]; then
    jq -e 'type == "array"' "$OUT/$id-$name.$extension" >/dev/null
  else
    grep -q '[^[:space:]]' "$OUT/$id-$name.$extension"
  fi
}

# codex-review.sh emits head+tail past CODEX_REVIEW_MAX_BYTES, which would drop findings from the
# graded text, but it always leaves the whole review in its sidecar (branch `bench` → key `bench`).
adopt_codex_sidecar() {
  local id="$1" dir="$OUT/$1-codex-result"
  grep -q '^\[\.\.\. truncated by codex-review\.sh' "$OUT/$id-codex.txt" || return 0
  if grep -qx 'status=ok' "$dir/bench.meta" 2>/dev/null && [[ -s "$dir/bench.review.txt" ]]; then
    cp "$dir/bench.review.txt" "$OUT/$id-codex.txt"
    echo "codex_text=full-sidecar" >>"$OUT/$id-meta.txt"
    return 0
  fi
  echo "ERROR: $id codex output is truncated and its sidecar is incomplete" >&2
  return 1
}

run_one() {
  local id="$1" sha="$2"
  local full clone status=0
  full=$(git -C "$REPO" rev-parse --verify "${sha}^{commit}")
  clone="$WORK/$id"
  git init -q "$clone"
  git -C "$clone" -c protocol.version=2 fetch -q --depth=2 "$REPO" "$full"
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
    echo "codex_version=$(codex --version 2>/dev/null | head -1)"
    echo "agy_version=$(agy --version 2>/dev/null | head -1)"
    echo "started=$(date -u +%FT%TZ)"
  } >"$OUT/$id-meta.txt"

  cd "$clone"
  run_reviewer "$id" claude json bash "$SCRIPTS/claude-review.sh" base "$EFFORT" "" || status=1
  rm -rf "$OUT/$id-codex-result"
  run_reviewer "$id" codex txt env CODEX_REVIEW_RESULT_DIR="$OUT/$id-codex-result" \
    bash "$SCRIPTS/codex-review.sh" "$CODEX_MODE" base "$COMPANION" || status=1
  adopt_codex_sidecar "$id" || status=1
  run_reviewer "$id" agy txt bash "$SCRIPTS/agy-review.sh" base || status=1
  run_reviewer "$id" comments json bash "$SCRIPTS/claude-review.sh" base --comments || status=1
  echo "finished=$(date -u +%FT%TZ)" >>"$OUT/$id-meta.txt"
  return "$status"
}

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
if [[ "$FULL_RUN" -eq 0 ]]; then
  [[ "$(bash "$HERE/check-results.sh" --fingerprint)" == "$FINGERPRINT" ]] \
    || { echo 'ERROR: reviewer inputs changed during the run' >&2; exit 1; }
  printf 'Review recall fingerprint: %s\n' "$FINGERPRINT" >"$OUT/fingerprint.txt"
fi
echo "done: ${#IDS[@]} fixture(s) → $OUT"
