#!/usr/bin/env bash
# Launch Antigravity (agy) CLI code review against a base branch.
#
# Usage: agy-review.sh <base_branch>
# Output: Antigravity's review text (exit 0) or a quota-exhausted JSON record (exit 75).

set -euo pipefail

BASE_BRANCH="${1:?Usage: agy-review.sh <base_branch>}"

if ! BASE_SHA=$(git rev-parse --verify --quiet --end-of-options "$BASE_BRANCH^{commit}"); then
  echo "ERROR: comparison ref $BASE_BRANCH not found — Antigravity review not run." >&2
  exit 1
fi
HEAD_SHA=$(git rev-parse --verify 'HEAD^{commit}')
DIFF_REVS=("$BASE_SHA...$HEAD_SHA")

# Gate on empty diff up front so we don't spin up agy for nothing.
# The diff itself is fetched by agy via its shell tool — embedding large
# diffs directly in the prompt can overload context.
if ! CHANGED_FILES=$(git diff --name-only "${DIFF_REVS[@]}" -- 2>/dev/null); then
  DIFF_REVS=("$BASE_SHA" "$HEAD_SHA")
  if ! CHANGED_FILES=$(git diff --name-only "${DIFF_REVS[@]}" --); then
    echo "ERROR: git diff against ${BASE_BRANCH} failed — Antigravity review not run." >&2
    exit 1
  fi
fi
if [ -z "$CHANGED_FILES" ]; then
  echo "No changes detected against ${BASE_BRANCH} — skipping Antigravity review." >&2
  exit 0
fi
command -v jq >/dev/null 2>&1 || { echo "ERROR: jq is required for Antigravity review." >&2; exit 1; }

REPO_ROOT=$(git rev-parse --show-toplevel)
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
source "$SCRIPT_DIR/review-guidance.sh"
GUIDANCE=$(review_repo_guidance "$HEAD_SHA")

REVIEW_PROMPT="You are reviewing a proposed code change in the repository at ${REPO_ROOT}.

## How to obtain the diff

