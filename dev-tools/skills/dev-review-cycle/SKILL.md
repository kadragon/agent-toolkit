---
name: dev-review-cycle
description: Post-dev review cycle — commit → reviews (Claude + agy + Codex) → apply → CI → merge. --no-hub: local only. --auto: skip confirmation. Trigger: "리뷰 돌려줘", "review cycle", "run review", "dev review", "리뷰 머지".
---

# Dev Review Cycle

## Arguments

- `--no-hub` — no push, no PR, no CI, no merge. Commits locally, reviews from local diff.
- `--auto` — skip user confirmation in Step 3. Apply all in-scope findings automatically. Verifier verdicts still apply (refuted = not applied).

## Prerequisites

- GitHub remote → `gh` CLI authenticated.
- Forgejo/Gitea remote → `FORGEJO_TOKEN` or `GITEA_TOKEN` set. Override API base with `DRC_HUB_API_URL` if needed.
- `--no-hub`: no auth required.

## Setup

```bash
PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)
# --no-hub: append the flag instead
```

Stop immediately if `CLAUDE_PLUGIN_ROOT` is unset. Stop if `has_errors: true`.

```bash
PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)  # from Setup — repeated here so this block is runnable standalone
HUB_TYPE=$(jq -r '.hub_type' <<<"$PREFLIGHT")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
FEATURE_BRANCH=$(jq -r '.feature_branch' <<<"$PREFLIGHT")
OWNER_REPO=$(jq -r '.owner_repo' <<<"$PREFLIGHT")
AGY_AVAILABLE=$(jq -r '.agy_available' <<<"$PREFLIGHT")
CODEX_AVAILABLE=$(jq -r '.codex_available' <<<"$PREFLIGHT")
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")
CODEX_COMPANION_PATH=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")
MERGE_STRATEGY=$(jq -c '.merge_strategy' <<<"$PREFLIGHT")
NO_HUB=$(jq -r '.no_hub' <<<"$PREFLIGHT")
```

## Workflow

One continuous flow. Only Step 3 pauses (skipped with `--auto`).

### Step 0: Ensure Feature Branch

If on base branch: inspect `git diff` and `git log --oneline -3`, derive short slug (2–4 words), create branch:
```bash
git checkout -b feat/short-slug
```

### Step 1: Commit + PR

CRITICAL (hub mode only — skip when `--no-hub`): PR MUST be created in this step, before any review. Do NOT defer PR creation to Step 6 or after reviews. Use commit-and-push.sh with `--pr` flag for PR creation here.

Determine commit message from context or `git diff --stat HEAD` + `git log --oneline -5`. File list is auto-detected by script.

```bash
COMMIT_MESSAGE="<derived from git diff --stat HEAD + git log --oneline -5>"

# --no-hub:
RESULT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --no-push --message "${COMMIT_MESSAGE}")

# hub mode:
PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)  # from Setup — repeated here so this block is runnable standalone
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
RESULT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --pr --base "${BASE_BRANCH}" --message "${COMMIT_MESSAGE}")
```

Extract `PR_NUMBER` and `PR_URL` from JSON (`jq -r '.pr_number'`, `jq -r '.pr_url'`). Hub mode only: if `pr_number` null but `pr_url` non-null, extract from URL: `basename "$PR_URL"`. Halt if both null. `--no-hub` (`--no-push`): null PR fields are expected — do not halt.

### Step 2: Collect Reviews

**All three sources (2-1, 2-2, 2-3) must be initiated in the same turn before waiting for any.** Use `run_in_background: true` for each. Allow 600s per source. After all complete, proceed to Step 3.

#### 2-1: Claude Skill Reviewers

