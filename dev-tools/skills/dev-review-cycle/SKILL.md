---
name: dev-review-cycle
description: >-
  Post-dev workflow — parallel reviews (Claude skills + Antigravity + Codex) → apply feedback → CI → merge. Trigger: "review cycle", "run review", "review and merge", "dev review", "리뷰 돌려줘", "리뷰 사이클", "리뷰 머지". --no-hub to skip GitHub ops for local review. NOT for review-only (no merge intent), code review discussions, or one-off reviews without committing.
---

# Dev Review Cycle

Post-dev workflow: creates PR, collects reviews from multiple sources, consolidates feedback, applies improvements — one continuous flow.

## Arguments

- `--no-hub` — Skip all GitHub ops: no push, no PR creation, no CI wait, no merge. Commits locally, collects reviews from local diff against base branch. Use when you want review feedback without publishing to GitHub.
- `--auto` — Skip user confirmation in Step 3. Apply all in-scope suggestions automatically and continue the workflow without pausing. Out-of-scope items are still recorded in `tasks.md`.

## Prerequisites

- Dev complete, all changes ready to commit.
- `--no-hub`: `gh` CLI auth not required.

## Setup: Pre-flight Checks and Repository Metadata

Run bundled preflight script to detect available tools and repo metadata in one step. Outputs JSON with all values needed throughout workflow.

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh [--no-hub]
```

Detects: `gh` auth status, Antigravity (agy) CLI, Codex (plugin or CLI mode), current branch, base branch, owner/repo, merge strategy. `--no-hub` skips remote/GitHub checks, detects base branch from local state only.

If `CLAUDE_PLUGIN_ROOT` is unset, stop immediately and report — all scripts depend on this variable.

If `has_errors` is `true`, stop and report errors.

Use returned JSON values (`no_hub`, `feature_branch`, `base_branch`, `owner_repo`, `agy_available`, `codex_available`, `codex_mode`, `codex_companion_path`, `merge_strategy`, `review_candidates`) in all subsequent steps. Prefer squash > merge > rebase for merge strategy.

## CRITICAL: Execution Model

Workflow MUST execute as single continuous flow. Transitions between steps automatic — **except Step 3**, where user confirmation required before applying changes (skipped when `--auto` is set).

After Step 5 (or directly after Step 3 if no changes needed), proceed through CI wait, merge, local cleanup without pausing.

## Workflow

### Step 0: Ensure Feature Branch

Before creating PR, check if on base branch (e.g., `main`). If so, create new feature branch automatically — do NOT ask user for branch name.

Generate branch name autonomously from staged/unstaged changes:

1. Inspect `git diff` and `git status` to understand what changed. If both return empty (clean working tree, all changes already committed), derive the slug from `git log --oneline -3` — use the most recent commit message as the source.
2. Derive short slug branch name (e.g., `feat/login-validation`, `fix/null-handler`, `refactor/cleanup-utils`). Keep the slug short — 2–4 words max, no verbose descriptions.
3. Create and switch immediately:
   ```bash
   git checkout -b <generated-branch-name>
   ```

If already on a non-base branch, skip this step.

### Step 1: Commit (and Create PR unless `--no-hub`)

Determine the commit message yourself:

- If you have context from recent development or Step 0's diff, use it directly.
- Otherwise run `git diff --stat HEAD` to understand scope, and `git log --oneline -5` to match the project's commit style.

The file list is auto-detected by the commit script — no need to collect it yourself. (Step 5 uses explicit `--files` instead: by then, unrelated files may be staged from review application and auto-detection would include them.)

**When `--no-hub` is set:**

```bash
RESULT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --no-push \
  --message "${COMMIT_MESSAGE}")
echo "$RESULT"
```

Immediately proceed to Step 2 after the script succeeds.

**When `--no-hub` is NOT set:**

```bash
RESULT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --pr \
  --base "${BASE_BRANCH}" \
  --message "${COMMIT_MESSAGE}")
