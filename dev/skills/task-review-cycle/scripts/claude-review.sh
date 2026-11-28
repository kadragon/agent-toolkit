#!/usr/bin/env bash
# Headless Claude code review against a base branch, invoking a review skill,
# emitting the findings-JSON array to stdout.
#
# Purpose: the Claude review slot, whichever runtime drives the cycle. This is
# the mirror of agy-review.sh / codex-review.sh. SKILL.md Step 2 calls it in the
# FOREGROUND under a Bash timeout, which is the whole point: the in-process Agent
# path this replaced had no timeout of its own, so a hung inner run — or one that
# finished while its completion notification was lost (upstream claude-code
# #49150, #58637, #68117) — stalled the cycle with no bound. A headless run also
# carries no session context, making it a stricter independent check than an
# in-process spawn, not a weaker one.
#
# Requires the `claude` CLI to be installed AND authenticated in the caller's
# environment. If it is not, the caller records "Reviewers Skipped".
#
# Usage: claude-review.sh <base_branch> [effort] [sprint_contract]
#   The review skill is fixed to "code-review" — SKILL.md Step 2 pins the Claude
#   slot to exactly one skill, so there is no slot argument. The optional effort
#   arg mirrors that step's escalation: the caller passes "high" when Step 1's
#   SECURITY_HIT floor capture is non-empty or the behavioral risk is material,
#   and nothing otherwise. The optional third
#   arg is the Sprint Contract; when non-empty the run also grades the diff
#   against it, which keeps that grading independent of the agent that wrote the
#   code. Grading is read-only judgment only — running the contract's lint/test
#   command stays with the orchestrator, both because --permission-mode plan
#   forbids it here and because that half is already the orchestrator's job.
# Usage (advisory): claude-review.sh <base_branch> --comments
# Output: JSON array on stdout; each run emits either code/contract or comment findings.

set -euo pipefail

BASE_BRANCH="${1:?Usage: claude-review.sh <base_branch> [effort | --comments] [sprint_contract]}"
SLOT_ID="code-review"
EFFORT="${2:-}"
CONTRACT="${3:-}"

command -v claude >/dev/null 2>&1 || { echo "ERROR: claude CLI not found" >&2; exit 1; }

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if [ "$EFFORT" = --comments ]; then
  RULES_FILE="$SCRIPT_DIR/../references/comment-rules.md"
  [ -f "$RULES_FILE" ] || { echo "ERROR: comment rules not found: $RULES_FILE" >&2; exit 1; }
  IFS= read -r -d '' COMMENT_RULES <"$RULES_FILE" || true
  PROMPT="Compare ${BASE_BRANCH}...HEAD and review only comments added or edited in that diff.
Use the rules below. Read-only: report, never edit. Do not invoke a code-review skill.
Return only a JSON array (empty when clean). For each finding include file, line, problem,
fix, severity P1, failure empty, verdict (delete, must-kill, suppression, constraint),
and \"source\":\"comments\". All these findings are advisory.

${COMMENT_RULES}"
else