Use your shell tool to compare commit ${HEAD_SHA} on ${CURRENT_BRANCH} against ${BASE_BRANCH} at ${BASE_SHA}. Use these commit IDs throughout because the refs and checkout may move. Your shell tool runs outside the repository directory, so every git command MUST use \`git -C ${REPO_ROOT}\`. Run these commands yourself — do NOT ask the user for the diff:

1. \`git -C ${REPO_ROOT} diff --stat ${DIFF_REVS[*]} --\` — get an overview of which files changed.
2. \`git -C ${REPO_ROOT} diff ${DIFF_REVS[*]} -- <path>\` — inspect specific files. Prefer reviewing per-file or per-hunk instead of loading the whole diff at once if the change is large.
3. \`git -C ${REPO_ROOT} log --oneline ${BASE_SHA}..${HEAD_SHA}\` — understand commit intent.
4. For full file contents, use \`git -C ${REPO_ROOT} show ${HEAD_SHA}:<path>\` or \`git -C ${REPO_ROOT} show ${BASE_SHA}:<path>\`.

## Scope: read-only review

This is a static review. Use only git commands and file reads. Do NOT run tests, builds, linters, validation scripts, or any command in the background — CI and other reviewers already cover execution, and waiting on those runs delays this review past the point anyone reads it. Do not modify any file.

## What to flag

Flag issues introduced or worsened by this change. Also report real bugs in code the diff touches or reads if you verify the same bug exists at the base and the diff did not worsen it. For a verified pre-existing bug, name the everyday path with its failing condition or cite reproduction evidence from real use if available. With neither, treat the bug as a PR comment only.

Each finding must be:
- A concrete bug, security vulnerability, or performance regression with a clear reproduction scenario
- Discrete and actionable (one issue per finding, not vague observations)
- Something the author would fix if made aware of it

Prefer no finding over a weak finding. Do not pad the review with style nits, praise, or generic advice.

## Priority levels

Tag each finding:
- [P0] Blocking — data loss, security hole, crash in production
- [P1] Urgent — incorrect behavior under normal conditions that must be fixed before merge
- [P2] Normal — actionable non-blocking defects. If introduced here, fix in the PR or leave a PR comment without filing an issue.
- [P3] Low — at most a PR comment, including nits. Never file an issue.
- [pre_existing] Advisory — a verified bug already present at the base and not worsened by the change. Include this tag alongside its P0–P3 priority to show impact.

## Comment format

For each finding, provide:
1. **Priority tag and title** (one line, imperative mood)
2. **file:line** reference
3. **Why** it is a problem (1 paragraph max, matter-of-fact tone)
4. **When** it manifests (specific inputs, environments, or conditions)
5. **Suggested fix** (concrete code snippet if applicable, 3 lines max)

## Output structure

List findings ordered by priority (P0 first, pre_existing last). After all findings, add:
- **Overall verdict**: \"LGTM\" if no P0/P1 issues introduced or worsened by the diff, or \"Changes Requested\" with a 1-sentence explanation. Pre-existing findings are advisory at every priority.
- If no issues worth flagging exist, say so plainly — do not invent findings.
${GUIDANCE}"

# --print-timeout is agy's ONLY deadline. Nothing outside this script bounds it: the cycle
# launches it in the background and moves on without waiting (SKILL.md Step 2), and
# run_in_background enforces no timeout of its own. Keep the cap here so a slow run fails
# with a reportable reason instead of running on with no result anyone reads. 15m stays:
# a lower cap only kills runs the pre-merge reclaim could still collect, and the author's 32
# logged runs (2026-10-16..24) maxed at 574s, so it never fired (late-source-reclaim.md).
# Capture stdout and stderr separately so we can detect empty output and report
# the failure reason (Windows: agy exits non-zero before producing output, which
# set -euo pipefail would otherwise swallow silently).
AGY_OUT=$(mktemp)
AGY_ERR=$(mktemp)
trap 'rm -f "$AGY_OUT" "$AGY_ERR"' EXIT

# --- durable result sidecar --------------------------------------------------
#
# Each invocation owns its sidecars, including simultaneous invocations on the same commit.
START_EPOCH=$(date +%s 2>/dev/null || printf '0')
RESULT_DIR="${AGY_REVIEW_RESULT_DIR:-$(git rev-parse --absolute-git-dir)/agy-review}"
RUN_DIR=$(umask 077; mkdir -p "$RESULT_DIR/$HEAD_SHA" &&
  cd "$RESULT_DIR/$HEAD_SHA" && mktemp -d "$PWD/run.XXXXXX") 2>/dev/null || RUN_DIR=""
PENDING_FILE="$RUN_DIR/review.pending"
REVIEW_FILE="$RUN_DIR/review.txt"
META_FILE="$RUN_DIR/review.meta"
if [ -n "$RUN_DIR" ] && ( umask 077
    printf 'pid=%s\nstarted_at=%s\nbranch=%s\nbase=%s\nbase_sha=%s\nhead_sha=%s\n' \
      "$$" "$START_EPOCH" "$CURRENT_BRANCH" "$BASE_BRANCH" "$BASE_SHA" "$HEAD_SHA" >"$PENDING_FILE"
  ) 2>/dev/null; then
  printf 'agy result directory: %s\n' "$RUN_DIR" >&2
else
  RUN_DIR=""
  echo "WARN: agy result dir unavailable — this review will not be persisted for a late reclaim" >&2
fi

# One line per finished run, appended and never rotated — the evidence for the --print-timeout
# cap (references/late-source-reclaim.md). Same shape as codex-review.sh's log minus `mode`:
# elapsed alone cannot separate "agy is slow" from "that diff was unusual", so diff size rides
# beside it, measured against HEAD_SHA because the cycle keeps committing while agy runs.
append_timing() {
  local status="$1" elapsed="$2" shortstat files ins del ts
  shortstat=$(git diff --shortstat "${DIFF_REVS[@]}" -- 2>/dev/null || printf '')
  files=$(printf '%s' "$shortstat" | grep -o '[0-9]\{1,\} file' | grep -o '[0-9]\{1,\}' || true)
  ins=$(printf '%s' "$shortstat" | grep -o '[0-9]\{1,\} insertion' | grep -o '[0-9]\{1,\}' || true)
  del=$(printf '%s' "$shortstat" | grep -o '[0-9]\{1,\} deletion' | grep -o '[0-9]\{1,\}' || true)
  ts=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || printf 'unknown')
  ( umask 077
    printf '%s elapsed=%ss status=%s files=%s lines=%s branch=%s\n' \
      "$ts" "$elapsed" "$status" "${files:-0}" "$(( ${ins:-0} + ${del:-0} ))" "$CURRENT_BRANCH" \
      >>"$RESULT_DIR/timings.log"
  ) 2>/dev/null || true
  return 0
}

# Review file first, meta second, pending removed last — a reader that sees `.meta` is
# guaranteed the review file beside it is whole.
publish_result() {
  local status="$1" reset="${2:-}" review_file="" now
  [ -n "$RUN_DIR" ] || return 0
  now=$(date +%s 2>/dev/null || printf '0')
  append_timing "$status" "$((now - START_EPOCH))"
  if [ "$status" = "ok" ] && ( umask 077; cp "$AGY_OUT" "$REVIEW_FILE.tmp.$$" ) 2>/dev/null &&
    mv -f "$REVIEW_FILE.tmp.$$" "$REVIEW_FILE" 2>/dev/null; then
    review_file="$REVIEW_FILE"
  fi
  ( umask 077
    { cat "$PENDING_FILE"
      printf 'status=%s\nexit_code=%s\nfinished_at=%s\nelapsed_seconds=%s\nreview_file=%s\n' \
        "$status" "$AGY_EXIT" "$now" "$((now - START_EPOCH))" "$review_file"
      if [ -n "$reset" ]; then
        printf 'reset=%s\n' "$reset"
      fi
    } >"$META_FILE.tmp.$$" && mv -f "$META_FILE.tmp.$$" "$META_FILE"
  ) 2>/dev/null && rm -f "$PENDING_FILE" 2>/dev/null ||
    echo "WARN: could not persist the agy result to $META_FILE" >&2
  return 0
}

AGY_EXIT=0
NO_COLOR=1 TERM=dumb agy -p "$REVIEW_PROMPT" \
  --dangerously-skip-permissions \
  --add-dir "$REPO_ROOT" \
  --print-timeout 15m >"$AGY_OUT" 2>"$AGY_ERR" || AGY_EXIT=$?

# agy can print a retry's 429 before reporting a different terminal error.
TERMINAL_DIAGNOSTIC=""
if [ "$AGY_EXIT" -gt 0 ] && [ "$AGY_EXIT" -lt 124 ]; then
  TERMINAL_DIAGNOSTIC=$(awk '
    { sub(/\r$/, "") }
    !NF || /^[[:space:]]+at[[:space:]]/ { next }
    tolower($0) ~ /^[[:space:]]*((your[[:space:]]+)?(quota[[:space:]]+)?(will[[:space:]]+)?resets?[[:space:]]+(in|after|at)|retry[[:space:]]+(in|after)|retry-after:)/ {
      hint = $0
      next
    }
    { diagnostic = $0; prior_hint = hint; hint = "" }
    END {
      print diagnostic
      if (hint != "") print hint
      else if (prior_hint != "") print prior_hint
    }
  ' "$AGY_ERR")
fi

is_quota_failure() {
  local error="${1%%$'\n'*}"
  case "$error" in
    AGY_ERROR:\ *)
      jq -e '(.error_code | tostring) == "429" and (.code_kind == "http" or .status == "RESOURCE_EXHAUSTED")' \
        <<<"${error#AGY_ERROR: }" >/dev/null 2>&1
      ;;
    'API Error: {'*)
      jq -e '(.code // .statusCode // .error_code | tostring) == "429"' \
        <<<"${error#API Error: }" >/dev/null 2>&1
      ;;
    *)
      local prefix='^[[:space:]]*((API[[:space:]]+)?error:[[:space:]]*)?'
      local http='HTTP([[:space:]]+error)?[[:space:]:]+429\b|429([[:space:]]+(Too Many Requests|Resource (has been )?exhausted)\b|[[:space:]]*$)'
      local resource='RESOURCE_EXHAUSTED([[:space:]]+\(code[[:space:]]+429\)|[[:space:].]*$)'
      local message='(((individual|model|api|request|usage|your)[[:space:]]+)?quota|rate[[:space:]-]limit)[[:space:]]+((is|has been)[[:space:]]+)?(exhausted|exceeded|reached)\b|you[[:space:]]+(have[[:space:]]+)?(exhausted|exceeded|reached)[[:space:]]+your[[:space:]]+(quota|rate limit)\b'
      grep -Eiq "$prefix($http|$resource|$message)" <<<"$error"
      ;;
  esac
}

if is_quota_failure "$TERMINAL_DIAGNOSTIC"; then
  RESET_DURATION='(resets? (in|after)|retry (in|after))[[:space:]]*([0-9]+([.][0-9]+)?[[:space:]]*(hours?|minutes?|seconds?|hrs?|mins?|secs?|h|m|s)[[:space:]]*)+\b'
  RESET_TIME='resets? at[[:space:]]*[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+(Z|[+-][0-9]{2}:[0-9]{2})'
  RESET=$(grep -Eio -e "$RESET_DURATION" -e "$RESET_TIME" -e 'retry-after:[[:space:]]*[0-9]+\b' <<<"$TERMINAL_DIAGNOSTIC" \
    | sed -nE -e '1!d' -e 's/^[^0-9]*//' -e 's/[[:space:]]+$//' -e p || true)
  QUOTA_RESULT=$(jq -cn --arg reset "$RESET" '{agy_review:"quota-exhausted",reset:(if $reset == "" then null else $reset end)}')
  publish_result quota-exhausted "$RESET"
  cat "$AGY_ERR" >&2
  printf '%s\n' "$QUOTA_RESULT"
  exit 75
fi

if ! grep -q '[^[:space:]]' "$AGY_OUT"; then
  publish_result empty
  echo "agy returned empty output (exit: $AGY_EXIT) — review skipped" >&2
  if [ -s "$AGY_ERR" ]; then
    echo "agy stderr:" >&2
    cat "$AGY_ERR" >&2
  fi
  exit 1
fi

# agy wrote output but exited non-zero — output is likely truncated; treat as failure
# rather than silently using partial review content.
if [ "$AGY_EXIT" -ne 0 ]; then
  publish_result failed
  echo "agy exited $AGY_EXIT with partial output — review skipped" >&2
  if [ -s "$AGY_ERR" ]; then
    echo "agy stderr:" >&2
    cat "$AGY_ERR" >&2
  fi
  exit 1
fi

publish_result ok
cat "$AGY_OUT"

# Forward any agy stderr (warnings, auth notices, rate-limit messages) even on success.
# Must not be the script's last command as a bare `[ ... ] && ...` list: when stderr is
# empty the test fails, the list returns 1, and — being last — that becomes the script's
# exit status. The caller reads a non-zero exit as failure and prints its
# `{"agy_review":"failed"}` sentinel after a perfectly good review. Hence the explicit exit 0.
if [ -s "$AGY_ERR" ]; then
  cat "$AGY_ERR" >&2
fi

exit 0
