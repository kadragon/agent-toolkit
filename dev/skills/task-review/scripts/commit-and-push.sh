#!/usr/bin/env bash
# Commit files and optionally push / create a PR.
#
# Usage:
#   commit-and-push.sh --message <text> [--files "f1 f2 ..."] [--no-push] [--pr] [--base <branch>]
#
# Flags:
#   --message <text>   Commit message (required)
#   --files <list>     Space-separated file paths to stage (default: auto-detect via changed-files.sh)
#   --no-push          Commit locally only; skip push and PR creation
#   --pr               Create a PR after pushing
#   --base <branch>    Base branch for the PR (default: main)
#
# Output: JSON to stdout
#   {commit_hash, committed, pushed, pr_number, pr_url, guard_skipped}
#   committed=false means the tree was clean and HEAD was pushed/PR'd as-is
#   (re-run against an already-committed branch).
#   guard_skipped=true means commit-guard could not be run (missing guard.py or
#   no python3) and the commit went through UNCHECKED — see the guard section below.
#
# Exit codes:
#   0  success
#   1  usage error, nothing to commit, commit/push failure, OR a commit-guard
#      rejection (protected branch / bad [TYPE] message). The JSON error on stderr
#      carries the guard's reason; fix the branch or the message, do not retry as-is.
#
# Guard outcomes are three, not two: it ALLOWS (commit proceeds), it REJECTS
# (exit 1, no commit), or it could not run at all. Only the last is fail-open, and
# only for a guard that is absent — a guard.py that exists but crashes exits
# non-zero and is treated as a rejection, so the stderr JSON carries a traceback
# instead of a guard reason. That is deliberate: a broken guard must not become a
# silent allow.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

MESSAGE=""
FILES=""
NO_PUSH=false
CREATE_PR=false
BASE_BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --message) MESSAGE="$2"; shift 2 ;;
    --files)   FILES="$2";   shift 2 ;;
    --no-push) NO_PUSH=true; shift ;;
    --pr)      CREATE_PR=true; shift ;;
    --base)    BASE_BRANCH="$2"; shift 2 ;;
    *) echo "ERROR: Unknown flag: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$MESSAGE" ]; then
  echo "ERROR: --message is required" >&2
  exit 1
fi

# --- Resolve file list ---
if [ -z "$FILES" ]; then
  FILES=$(bash "$SCRIPT_DIR/changed-files.sh" | tr '\n' ' ')
fi
FILES=$(echo "$FILES" | tr -s '[:space:]' ' ' | sed 's/^ //;s/ $//')

# --- Stage and commit ---
# A clean tree on a push/PR run means the branch is already committed (e.g. a
# re-run of the review cycle) — skip the commit and push/PR the existing HEAD.
# A clean tree on a --no-push run has nothing to do at all, so that stays fatal.
COMMITTED=false
GUARD_SKIPPED=false
if [ -n "$FILES" ]; then
  # `git add` treats a pathspec matching neither the worktree nor the index as
  # fatal, and that fatal aborts the WHOLE batch — the sibling modified files in
  # the same call stay unstaged too. task-next's pre-merge cleanup deletes
  # tasks.md whenever it empties, and changed-files.sh correctly reports the
  # deleted path, so once that deletion is staged the path matches nothing and
  # Step 1 dies with `fatal: pathspec 'tasks.md' did not match any files`.
  #
  # `git add -A -- $FILES` is NOT the fix (measured, git 2.50.1): -A changes
  # which *changes* are picked up, not whether an unmatched pathspec is fatal —
  # it fails identically. Nor is a plain worktree deletion the problem: plain
  # `git add -- <deleted-but-tracked>` already stages it. The only broken case is
  # a path in neither worktree nor index, which by definition has nothing left to
  # add, so dropping it from the pathspec list is both safe and sufficient — the
  # already-staged deletion rides into the commit untouched.
  #
  # Only that one case is suppressed. A path that matches nothing AND has no staged
  # deletion is a genuinely unknown path — a typo, or a stale entry in an
  # agent-supplied --files list — and it stays in the pathspec so git's own fatal
  # still fires. Dropping those too would turn a loud abort into a quietly
  # incomplete commit that then goes to review and merge.
  STAGE=()
  # Word-split is intentional here: FILES is a space-separated list of paths.
  # shellcheck disable=SC2086
  for f in $FILES; do
    if [ -e "$f" ] || [ -L "$f" ] || git ls-files --error-unmatch -- "$f" >/dev/null 2>&1; then
      STAGE+=("$f")
    elif [ -z "$(git diff --cached --name-only --diff-filter=D -- "$f")" ]; then
      STAGE+=("$f")
    fi
  done
  # Guard the expansion: bash 3.2 (macOS system bash) errors on "${arr[@]}" for
  # an empty array under `set -u`.
  if [ "${#STAGE[@]}" -gt 0 ]; then
    git add -- "${STAGE[@]}"
  fi
  # --- commit-guard ---
  # The PreToolUse(Bash) hook cannot see this commit: the agent's Bash command is
  # `bash <this script> ...`, so guard.py's _is_git_commit() finds no git+commit
  # token pair and passes. Both shipped guards (protected branch, [TYPE] message)
  # were therefore inert on this — the repo's primary — commit path. Call the same
  # policy directly instead, via guard.py's --precommit-check CLI mode.
  #
  # Fail-open on a missing guard (partial install, moved path), but NEVER silently:
  # a guard that vanished is the same invisible gap this call exists to close, so it
  # warns on stderr and surfaces guard_skipped=true in the output JSON.
  GUARD="$SCRIPT_DIR/../../../hooks/commit-guard/guard.py"
  if [ ! -f "$GUARD" ]; then
    echo "WARNING: commit-guard not found at $GUARD — committing UNCHECKED" >&2
    GUARD_SKIPPED=true
  elif ! command -v python3 >/dev/null 2>&1; then
    echo "WARNING: python3 not available — commit-guard skipped, committing UNCHECKED" >&2
    GUARD_SKIPPED=true
  else
    # Exit 2 = guard rejection; exit 1 = we called it wrong. Both must stop the
    # commit, but only the former is the caller's message/branch to fix.
    GUARD_RC=0
    GUARD_OUT=$(python3 "$GUARD" --precommit-check --message "$MESSAGE" --cwd "$PWD" 2>&1) || GUARD_RC=$?
    if [ "$GUARD_RC" -ne 0 ]; then
      jq -n --arg e "commit blocked by commit-guard: $GUARD_OUT" '{error: $e}' >&2
      exit 1
    fi
  fi
  # `git commit` prints its summary ("[branch hash] msg\n N files changed…") to
  # STDOUT, which would pollute the pure-JSON contract exactly like the new-branch
  # push tracking line did (see Push below). Command substitution already keeps
  # that summary out of the script's stdout on success; `2>&1` folds stderr into
  # the same capture so a failure is reported with full detail. Do NOT add
  # `>/dev/null` here (unlike the push handler): git's "nothing to commit" note
  # goes to stdout, so discarding stdout would blank out COMMIT_OUT on that exact
  # failure. set -e would otherwise abort on a failed commit with a raw non-zero
  # exit; this guard turns it into a structured JSON error, mirroring push.
  if ! COMMIT_OUT=$(git commit -m "$MESSAGE" 2>&1); then
    jq -n --arg e "commit failed: $COMMIT_OUT" '{error: $e}' >&2
    exit 1
  fi
  COMMITTED=true