echo "$RESULT"
```

Extract `pr_number` and `pr_url` from the JSON output (`jq -r '.pr_number'`, `jq -r '.pr_url'`). If the script exits non-zero, stop and report the error. If `pr_number` is null but `pr_url` is non-null, extract the number from the URL: `basename $pr_url`. If both are null, halt with error — do not proceed.

**Do NOT pause or ask the user after PR creation.** Immediately proceed to Step 2.

### Step 2: Collect Reviews

Collect reviews from multiple sources. Launch all available sources in parallel using background tasks.

#### 2-1: Claude Skill Reviewers (1–N parallel sub-agents)

Use `review_candidates` from preflight output to dynamically select and launch relevant review skills.

**Selection procedure (do this inline — no extra Agent tool call):**

1. Get and store the full branch diff — this becomes the authoritative scope reference for Step 3:
   ```bash
   CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)
   ```
   Do NOT use `git diff HEAD` (last commit only). The branch may have multiple commits.
2. Read `review_candidates` from preflight JSON (list of `{id, kind, description}`).
3. Apply these selection rules:
   - **Trivial-diff short-circuit** — Before proceeding, compute diff size: count the files in `CHANGED_FILES` and read line delta from `git diff "${BASE_BRANCH}...HEAD" --shortstat`. If ≤ 10 changed lines AND ≤ 3 files AND none of the changed file paths contain security-related patterns (auth, crypto, secret, permission, network, env) → launch exactly 1 general reviewer (highest-priority candidate per rules below). Record all other candidates in 'Reviewers Skipped' with reason "trivial diff — single reviewer sufficient". A security-path hit overrides this short-circuit regardless of diff size.
   - **Always include** one general-purpose code reviewer if available. Priority order: `pr-review-toolkit:review-pr` > `review`. Note: `code-review` (kind=command) requires a GitHub PR to exist — skip it when `--no-hub` is set or no PR has been created yet.
   - **Include `security-review`** only if the diff touches files related to auth, crypto, secrets, permissions, network, or environment variables.
   - **Skip `caveman:caveman-review`** by default — it produces style-compressed output that duplicates general review signal. Include only if the user explicitly requests caveman review.
   - **Cap at 4 total** claude-skill sub-agents to prevent runaway context cost.
   - For any remaining candidates not selected, record the reason. Surface them to the user in Step 3 under a "Reviewers Skipped" note in the consolidation output (e.g., "out of scope for this diff", "exceeds cap").

4. For each selected candidate, launch one Agent tool call with `run_in_background: true`. Do NOT pass `subagent_type`. Use `model` from the candidate's metadata (`candidate.model`): `opus` for security-related reviewers, `sonnet` for all others. Prompt structure for all kinds:

```
Agent tool parameters:
  description: "Review via ${SKILL_ID} against ${BASE_BRANCH}"
  model: "${CANDIDATE_MODEL}"  # from candidate.model in preflight output
  run_in_background: true
  prompt: |
    Review the changes on branch ${FEATURE_BRANCH} against ${BASE_BRANCH}.
    1. Run `git diff ${BASE_BRANCH}...HEAD --name-only` to list changed files.
    2. Invoke the Skill tool with skill="${SKILL_ID}" to perform the review.
       - For kind="skill": the skill accepts a git diff context; pass it directly.
       - For kind="command" with id="code-review": also pass ${PR_NUMBER} as args
         (code-review uses gh pr commands internally and requires a PR number).
       - For kind="builtin": invoke exactly like any other skill.
    3. Return findings as a list: each line = file:line, severity (P0-P3), description, fix.
       Tag each finding with source="${SKILL_ID}".
    IMPORTANT: Only flag issues that were **introduced or made significantly worse** by
    this PR's changes. Do NOT flag pre-existing issues — whether in untouched files or in
    unchanged lines within touched files.
```

#### 2-2: Antigravity (agy) Review

Skip if `agy_available` is false from pre-flight. Invoke via Bash tool with `run_in_background: true` and `timeout: 600000`:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/agy-review.sh ${BASE_BRANCH} \
  || echo '{"agy_review":"failed"}' >&2
```

Wrap each background script invocation so failure is caught and logged, not silently dropped. If the command fails, proceed without this review.

#### 2-3: Codex Review

Skip if `codex_available` is false from pre-flight. Invoke via Bash tool with `run_in_background: true` and `timeout: 600000`:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/codex-review.sh ${CODEX_MODE} ${BASE_BRANCH} ${CODEX_COMPANION_PATH} \
  || echo '{"codex_review":"failed"}' >&2
