---
name: dev-review-cycle
description: Post-dev review cycle — commit → reviews (Claude + agy + Codex) → apply → retrospect → CI → merge. --no-hub: local only. --auto: skip confirmation. Trigger: "리뷰 돌려줘", "review cycle", "run review", "dev review", "리뷰 머지", "open pr merge", "wait ci merge".
---

# Dev Review Cycle

## Arguments

- `--no-hub` — no push, no PR, no CI, no merge. Commits locally, reviews from local diff.
- `--auto` — skip user confirmation in Step 3. Apply all in-scope findings automatically. Verifier and contest-round verdicts still apply (refuted = not applied).

## Prerequisites

- GitHub remote → `gh` CLI authenticated.
- Forgejo/Gitea remote → `FORGEJO_TOKEN` or `GITEA_TOKEN` set. Override API base with `DRC_HUB_API_URL` if needed.
- `--no-hub`: no auth required.

Before executing a bundled file, resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded this turn. Use that concrete directory; do not infer it from a plugin-root environment variable.

## Setup

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")
# --no-hub: append the flag instead
```

Stop immediately if the loaded skill's bundled scripts cannot be resolved. Stop if `has_errors: true`.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
HUB_TYPE=$(jq -r '.hub_type' <<<"$PREFLIGHT")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
FEATURE_BRANCH=$(jq -r '.feature_branch' <<<"$PREFLIGHT")
OWNER_REPO=$(jq -r '.owner_repo' <<<"$PREFLIGHT")
AGY_AVAILABLE=$(jq -r '.agy_available' <<<"$PREFLIGHT")
CODEX_AVAILABLE=$(jq -r '.codex_available' <<<"$PREFLIGHT")
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")
CODEX_COMPANION_PATH=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")
NATIVE_ENGINE=$(jq -r '.native_engine' <<<"$PREFLIGHT")           # "claude" → in-process Agent; else → claude CLI companion (2-1)
CLAUDE_CLI_AVAILABLE=$(jq -r '.claude_cli_available' <<<"$PREFLIGHT")
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
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
COMMIT_MESSAGE="<derived from git diff --stat HEAD + git log --oneline -5>"

# --no-hub:
RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" \
  --no-push --message "${COMMIT_MESSAGE}")

# hub mode:
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" \
  --pr --base "${BASE_BRANCH}" --message "${COMMIT_MESSAGE}")
```

Extract `PR_NUMBER` and `PR_URL` from JSON (`jq -r '.pr_number'`, `jq -r '.pr_url'`). Hub mode only: if `pr_number` null but `pr_url` non-null, extract from URL: `basename "$PR_URL"`. Halt if both null. `--no-hub` (`--no-push`): null PR fields are expected — do not halt.

### Step 2: Collect Reviews

**All three sources (2-1, 2-2, 2-3) must be initiated in the same turn before waiting for any.** Use `run_in_background: true` for each. Allow 600s per source. On a 600s breach for any one source, stop waiting on that source only — do not extend the budget or re-poll indefinitely. Treat its output as unavailable for this cycle: same handling as "Review sub-agent fails" (record "Reviewers Skipped: timeout (>600s)" for that source in the consolidation table), and proceed with whichever sources did return. If all three sources breach 600s, follow the existing "If all sources fail" rule below (inline review + note in consolidation). After all complete (or time out), proceed to Step 3.

#### 2-1: Claude Skill Reviewers

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
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
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
  PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
  REVIEW_CANDIDATES_JSON=$(jq -c '.review_candidates' <<<"$PREFLIGHT")  # from 2-1
  SLOT1=$(jq -r '[.candidates[] | select(.domain=="general")] | first | .id // empty' <<<"$REVIEW_CANDIDATES_JSON")
  ```
  Skip `kind=command` slots unless `HUB_TYPE=github` AND PR exists.
- **Slot 2 (security, conditional):**
  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
  PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
  BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
  CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)  # from 2-1
  SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment' | head -1 || true)  # from 2-1
  REVIEW_CANDIDATES_JSON=$(jq -c '.review_candidates' <<<"$PREFLIGHT")  # from 2-1
  [[ -n "$SECURITY_HIT" ]] && \
    SLOT2=$(jq -r '[.candidates[] | select(.domain=="security")] | first | .id // empty' <<<"$REVIEW_CANDIDATES_JSON")
  ```
- All other candidates → "Reviewers Skipped: redundant domain".

For each selected slot, set `SLOT_ID="$SLOT1"` (Slot 1) or `SLOT_ID="$SLOT2"` (Slot 2). How the reviewer is launched depends on the runtime driving this cycle (`NATIVE_ENGINE`, from Setup) — the goal is that a **Claude** engine is always in the panel, alongside agy (2-2) and Codex (2-3), no matter which runtime drives:

- **`NATIVE_ENGINE == "claude"`** (Claude Code is driving) — launch one Agent (`run_in_background: true`, no `subagent_type`) with the prompt below. Do not pin a model — omit the `model` field so each reviewer inherits the session's model (an Opus session reviews with Opus, a Sonnet session with Sonnet).
- **otherwise** (a non-Claude runtime such as Codex is driving) — the in-process agent would review as that runtime's own engine, not Claude, so shell out to the `claude` CLI to keep a Claude reviewer in the panel (mirror of how 2-2/2-3 summon their engines via companion scripts). If `CLAUDE_CLI_AVAILABLE == false`, skip this slot and record "Reviewers Skipped: claude CLI unavailable". Otherwise launch in the same turn with `run_in_background: true`:
  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -f "$SKILL_DIR/scripts/claude-review.sh" ]] || { echo "Bundled claude-review unavailable: $SKILL_DIR/scripts/claude-review.sh" >&2; exit 1; }
  PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
  BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
  SLOT_ID="<the selected slot's review skill id — Slot 1's general or Slot 2's security, chosen above>"
  bash "$SKILL_DIR/scripts/claude-review.sh" "${BASE_BRANCH}" "${SLOT_ID}" \
    || echo '[]'
  ```
  `claude-review.sh` emits the same findings-JSON array as the Agent path (it embeds the same reviewer prompt), so Step 3 consolidates both identically.

Reviewer prompt (Agent path):
```
Review changes on branch ${FEATURE_BRANCH} against ${BASE_BRANCH}.
1. git diff ${BASE_BRANCH}...HEAD --name-only
2. Invoke Skill "${SLOT_ID}" to review.
3. Return findings as JSON array:
   [{"file":"...","line":N,"severity":"P0".."P3","confidence":0-100,"problem":"...","fix":"...","source":"${SLOT_ID}"}]
   confidence = certainty the issue is real in THIS code (not a pattern match). 100 = verified by reading actual code path.
If docs/design/{slug}.md exists for this branch's slug, also verify the diff fulfills its User Stories and Implementation/Testing Decisions and flag scope creep or missing requirements as additional findings.
Only flag issues introduced or made significantly worse by this PR.
Do NOT flag: pre-existing issues, linter-owned style, generated/vendored files, speculative concerns, >5 style nits.
```

#### 2-2: Antigravity (agy)

Skip if `agy_available=false`. Launch with `run_in_background: true` in the same turn as 2-1 and 2-3.
```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
bash "$SKILL_DIR/scripts/agy-review.sh" "${BASE_BRANCH}" \
  || echo '{"agy_review":"failed"}' >&2
```

#### 2-3: Codex

Skip if `codex_available=false`. Launch with `run_in_background: true` in the same turn as 2-1 and 2-2.
```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")  # from Setup
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
CODEX_COMPANION_PATH=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")  # from Setup
bash "$SKILL_DIR/scripts/codex-review.sh" "${CODEX_MODE}" "${BASE_BRANCH}" "${CODEX_COMPANION_PATH}" \
  || echo '{"codex_review":"failed"}' >&2