elif [ "$NO_PUSH" = "true" ]; then
  echo '{"error": "No changed files detected — nothing to commit"}' >&2
  exit 1
fi
COMMIT_HASH=$(git rev-parse HEAD)

if [ "$NO_PUSH" = "true" ]; then
  jq -n --arg hash "$COMMIT_HASH" --argjson committed "$COMMITTED" \
    --argjson guard_skipped "$GUARD_SKIPPED" \
    '{commit_hash: $hash, committed: $committed, pushed: false, pr_number: null,
      pr_url: null, guard_skipped: $guard_skipped}'
  exit 0
fi

# --- Push ---
# stdout is a pure-JSON contract, but a first push of a new branch pollutes it:
# `git push -u` prints "branch '<x>' set up to track 'origin/<x>'." to STDOUT
# (the new-branch / PR-hint lines go to stderr). Command substitution captures
# stdout, so even a correct `RESULT=$(...)` caller gets that tracking line ahead
# of the JSON and jq exits 5 on the parse error. On a re-run the upstream is
# already set, no tracking line prints, and stdout is clean — which is why the
# failure looks intermittent and clears on retry. Route push output away from
# both streams on success (2>&1 >/dev/null: stdout→/dev/null, stderr→capture);
# surface it only on failure.
if ! PUSH_OUT=$(git push -u origin HEAD 2>&1 >/dev/null); then
  # Encode via jq: git error output routinely contains quotes/newlines that
  # would produce malformed JSON under raw interpolation.
  jq -n --arg e "push failed: $PUSH_OUT" '{error: $e}' >&2
  exit 1
fi

PR_NUMBER=""
PR_URL=""

if [ "$CREATE_PR" = "true" ]; then
  TITLE=$(printf '%s' "$MESSAGE" | head -n 1)
  BODY=$(printf '%s' "$MESSAGE" | tail -n +3)

  # hub.sh routes to gh (GitHub) or the Forgejo/Gitea REST API, and falls back
  # to the existing PR when one already exists for this branch (re-run).
  PR_JSON=$(bash "$SCRIPT_DIR/hub.sh" pr-create \
    --base "$BASE_BRANCH" \
    --title "$TITLE" \
    --body "$BODY" 2>/dev/null || echo '{}')
  PR_NUMBER=$(jq -r '.pr_number // ""' <<<"$PR_JSON")
  PR_URL=$(jq -r '.pr_url // ""' <<<"$PR_JSON")
fi

jq -n \
  --arg hash "$COMMIT_HASH" \
  --argjson committed "$COMMITTED" \
  --arg pr_number "$PR_NUMBER" \
  --arg pr_url "$PR_URL" \
  --argjson guard_skipped "$GUARD_SKIPPED" \
  '{
    commit_hash: $hash,
    committed: $committed,
    pushed: true,
    pr_number: ($pr_number | if . == "" then null else . end),
    pr_url: ($pr_url | if . == "" then null else . end),
    guard_skipped: $guard_skipped
  }'