```

Wrap each background script invocation so failure is caught and logged, not silently dropped. If the command fails, proceed without this review.

#### Collecting Results

Launch all available sources in parallel. Allow up to 10 minutes (600000ms) per source. After all reviews are collected, immediately proceed to Step 3.

If all launched sources failed or returned no findings, fall back to inline review: check naming, error handling, and test coverage from the diff. Note in consolidation that all automated review sources failed.

### Step 3: Consolidate Reviews and Get User Approval

Read **`references/consolidation-guide.md`** now. Deduplicate, resolve conflicts, classify scope (in/out), and present a consolidated table following that procedure.

**Scope reference:** Use `CHANGED_FILES` from Step 2-1 as the authoritative file list. A finding is in-scope only if (a) its file appears in `CHANGED_FILES` AND (b) the issue was introduced or made significantly worse by this PR — not pre-existing. Pre-existing issues in changed files are out-of-scope unless this PR made them materially worse. Issues in unchanged files are always out-of-scope. Do not use `git diff HEAD` — that shows only the most recent commit and will incorrectly exclude files changed in earlier commits on this branch.

**If `--auto` is NOT set:** STOP here and ask the user for confirmation. The user may approve all, reject some, or change scope classifications before proceeding.

**If `--auto` is set:** Skip confirmation. Treat all in-scope suggestions as approved.

In both cases, complete these two steps in order before proceeding:

1. **Record backlog items** — Before touching any code, write to `tasks.md`: (a) all out-of-scope items, and (b) all in-scope P2/P3 items (readability, style, minor improvements). Format in `references/consolidation-guide.md`.
2. **Proceed to Step 4** — Apply only P0/P1 in-scope items (correctness bugs, concrete security risks, broken tests). P2/P3 items are already captured in `tasks.md`; do not apply them inline.

If no P0/P1 in-scope suggestions exist:
- If `tasks.md` was modified in Step 3 (P2/P3 or out-of-scope items recorded), skip Step 4 but still execute Step 5 to commit `tasks.md` before merging. Use `--files "tasks.md"` with a commit message describing the backlog update (e.g. `[PLAN] record review backlog from PR #N`).
- If `tasks.md` was NOT modified, skip Steps 4–5 entirely.

Step 6 (merge/push) still executes in either case unless `--no-hub` is set, in which case the workflow ends after the Step 5 commit (or after Step 3 if no commit was needed).

### Step 4: Apply Improvements

Apply accepted improvements to the codebase. Run tests after changes to verify nothing is broken. To find the test command: check `package.json` `scripts.test`, `Makefile` targets, `pytest.ini`, `pyproject.toml` (`[tool.pytest]` or `[tool.hatch]`), `go.mod`, `Cargo.toml`, or `build.gradle` / `./gradlew test`. If no test command is found, skip tests and note the omission in the Step 6 summary.

If tests fail after applying improvements, revert the broken change — use `git restore <files>` for unstaged changes; if already staged, run `git restore --staged <files> && git restore <files>`. Manually delete any newly created untracked files. Report which suggestion caused the failure and ask the user whether to skip it or attempt a different approach. Do not proceed to Step 5 with failing tests.

After improvements are applied and tests pass, immediately proceed to Step 5.

### Step 5: Commit (and Push unless `--no-hub`)

Determine the commit message yourself — you have full context from Step 4. List the exact files you modified in that step; pass them explicitly via `--files` to avoid accidentally staging unrelated changes. Before passing `--files`, run `git status --short` and confirm the list matches files you actually modified (including `tasks.md` if modified in Step 3). Silent omission of a file means uncommitted changes.

**When `--no-hub` is set:**

```bash
RESULT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --no-push \
  --files "${FILES_TO_STAGE}" \
  --message "${COMMIT_MESSAGE}")
echo "$RESULT"
```

After the script returns, skip Step 6 entirely. Report the review summary and applied improvements to the user. The workflow ends here.

**When `--no-hub` is NOT set:**

```bash
RESULT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --files "${FILES_TO_STAGE}" \
  --message "${COMMIT_MESSAGE}")
echo "$RESULT"
```

After the script returns, immediately proceed to Step 6.

### Step 6: Wait for CI and Merge (skip when `--no-hub`)