```

If all sources fail → inline review + note in consolidation.

### Step 3: Consolidate + Confirm

Follow **`references/consolidation-guide.md`** for deduplication, the Contest Round (confidence 50–74 band), confidence filtering (< 50 drops to low-confidence list), scope classification, and tasks.md recording.

**Verifier gate (P0/P1) and Contest Round (confidence 50–74) — spawn in parallel, not sequentially.** The two gates target disjoint findings (P0/P1 vs the 50–74 confidence band) and never compete for the same candidate, so launch both in the same turn with `run_in_background: true` and wait for both before proceeding.

- **Verifier gate:** If any P0 or P1 in-scope candidates survived, spawn one verifier sub-agent (do not pin a model — inherit the session's model) to re-check each at file:line — confirm (a) exists in working tree, (b) introduced by this branch's diff, (c) concrete path to breakage. Return `confirmed | refuted | uncertain` with one-line evidence. Refuted → "Refuted by verifier" section, never applied. Skip verifier when no P0/P1s exist.
- **Contest Round (bounded, single pass — see consolidation-guide.md Section 3):** Collect contestable findings — confidence 50–74. If the set is empty, skip — do not spawn an agent. Otherwise spawn exactly one sub-agent (do not pin a model — inherit the session's model) with the diff and the full batch of contestable findings; it returns `confirmed | refuted` per finding with file:line evidence. This is one round only — it does not loop or re-run to convergence. `confirmed` → promoted into the action table (tagged `contest-confirmed` in the Verdict column). `refuted` → "Refuted by contest round" section, never applied.

If `--auto` NOT set: STOP, present consolidated table, wait for confirmation.
If `--auto` set: treat all in-scope (non-refuted) as approved.

Before proceeding:
1. Write out-of-scope items to `tasks.md` (format in consolidation-guide.md).
2. If no in-scope items: skip Step 4, but still run Step 4.5 (retrospect). Run Step 5 if `tasks.md` was modified or Step 4.5 edited any repo file. Step 6 always runs (unless `--no-hub`).

### Step 4: Apply Improvements

Apply accepted changes. Find test command: `package.json scripts.test`, `Makefile`, `pytest.ini`, `pyproject.toml`, `go.mod`, `Cargo.toml`. Run tests. On failure: revert via `git restore --staged <files> && git restore <files>`, report which suggestion failed, ask user to skip or retry.

### Step 4.5: Retrospect (pre-merge, signal-gated)

Reflect on this cycle **before committing**, so any durable lesson lands *inside this PR* instead of becoming a stray change on `main` after merge. This is the only in-cycle retrospect point — cheap, skippable, and a no-op for most cycles.

Quick self-check: did this cycle surface a **user correction**, a **recurring gotcha / setup fix**, or a **reusable workflow**? If none, skip and go to Step 5 — silence is the normal outcome, not a failure.

If a signal exists, invoke `Skill(dev-tools:capture-learnings)` and route its write-back **by weight** so the PR stays scoped:

| Lesson | Write-back |
|--------|-----------|
| Preference / approach correction | **auto-memory** — outside the repo, so write now with no merge impact |
| Small doc or gotcha tied to this change | inline edit to `docs/*.md` / `AGENTS.md` / `CLAUDE.md` → rides into the Step 5 commit, validated by Step 6 CI |
| New skill, skill overhaul, or multi-file doc rewrite | record to `tasks.md` as a follow-up (same channel as an out-of-scope finding) — do **not** inline: it would balloon the PR, and a skill edit would force a mid-cycle version re-bump |

`--auto`: `capture-learnings` runs **non-interactively** (its cycle-tail `--auto` path) — it writes the light memory/doc delta directly, with this PR's review + CI as the veto, and defers any destructive memory prune to `tasks.md` instead of pausing. Interactive: it shows the proposed delta and waits for confirm. Heavy items always defer to `tasks.md`, never inline.

Any repo file edited here rides into Step 5 — add it to `FILES_TO_STAGE` below.

### Step 5: Commit Improvements

List exact files modified in Step 4 **and any repo files edited in Step 4.5**. Verify against `git status --short` before staging.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/commit-and-push.sh" ]] || { echo "Bundled commit helper unavailable: $SKILL_DIR/scripts/commit-and-push.sh" >&2; exit 1; }
FILES_TO_STAGE="path/to/file1 path/to/file2"  # exact files modified in Step 4 and Step 4.5, verified against `git status --short`
COMMIT_MESSAGE="<derived from git diff --stat HEAD + git log --oneline -5>"  # from Step 1

# --no-hub:
bash "$SKILL_DIR/scripts/commit-and-push.sh" \
  --no-push --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"

# hub mode:
bash "$SKILL_DIR/scripts/commit-and-push.sh" \
  --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
```

`--no-hub`: report summary and end here.

### Step 6: CI + Merge

Follow **`references/ci-failure-handling.md`**. Summary:
1. `scripts/ci-wait.sh <PR_NUMBER>` — wait up to 15 min, check `passed` and `reason`.
2. On failure with no `reason` (real CI failure): `scripts/ci-failure-logs.sh` → classify fix. Trivial → apply directly. Logic change → re-run Steps 2–3. Hard stop after 3 failures.
   On failure with `reason:"timeout"` (CI still running after 15 min): NOT a failure — do not fetch logs, does not count toward 3×. Stop and ask the user (keep waiting / check dashboard / abandon PR). See ci-failure-handling.md for detail.
3. Merge (all 4 args required; `MERGE_STRATEGY` is a JSON object, not a bare word):
   ```bash
   SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
   [[ -f "$SKILL_DIR/scripts/merge-and-cleanup.sh" ]] || { echo "Bundled merge helper unavailable: $SKILL_DIR/scripts/merge-and-cleanup.sh" >&2; exit 1; }
   bash "$SKILL_DIR/scripts/merge-and-cleanup.sh" \
     <PR_NUMBER> <BASE_BRANCH> <FEATURE_BRANCH> '<MERGE_STRATEGY_JSON>'
   ```

## Error Handling

| Failure | Action |
|---------|--------|
| Loaded skill path or bundled script unavailable | Stop immediately |
| Preflight `has_errors: true` | Stop, report (suggest `gh auth login` or set token) |
| Step 1 fails | Stop, report |
| Review sub-agent fails | Log skill id, proceed with remaining |
| Review source >600s | Skip that source, proceed with the rest; note "timeout (>600s)" |
| No actionable suggestions | Skip Step 4; still run Step 4.5 + Step 6 (Step 5 only if edits exist) |
| Push fails | Report, suggest manual resolution |
| `--no-push` + clean tree (nothing to commit) | Fatal — `commit-and-push.sh` exits 1, "nothing to do" |
| CI fails 3× | Stop, ask user |
| CI timeout (`reason:"timeout"`) | Stop, ask user — does not count toward 3× |
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