# SKILL.md Step 2 delegates the whole reviewer prompt to this script, so this
# block is its only copy — there is no second prompt to keep in sync. The strict
# "JSON array and NOTHING else" instruction is what lets .result be parsed
# directly as the findings array.
# Read the heredoc straight into the variable rather than through
# PROMPT=$(cat <<EOF ...). Inside a command substitution, bash 3.2 does not treat
# heredoc content as literal: it scans the body for quotes, so the apostrophes
# below (run's, branch's) opened a quote that swallowed the rest of the file. The
# script then died at exit 127 running its own comments as commands — on macOS
# only, since bash 5 parses it correctly and CI runs Linux. read -d '' takes the
# body verbatim and returns non-zero at EOF, hence the || true under set -e.
IFS= read -r -d '' PROMPT <<EOF || true
Review changes on the current branch against ${BASE_BRANCH}.
List actionable defects introduced or worsened by the diff and concrete pre-existing bugs in code the diff touches or reads. For each one, give the file and line, why it is wrong, and how to show it fails. Leave out improvements, refactors and nits.
Treat introduced P0/P1 as merge blockers and introduced P2 as in-PR fixes or advisory PR comments without issue filing. P3 and nits never become queue items.
For a verified pre-existing bug, name the everyday path with its failing condition or cite reproduction evidence from real use if available. With neither, treat the bug as a PR comment only.
1. git diff ${BASE_BRANCH}...HEAD --name-only
2. Invoke Skill "${SLOT_ID}" with args "${EFFORT}" to review — the skill name is exactly \`${SLOT_ID}\`; the effort goes in the args field, never in the name. Empty args = default effort. Do not invoke any other review skill or command.
   The local skill can read repository-root REVIEW.md. Reuse that guidance when it did. If it did
   not read the root file and one exists, read it once and apply its failure criteria, nit cap,
   skip paths and file:line rules before returning findings. Do not reload guidance the skill already read
   or let it override review scope, read-only constraints or output format.
3. Return findings as a JSON array and NOTHING else — no prose, no code fence:
   [{"file":"...","line":N,"severity":"P0"|"P1"|"P2"|"pre_existing","confidence":0-100,"problem":"...","failure":"...","fix":"...","source":"${SLOT_ID}"}]
   severity: P0 = data loss, security hole, crash, or a broken contract; P1 = wrong behavior that must be fixed before merge; P2 = actionable non-blocking defect; pre_existing = a concrete bug already present at the base and not worsened by the diff (advisory).
   If severity is pre_existing, also include "priority":"P0"|"P1"|"P2"|"P3" based on impact. P3 is Low.
   confidence = certainty the issue is real in THIS code (not a pattern match). 100 = verified by reading actual code path.
   failure = how to show it fails: a concrete input or state and the wrong output or crash it produces, or the test or command that would fail. Required for every finding. If the reviewer gave none and you cannot name one, keep the finding with failure "" — never invent a scenario. For a design-doc finding below, failure names the User Story or decision the diff leaves unmet.
   Include every merge-blocking finding from \`${SLOT_ID}\`; never re-rank, re-judge, merge, summarize or drop a blocking finding. Include actionable P2 findings as well. Verify pre_existing findings against the base and include qualifying bugs you encounter even if the skill omitted them. \`[]\` means the reviewer ran and found nothing reportable; it never means you could not read its output.
If docs/design/{slug}.md exists for this branch's slug, also verify the diff fulfills its User Stories and Implementation/Testing Decisions and flag scope creep or missing requirements as additional findings.
Do NOT flag: linter-owned style, generated/vendored files, speculative concerns, style nits, or a request to add a guard, retry or validation for a state the diff itself shows no caller can reach (removing an existing guard is still flaggable).
If there are no findings, return [].
EOF

# The heredoc above is UNQUOTED, so it expands dollar signs and backticks. A
# Sprint Contract is caller-supplied text that legitimately carries both: a
# lint/test command, or a shell snippet inside an acceptance criterion. Appending
# it into that heredoc would therefore run command substitution taken from the
# contract, in this shell. Concatenate by parameter expansion instead, which
# substitutes the value and never re-parses it.
#
# Keep backticks, command-substitution punctuation and apostrophes out of the
# block below and out of this comment. Once the heredoc body above contains
# backticks, bash 3.2 mis-tracks quoting across the rest of the file and rejects
# it outright, while bash 5 on the CI runner accepts it — so this breaks on macOS
# where CI stays green. test_claude_review.py runs `bash -n` to catch it.
if [ -n "$CONTRACT" ]; then
  PROMPT="${PROMPT}

Then grade the diff against the Sprint Contract below. A criterion you can settle by reading the
diff, and that the diff does not meet, is a finding: severity P0, \"source\":\"contract\". Hunt for
ways the change fails such a criterion; record a pass only on evidence. A criterion that can only
be settled by RUNNING something is different: grade it against the \"Lint/test evidence\" line in
the contract when one is present, and otherwise leave it alone. Never report a criterion as unmet
merely because this session could not run it — that would block every merge. Append contract
findings to the SAME JSON array as the ${SLOT_ID} findings. Do NOT run the lint/test command named
in the contract — this session is read-only, and the orchestrator runs that command itself.

Sprint Contract:
${CONTRACT}"
fi

fi

# --permission-mode plan makes the headless session structurally read-only: it
# can still read the diff and files (git diff, Read) but cannot Edit/Write or
# run mutating commands. A review must never touch the tree — without this, a
# headless session that misreads its task (or trips the target repo's hooks) can
# create/modify files instead of just reporting findings.
#
# Do NOT pass --model: a headless run has no live session to inherit from, so
# the CLI's configured default model is the intended choice.
#
# stdin comes from a pipe under an agent Bash tool, where the CLI waits 3s for
# data that never arrives and warns on stderr. Redirect it: the prompt is an
# argument, so there is nothing to read.
RAW=""
status=0
RAW=$(claude -p --permission-mode plan --output-format json "$PROMPT" </dev/null) || status=$?
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
# revalidate. Only if BOTH fail do we surface the raw text and report the slot as
# unavailable: an unread run is a dead slot, and `[]` would consolidate as a clean
# Claude review — the failure mode the sentinel rule in SKILL.md Step 2 exists to stop.
if emit_if_array "$RESULT"; then
  exit 0
fi
EXTRACTED=$(printf '%s' "$RESULT" | tr '\n' ' ' | grep -oE '\[.*\]' | tail -1 || true)
if [ -n "$EXTRACTED" ] && emit_if_array "$EXTRACTED"; then
  exit 0
fi
printf 'WARN: claude review did not return a parseable JSON array:\n%s\n' "$RESULT" >&2
echo '{"code_review_slot":"inner-run-unavailable","detail":"claude-review.sh could not parse a findings array from the run output"}'