```bash
PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)  # from Setup — repeated here so this block is runnable standalone
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)
FILE_COUNT=$(echo "$CHANGED_FILES" | grep -c . 2>/dev/null || true)
LINE_DELTA=$(git diff "${BASE_BRANCH}...HEAD" --shortstat \
  | grep -oE '[0-9]+ insertion|[0-9]+ deletion' | grep -oE '[0-9]+' | awk '{s+=$1}END{print s+0}')
SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment' | head -1 || true)
REVIEW_CANDIDATES_JSON=$(jq -c '.review_candidates' <<<"$PREFLIGHT")
```

**Two-slot model:**

- **Trivial short-circuit** — `FILE_COUNT ≤ 3` AND `LINE_DELTA ≤ 10` AND `SECURITY_HIT` empty → skip all Claude skill sub-agents; do inline review (read diff, assess naming/error-handling/coverage). Record all candidates as "Reviewers Skipped: trivial diff". Skip to 2-2.
- **Slot 1 (general, always 1):**
  ```bash
  PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)  # from Setup — repeated here so this block is runnable standalone
  REVIEW_CANDIDATES_JSON=$(jq -c '.review_candidates' <<<"$PREFLIGHT")  # from 2-1
  SLOT1=$(jq -r '[.candidates[] | select(.domain=="general")] | first | .id // empty' <<<"$REVIEW_CANDIDATES_JSON")
  ```
  Skip `kind=command` slots unless `HUB_TYPE=github` AND PR exists.
- **Slot 2 (security, conditional):**
  ```bash
  PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)  # from Setup — repeated here so this block is runnable standalone
  BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
  CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)  # from 2-1
  SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment' | head -1 || true)  # from 2-1
  REVIEW_CANDIDATES_JSON=$(jq -c '.review_candidates' <<<"$PREFLIGHT")  # from 2-1
  [[ -n "$SECURITY_HIT" ]] && \
    SLOT2=$(jq -r '[.candidates[] | select(.domain=="security")] | first | .id // empty' <<<"$REVIEW_CANDIDATES_JSON")
  ```
- All other candidates → "Reviewers Skipped: redundant domain".

For each selected slot, set `SLOT_ID="$SLOT1"` (Slot 1) or `SLOT_ID="$SLOT2"` (Slot 2), then launch one Agent (`run_in_background: true`, no `subagent_type`) with the prompt below. Model: Slot 1 → `sonnet`, Slot 2 → `opus`.

Reviewer prompt:
```
Review changes on branch ${FEATURE_BRANCH} against ${BASE_BRANCH}.
1. git diff ${BASE_BRANCH}...HEAD --name-only
2. Invoke Skill "${SLOT_ID}" to review.
3. Return findings as JSON array:
   [{"file":"...","line":N,"severity":"P0".."P3","confidence":0-100,"problem":"...","fix":"...","source":"${SLOT_ID}"}]
   confidence = certainty the issue is real in THIS code (not a pattern match). 100 = verified by reading actual code path.
Only flag issues introduced or made significantly worse by this PR.
Do NOT flag: pre-existing issues, linter-owned style, generated/vendored files, speculative concerns, >5 style nits.
```

#### 2-2: Antigravity (agy)

Skip if `agy_available=false`. Launch with `run_in_background: true` in the same turn as 2-1 and 2-3.
```bash
PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)  # from Setup — repeated here so this block is runnable standalone
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/agy-review.sh ${BASE_BRANCH} \
  || echo '{"agy_review":"failed"}' >&2
```

#### 2-3: Codex

Skip if `codex_available=false`. Launch with `run_in_background: true` in the same turn as 2-1 and 2-2.
```bash
PREFLIGHT=$(bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/preflight.sh)  # from Setup — repeated here so this block is runnable standalone
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")  # from Setup
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
CODEX_COMPANION_PATH=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")  # from Setup
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/codex-review.sh "${CODEX_MODE}" "${BASE_BRANCH}" "${CODEX_COMPANION_PATH}" \
  || echo '{"codex_review":"failed"}' >&2
```

If all sources fail → inline review + note in consolidation.

### Step 3: Consolidate + Confirm

