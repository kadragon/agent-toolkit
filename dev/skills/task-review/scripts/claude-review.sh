#!/usr/bin/env bash
# Headless Claude code review against a base branch, invoking a review skill,
# emitting the findings-JSON array to stdout.
#
# Purpose: keep a Claude engine in the review panel even when the runtime
# driving the cycle is NOT Claude (e.g. Codex). This is the mirror of
# agy-review.sh / codex-review.sh, which keep those engines in the panel when
# Claude drives. When Claude itself drives, Step 2-1 uses the in-process Agent
# tool instead (it inherits the live session model for free); this script is
# only the non-Claude-driver fallback.
#
# Requires the `claude` CLI to be installed AND authenticated in the caller's
# environment. If it is not, the caller records "Reviewers Skipped".
#
# Usage: claude-review.sh <base_branch> <slot_id>
#   slot_id: the review skill to invoke (e.g. "review", "security-review").
# Output: JSON array of findings on stdout — same contract as the 2-1 Agent
#         path, so Step 3 consolidation treats both identically.

set -euo pipefail

BASE_BRANCH="${1:?Usage: claude-review.sh <base_branch> <slot_id>}"
SLOT_ID="${2:?Usage: claude-review.sh <base_branch> <slot_id>}"

command -v claude >/dev/null 2>&1 || { echo "ERROR: claude CLI not found" >&2; exit 1; }

# Mirrors SKILL.md Step 2-1's reviewer prompt — keep the two in sync. The strict
# "JSON array and NOTHING else" instruction is what lets .result be parsed
# directly as the findings array.
PROMPT=$(cat <<EOF
Review changes on the current branch against ${BASE_BRANCH}.
1. git diff ${BASE_BRANCH}...HEAD --name-only
2. Invoke Skill "${SLOT_ID}" to review.
3. Return findings as a JSON array and NOTHING else — no prose, no code fence:
   [{"file":"...","line":N,"severity":"P0".."P3","confidence":0-100,"problem":"...","fix":"...","source":"${SLOT_ID}"}]
   confidence = certainty the issue is real in THIS code (not a pattern match). 100 = verified by reading actual code path.
If docs/design/{slug}.md exists for this branch's slug, also verify the diff fulfills its User Stories and Implementation/Testing Decisions and flag scope creep or missing requirements as additional findings.
Only flag issues introduced or made significantly worse by this branch's diff.
Do NOT flag: pre-existing issues, linter-owned style, generated/vendored files, speculative concerns, >5 style nits.
If there are no findings, return [].
EOF
)

# --permission-mode plan makes the headless session structurally read-only: it
# can still read the diff and files (git diff, Read) but cannot Edit/Write or
# run mutating commands. A review must never touch the tree — without this, a
# headless session that misreads its task (or trips the target repo's hooks) can
# create/modify files instead of just reporting findings.
#
# Do NOT pass --model: under a non-Claude driver there is no live session to
# inherit, so the CLI's configured default model is the intended choice.
RAW=""
status=0
RAW=$(claude -p --permission-mode plan --output-format json "$PROMPT") || status=$?
if [ "$status" -ne 0 ]; then
  printf '%s\n' "${RAW:-claude CLI exited $status with no stdout}" >&2
  exit "$status"
fi

# --output-format json wraps the run in an envelope; .result holds the model's
# text output (the JSON array). Fall back to the raw payload if jq is missing or
# the field is absent, then strip an optional ```json code fence.
RESULT=$(jq -r '.result // empty' <<<"$RAW" 2>/dev/null || true)
[ -z "$RESULT" ] && RESULT="$RAW"
RESULT=$(printf '%s' "$RESULT" | sed -E 's/^```[a-zA-Z]*[[:space:]]*//; s/[[:space:]]*```$//')

emit_if_array() { jq -e 'type == "array"' <<<"$1" >/dev/null 2>&1 && { printf '%s\n' "$1"; return 0; }; return 1; }

# Prefer the clean case: the whole result is the array. If not — a headless
# session can wrap the array in prose (e.g. a repo Stop hook injects a nudge the
# model answers before re-emitting JSON) — recover the outermost [...] block and
# revalidate. Only if BOTH fail do we surface the raw text and return [], so a
# parse miss reads as a diagnosable warning rather than a silent "0 findings".
if emit_if_array "$RESULT"; then
  exit 0
fi
EXTRACTED=$(printf '%s' "$RESULT" | tr '\n' ' ' | grep -oE '\[.*\]' | tail -1 || true)
if [ -n "$EXTRACTED" ] && emit_if_array "$EXTRACTED"; then
  exit 0
fi
printf 'WARN: claude review did not return a parseable JSON array:\n%s\n' "$RESULT" >&2
echo '[]'
