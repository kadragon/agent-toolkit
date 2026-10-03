#!/usr/bin/env bash
# Commit files and optionally push / create a PR.
#
# Usage:
#   commit-and-push.sh --message <text> [--files "f1 f2 ..."] [--no-push] [--pr] [--base <branch>]
#   commit-and-push.sh --message <text> --prefer-staged [--no-push] [--pr] [--base <branch>]
#   commit-and-push.sh --message <text> --no-commit [--pr] [--base <branch>]
#   commit-and-push.sh --verify-head
#
# Flags:
#   --message <text>   Commit message (required, except with --verify-head)
#   --verify-head      Commit nothing; run commit-guard against the existing HEAD
#                      and report. For a clean resumed branch, where there is no
#                      new commit to guard but HEAD is still about to be pushed
#                      or merged.
#   --files <list>     Space-separated file paths to stage (default: auto-detect via changed-files.sh)
#   --prefer-staged    A non-empty index is committed exactly as staged, staging
#                      nothing more. An empty index on a branch ahead of --base
#                      runs --verify-head instead (dirt in unstaged_left); one
#                      with nothing ahead falls back to auto-detect.
#                      For a caller that staged its reviewed in-scope files, so a
#                      stray edit present beforehand stays out (PR #291).
#   --no-push          Commit locally only; skip push and PR creation
#   --no-commit        Stage and commit nothing, even on a dirty tree; guard and
#                      push/PR the existing HEAD. For a caller that has already
#                      committed (the review cycle's hub PR block), so unrelated
#                      dirty files cannot ride into the pushed branch (PR #277).
#                      --message still supplies the PR title/body.
#   --pr               Create a PR after pushing
#   --base <branch>    Base branch for the PR and the --prefer-staged ahead check (default: main)
#
# Output: JSON to stdout
#   {commit_hash, committed, pushed, pr_number, pr_url, guard_skipped, unstaged_left}
#   unstaged_left lists changed/untracked files a --prefer-staged run left out ([] otherwise).
#   committed=false means nothing was staged (a clean tree, or --no-commit) and HEAD
#   was pushed/PR'd as-is (re-run against an already-committed branch). That path still runs
#   commit-guard against HEAD's own subject, so a branch committed outside this
#   harness cannot reach a PR or main unchecked.
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
NO_COMMIT=false
PREFER_STAGED=false
CREATE_PR=false
VERIFY_HEAD=false
BASE_BRANCH="main"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --message) MESSAGE="$2"; shift 2 ;;
    --files)   FILES="$2";   shift 2 ;;
    --no-push) NO_PUSH=true; shift ;;
    --no-commit) NO_COMMIT=true; shift ;;
    --prefer-staged) PREFER_STAGED=true; shift ;;
    --pr)      CREATE_PR=true; shift ;;
    --verify-head) VERIFY_HEAD=true; shift ;;
    --base)    BASE_BRANCH="$2"; shift 2 ;;
    *) echo "ERROR: Unknown flag: $1" >&2; exit 1 ;;
  esac
done

if [ -z "$MESSAGE" ] && [ "$VERIFY_HEAD" != "true" ]; then
  echo "ERROR: --message is required" >&2
  exit 1
fi
if [ "$NO_COMMIT" = "true" ] && { [ "$NO_PUSH" = "true" ] || [ -n "$FILES" ]; }; then
  echo "ERROR: --no-commit cannot be combined with --no-push or --files" >&2
  exit 1
fi
if [ "$PREFER_STAGED" = "true" ] && { [ "$NO_COMMIT" = "true" ] || [ -n "$FILES" ]; }; then
  echo "ERROR: --prefer-staged cannot be combined with --no-commit or --files" >&2
  exit 1
fi
STAGED_ONLY=false
if [ "$PREFER_STAGED" = "true" ] && ! git diff --cached --quiet; then
  STAGED_ONLY=true
fi
# An empty index on a branch already ahead of the base is a resumed cycle: its
# reviewed work is committed, so auto-detect would only sweep in strays (PR #292).
# Verify HEAD instead and report the dirt. A branch with nothing ahead, or a base
# that resolves neither remotely nor locally, keeps auto-detect — a standalone
# first run that never staged still needs its commit.
UNSTAGED_LEFT=""
if [ "$PREFER_STAGED" = "true" ] && [ "$STAGED_ONLY" != "true" ]; then
  BASE_REF=""
  for ref in "origin/$BASE_BRANCH" "$BASE_BRANCH"; do
    if git rev-parse --verify -q "$ref^{commit}" >/dev/null; then
      BASE_REF="$ref"
      break
    fi
  done
  if [ -n "$BASE_REF" ] && [ "$(git rev-list --count "$BASE_REF..HEAD")" -gt 0 ]; then
    VERIFY_HEAD=true
    UNSTAGED_LEFT=$(bash "$SCRIPT_DIR/changed-files.sh")
  fi
fi