Follow **`references/consolidation-guide.md`** for deduplication, confidence filtering (< 75 drops to low-confidence list), scope classification, and tasks.md recording.

**Verifier gate (P0/P1):** If any P0 or P1 in-scope candidates survived, spawn one Sonnet verifier sub-agent to re-check each at file:line — confirm (a) exists in working tree, (b) introduced by this branch's diff, (c) concrete path to breakage. Return `confirmed | refuted | uncertain` with one-line evidence. Refuted → "Refuted by verifier" section, never applied. Skip verifier when no P0/P1s exist.

If `--auto` NOT set: STOP, present consolidated table, wait for confirmation.
If `--auto` set: treat all in-scope (non-refuted) as approved.

Before proceeding:
1. Write out-of-scope items to `tasks.md` (format in consolidation-guide.md).
2. If no in-scope items: skip Steps 4–5. If `tasks.md` modified, still run Step 5 to commit it. Step 6 always runs (unless `--no-hub`).

### Step 4: Apply Improvements

Apply accepted changes. Find test command: `package.json scripts.test`, `Makefile`, `pytest.ini`, `pyproject.toml`, `go.mod`, `Cargo.toml`. Run tests. On failure: revert via `git restore --staged <files> && git restore <files>`, report which suggestion failed, ask user to skip or retry.

### Step 5: Commit Improvements

List exact files modified in Step 4. Verify against `git status --short` before staging.

```bash
FILES_TO_STAGE="path/to/file1 path/to/file2"  # exact files modified in Step 4, verified against `git status --short`
COMMIT_MESSAGE="<derived from git diff --stat HEAD + git log --oneline -5>"  # from Step 1

# --no-hub:
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --no-push --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"

# hub mode:
bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/commit-and-push.sh \
  --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
```

`--no-hub`: report summary and end here.

### Step 6: CI + Merge

Follow **`references/ci-failure-handling.md`**. Summary:
1. `scripts/ci-wait.sh <PR_NUMBER>` — wait up to 15 min, check `passed`.
2. On failure: `scripts/ci-failure-logs.sh` → classify fix. Trivial → apply directly. Logic change → re-run Steps 2–3. Hard stop after 3 failures.
3. Merge (all 4 args required; `MERGE_STRATEGY` is a JSON object, not a bare word):
   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/skills/dev-review-cycle/scripts/merge-and-cleanup.sh \
     <PR_NUMBER> <BASE_BRANCH> <FEATURE_BRANCH> '<MERGE_STRATEGY_JSON>'
   ```

## Error Handling

| Failure | Action |
|---------|--------|
| `CLAUDE_PLUGIN_ROOT` unset | Stop immediately |
| Preflight `has_errors: true` | Stop, report (suggest `gh auth login` or set token) |
| Step 1 fails | Stop, report |
| Review sub-agent fails | Log skill id, proceed with remaining |
| No actionable suggestions | Skip Steps 4–5, still run Step 6 |
| Push fails | Report, suggest manual resolution |
| `--no-push` + clean tree (nothing to commit) | Fatal — `commit-and-push.sh` exits 1, "nothing to do" |
| CI fails 3× | Stop, ask user |
| Merge fails | Report `merge_ok`, do not force-delete |

## Scripts Reference

| Script | Usage |
|--------|-------|
| `scripts/preflight.sh` | Pre-flight checks, outputs JSON |
| `scripts/commit-and-push.sh` | Stage, commit, push, create PR; idempotent with `--pr` |
| `scripts/agy-review.sh` | Antigravity review launcher |
| `scripts/codex-review.sh` | Codex review launcher |
| `scripts/ci-wait.sh <pr>` | Wait for CI, outputs `{passed: bool}` |
| `scripts/ci-failure-logs.sh` | Fetch failed CI logs as JSON |
| `scripts/merge-and-cleanup.sh` | Merge PR, clean local/remote branches |
| `scripts/hub.sh` | Hub adapter (GitHub / Forgejo) — called by other scripts |