Before proceeding, confirm `PR_NUMBER`, `BASE_BRANCH`, `FEATURE_BRANCH`, and `MERGE_STRATEGY` are still in context. If the session is long and any value is unclear, recover via `gh pr view` (for PR number/branch) or re-run preflight.

Read **`references/ci-failure-handling.md`** now. Follow its procedure for CI wait, failure triage, and merge/cleanup.

Summary:

1. **Wait for CI** — run `scripts/ci-wait.sh` and check `passed` in the JSON output (timeout 15 min).
2. **On failure** — Fetch logs via `scripts/ci-failure-logs.sh`, classify fix (trivial → apply directly; logic change → re-run Steps 2-3). Hard stop after 3 consecutive failures.
3. **Merge and clean up** — Run the merge script with all 4 required positional args (5th is optional):
   ```
   bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/merge-and-cleanup.sh \
     <PR_NUMBER> <BASE_BRANCH> <FEATURE_BRANCH> '<MERGE_STRATEGY_JSON>' [worktree_path]
   ```
   All values come from pre-flight output: `pr_number`, `base_branch`, `feature_branch`, `merge_strategy` (JSON object, not a bare word like "squash"). Report errors if `merge_ok` is false.

## Re-running the Cycle

To run a subsequent review cycle on the same PR (e.g., after applying changes and wanting fresh reviews):

1. Re-run Step 1 normally. `commit-and-push.sh --pr` is idempotent: it commits new changes (or pushes the existing HEAD as-is when the tree is clean) and, when a PR already exists for the branch, returns that PR's `pr_number`/`pr_url` instead of creating a duplicate. Use the returned `pr_number`.
2. Continue from Step 2 with that PR number.
3. Proceed through Steps 3–6 as normal.

When `--no-hub` is set, re-running simply means committing new changes locally and collecting fresh reviews from Step 2 onward.

## Error Handling

| Failure | Action |
|---------|--------|
| Pre-flight `has_errors: true` | Stop. Report errors (e.g., suggest `gh auth login`). |
| Step 1 (commit/PR) fails | Stop. Report the error. |
| Review skill sub-agent fails | Log the failed skill id, proceed with remaining reviewers. |
| Antigravity/Codex unavailable or fails | Inform user, proceed with available reviews. |
| No actionable suggestions | Report no issues. Skip Steps 4–5 only. Step 6 still executes (unless `--no-hub`). |
| Push fails (Step 5) | Report error. Suggest manual resolution. |
| CI fails 3 times | Stop. Ask user for guidance. |
| CI fix requires logic change | Re-run Steps 2-3 before pushing. |
| Merge/cleanup fails | Report `merge_ok` / warnings. Do not force-delete. |

## Additional Resources

### Reference Files

For detailed procedures, consult:
- **`references/consolidation-guide.md`** — Review deduplication, conflict resolution, scope classification, and tasks.md recording format
- **`references/ci-failure-handling.md`** — CI wait, failure triage, merge, and cleanup procedure

### Scripts

- **`scripts/preflight.sh`** — Pre-flight checks, outputs JSON with tool availability and repo metadata
- **`scripts/changed-files.sh`** — Detects tracked changes + untracked new files; one path per line. Called automatically by commit-and-push.sh — do not invoke directly.
- **`scripts/commit-and-push.sh`** `--message <msg> [--files "f1 f2"] [--no-push] [--pr] [--base <branch>]` — Stage, commit, push, and optionally create a PR; outputs JSON `{commit_hash, committed, pushed, pr_number, pr_url}` (`committed: false` = clean tree, HEAD pushed/PR'd as-is on a re-run). Idempotent with `--pr`: returns the existing PR when one already exists for the branch.
- **`scripts/ci-wait.sh`** `<pr_number>` — Waits for all CI checks to complete; outputs JSON `{passed: bool}`
- **`scripts/agy-review.sh`** — Antigravity (agy) review launcher
- **`scripts/codex-review.sh`** — Codex review launcher (plugin or CLI mode)
- **`scripts/ci-failure-logs.sh`** — Fetches failed CI check logs as JSON
- **`scripts/merge-and-cleanup.sh`** `<pr_number> <base_branch> <feature_branch> '<merge_strategy_json>'` — Merges PR and cleans up local/remote branches. All 4 args required; merge_strategy is a JSON object (e.g. `'{"squash":true}'`), not a bare word.