# --- commit-guard ---
# The PreToolUse(Bash) hook cannot see commits made here: the agent's Bash command
# is `bash <this script> ...`, so guard.py's _is_git_commit() finds no git+commit
# token pair and passes. Both shipped guards (protected branch, [TYPE] message)
# were therefore inert on this — the repo's primary — commit path. Call the same
# policy directly instead, via guard.py's --precommit-check CLI mode.
#
# Fail-open on a missing guard (partial install, moved path) or no interpreter,
# but NEVER silently: a guard that vanished is the same invisible gap this call
# exists to close, so it warns on stderr and surfaces guard_skipped=true in JSON.
# Sets GUARD_SKIPPED; exits 1 on a rejection. $1 is the message to judge, $2 the
# noun for the warning ("committing" / "publishing HEAD").
GUARD_SKIPPED=false
run_commit_guard() {
  guard_message="$1"
  guard_action="$2"
  GUARD="$SCRIPT_DIR/../../../hooks/commit-guard/guard.py"
  # Resolve the interpreter rather than hardcoding python3. Windows installs
  # routinely ship only `python` — dev/hooks.json's own commit-guard entry uses
  # `commandWindows: python ...` for exactly that reason, and
  # hooks/session-start/run.sh already resolves the same way. Hardcoding python3
  # here would leave every task-review-cycle commit unguarded on those installs
  # while reporting a clean run.
  PY=$(command -v python3 || command -v python || true)
  if [ ! -f "$GUARD" ]; then
    echo "WARNING: commit-guard not found at $GUARD — $guard_action UNCHECKED" >&2
    GUARD_SKIPPED=true
    return 0
  fi
  if [ -z "$PY" ]; then
    echo "WARNING: no python3/python interpreter — commit-guard skipped, $guard_action UNCHECKED" >&2
    GUARD_SKIPPED=true
    return 0
  fi
  # Exit 2 = guard rejection; exit 1 = we called it wrong. Both must stop the
  # commit, but only the former is the caller's message/branch to fix.
  GUARD_RC=0
  GUARD_OUT=$("$PY" "$GUARD" --precommit-check --message "$guard_message" --cwd "$PWD" 2>&1) || GUARD_RC=$?
  if [ "$GUARD_RC" -ne 0 ]; then
    jq -n --arg e "commit blocked by commit-guard: $GUARD_OUT" '{error: $e}' >&2
    exit 1
  fi
}

# --- Verify-head only: guard the existing HEAD, commit and publish nothing ---
# A clean resumed branch has no new commit to guard, but its HEAD is still about
# to be pushed or merged, and it may have been committed outside this harness
# (by hand, or by a tool whose PreToolUse hook cannot see it). Without this the
# resume path is the one route by which an unchecked commit reaches a PR or main.
if [ "$VERIFY_HEAD" = "true" ]; then
  run_commit_guard "$(git log -1 --format=%s)" "publishing HEAD"
  UNSTAGED_JSON=$(printf '%s' "$UNSTAGED_LEFT" | jq -R . | jq -sc 'map(select(length > 0))')
  jq -n --arg hash "$(git rev-parse HEAD)" --argjson guard_skipped "$GUARD_SKIPPED" \
    --argjson unstaged_left "$UNSTAGED_JSON" \
    '{commit_hash: $hash, committed: false, resumed: true, pushed: false,
      pr_number: null, pr_url: null, guard_skipped: $guard_skipped,
      unstaged_left: $unstaged_left}'
  exit 0
fi

# --- Resolve file list ---
# --no-commit leaves FILES empty, so the clean-tree branch below publishes HEAD as-is;
# a staged-only commit never stages, so it skips detection too.
if [ -z "$FILES" ] && [ "$NO_COMMIT" != "true" ] && [ "$STAGED_ONLY" != "true" ]; then
  FILES=$(bash "$SCRIPT_DIR/changed-files.sh" | tr '\n' ' ')
fi
FILES=$(echo "$FILES" | tr -s '[:space:]' ' ' | sed 's/^ //;s/ $//')

# --- Stage and commit ---
# A clean tree on a push/PR run means the branch is already committed (e.g. a
# re-run of the review cycle) — skip the commit and push/PR the existing HEAD.
# A clean tree on a --no-push run has nothing to do at all, so that stays fatal.
COMMITTED=false
if [ "$STAGED_ONLY" = "true" ]; then
  run_commit_guard "$MESSAGE" "committing"
  if ! COMMIT_OUT=$(git commit -m "$MESSAGE" 2>&1); then
    jq -n --arg e "commit failed: $COMMIT_OUT" '{error: $e}' >&2
    exit 1
  fi
  COMMITTED=true
  # Report what stayed out, so a partial index cannot silently drop reviewed work.
  UNSTAGED_LEFT=$(bash "$SCRIPT_DIR/changed-files.sh")
elif [ -n "$FILES" ]; then
  run_commit_guard "$MESSAGE" "committing"
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
else
  # Clean tree on a push/PR run: nothing is committed here, but this call still
  # publishes HEAD, which may have been committed outside this harness.
  run_commit_guard "$(git log -1 --format=%s)" "publishing HEAD"
fi
COMMIT_HASH=$(git rev-parse HEAD)
UNSTAGED_JSON=$(printf '%s' "$UNSTAGED_LEFT" | jq -R . | jq -sc 'map(select(length > 0))')

if [ "$NO_PUSH" = "true" ]; then
  jq -n --arg hash "$COMMIT_HASH" --argjson committed "$COMMITTED" \
    --argjson guard_skipped "$GUARD_SKIPPED" --argjson unstaged_left "$UNSTAGED_JSON" \
    '{commit_hash: $hash, committed: $committed, pushed: false, pr_number: null,
      pr_url: null, guard_skipped: $guard_skipped, unstaged_left: $unstaged_left}'
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
  --argjson unstaged_left "$UNSTAGED_JSON" \
  '{
    commit_hash: $hash,
    committed: $committed,
    pushed: true,
    pr_number: ($pr_number | if . == "" then null else . end),
    pr_url: ($pr_url | if . == "" then null else . end),
    guard_skipped: $guard_skipped,
    unstaged_left: $unstaged_left
  }'
