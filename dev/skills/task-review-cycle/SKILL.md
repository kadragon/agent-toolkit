---
name: task-review-cycle
description: >-
  Internal review-cycle primitive for `task-review`. Not a standalone entry
  point — do not invoke without an explicit caller argument.
---

# Dev Review Cycle

## Caller gate

This skill is a callable primitive, not a standalone entry point. Before Setup, check the invocation
for a caller token of the form `--from <caller>`.

- **Token present** → strip it from `args` and run normally; everything else is the caller's own
  flags. The callers that exist today are `--from task-review` (the human's wrapper),
  `--from task-new` and `--from task-next` (their Step 4 hand-offs, including batch and tree mode).
  The list is open, not an allowlist: an unrecognised caller name is still a caller — run.
- **Token absent** → stop before Step 0. Do not commit, push, open a PR, or merge. Say that the
  review cycle is reached through `/task-review` (Claude Code) or the `task-review` picker entry
  (Codex) and let the human fire it. This is the invariant in `docs/invocation.md` → *The invariant*
  seen from the callee's side: a user-invoked wrapper exists precisely so the human times these side
  effects, and a primitive the model auto-selected would bypass that.

**What the gate does and does not catch.** It separates "a skill invoked me" from "the router
auto-selected me off a user query", which is the failure it exists for — an auto-selection carries no
token. It cannot stop an agent that reads this file and writes `--from user` itself. The gate is
prompted, not mechanical — nothing in CI enforces it. It exists because this skill's
`description` alone cannot stop the model from selecting it: measured with
`scripts/ci/check_skill_triggers.py`'s own `Corpus`/`rank()`, a short request like
`"do a code review on the current diff"` ranks `task-review-cycle` first.

## Arguments

- `--from <caller>` — required caller token, supplied by whichever skill invoked this one. See *Caller gate*.
- `--no-hub` — no push, no PR, no CI, no merge. Commits locally, reviews from local diff.
- `--auto` — skip user confirmation in Step 3. Apply all in-scope findings automatically. Verifier and contest-round verdicts still apply (refuted = not applied).
- `--qa-pending` — the caller handed off straight after implement, so **contract QA is still owed**: Step 2 runs it as source 2-4 alongside the review panel instead of the caller running it as its own wave in front of this cycle. Passed today by `--from task-next` and `--from task-new` on their default full-cycle path only; their lite path, `--tree` and `--all` batch mode verify before handing off and do not pass it. A caller that passes it **must restate the Sprint Contract verbatim** (Tag / Scope / Acceptance criteria / Out of scope / Lint-test command) in the invocation — its pre-merge cleanup has already pruned `tasks.md`, so the restatement is the only copy 2-4's brief can be built from. Flag present with no contract restated → stop and ask the caller for it; do not invent criteria. **Version bump and pre-merge cleanup deliberately stay with the caller** instead of moving into this cycle's Step 5: pre-handoff is what lets the Step 1 commit carry a valid version bump, so CI's bump check passes from the first push. The restatement requirement is the price of that choice.

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

Every block below re-runs `preflight.sh` so it stays runnable standalone; that is cheap, because
the script caches its own result per branch under `$(git rev-parse --git-dir)` and only the first
run in a cycle pays the hub probes. The cache is keyed on the current branch, so the Setup-era
entry is discarded the moment Step 0 cuts the feature branch — no block ever reads a stale
`feature_branch`. Pass `--refresh` if you need to force a live probe.

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

**commit-guard runs inside the script** (`hooks/commit-guard/guard.py --precommit-check`), because the PreToolUse hook cannot see a `git commit` that happens inside `bash <script>`. A rejection exits 1 with `{"error": "commit blocked by commit-guard: ..."}` on stderr and creates no commit. Two causes, both requiring a fix rather than a retry: the branch is `main`/`master` (check out a feature branch), or the message fails `^\[(FEAT|REFACTOR|FIX|TEST|CONSTRAINT|DOCS|HARNESS|PLAN)\] ` (fix the message). Also check `guard_skipped` in the output JSON — `true` means the guard could not run and the commit went through unchecked; surface that to the user rather than treating the commit as verified.

### Step 2: Collect Reviews

**All three review sources (2-1, 2-2, 2-3) — plus 2-4 when `--qa-pending` is set — must be initiated in the same turn before waiting for any.** 2-4 is contract QA, not a review engine: it is exempt from the panel short-circuit, counts toward nothing in the quorum rule, and its own timeout is a hard stop rather than a skip. Its three exception rules are stated at 2-4 below; the paragraph you are reading and the two rules that follow govern the review sources only. Use `run_in_background: true` for each, and stamp the launch in that same turn — the *Quorum-and-go* rule below reads that stamp. Allow 1200s per source. On a 1200s breach for any one source, stop waiting on that source only — do not extend the budget or re-poll indefinitely. Treat its output as unavailable for this cycle: same handling as "Review sub-agent fails" (record "Reviewers Skipped: timeout (>1200s)" for that source in the consolidation table), and proceed with whichever sources did return. If all three sources breach 1200s, follow the existing "If all sources fail" rule below (inline review + note in consolidation). Proceed to Step 3 when the *Quorum-and-go* rule below is satisfied — **not** necessarily when every source has returned.

#### Panel short-circuit — evaluate once, before launching anything

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)
DELTA_TERMS=$(git diff "${BASE_BRANCH}...HEAD" --shortstat \
  | grep -oE '[0-9]+ insertion|[0-9]+ deletion' | grep -oE '[0-9]+' | tr '\n' '+' | sed 's/+$//;s/^$/0/')
LINE_DELTA=$(( DELTA_TERMS ))
SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment' | head -1 || true)
BINARY_HIT=$(git diff "${BASE_BRANCH}...HEAD" --numstat | cut -f1,2 | grep -m1 -e '-' || true)
MODE_OR_RENAME=$(git diff "${BASE_BRANCH}...HEAD" --summary | grep -E '^ (mode change|rename) ' | head -1 || true)
```

`1 ≤ LINE_DELTA ≤ 30` AND `SECURITY_HIT`, `BINARY_HIT` and `MODE_OR_RENAME` all empty → **skip
2-1, 2-2 and 2-3 all three**; do the inline review instead (read the diff, assess naming, error
handling, coverage). Record `Reviewers Skipped: trivial diff (all engines, LINE_DELTA ≤ 30)` in
the consolidation table and go straight to Step 3. Otherwise launch all three sources as described
below.

**The short-circuit never skips 2-4.** It decides whether the *review panel* is worth its cost on a
small diff; contract QA asks a different question — did the change meet its Sprint Contract — and a
30-line diff can miss an acceptance criterion as easily as a 300-line one. Under `--qa-pending`,
launch 2-4 even when this gate fires, and reach Step 3 with the inline review plus 2-4's verdict.

**A zero line delta is not a trivial diff — it is an unmeasured one.** `--shortstat` counts no
insertions or deletions for a binary edit, a file-mode flip or a pure rename, so a change that
swaps an asset or sets an executable bit arrives here as `LINE_DELTA=0` and would clear a bare
`≤ 30` test. The `1 ≤` floor plus the two probes above make that case fail closed and run the
full panel; they are what keeps line delta usable as the primary term.

**There is no file-count term, deliberately.** The gate this replaced also required
`FILE_COUNT ≤ 3`, which is exactly what stopped it firing: this repo's changes are wide and
shallow (a 16-file, +48/-51 doc sweep cleared no gate), so of the last 15 merged PRs exactly one
qualified. Line delta alone is what tracks review-worthiness across that shape. Re-adding a file
cap re-introduces the bug.

**`SECURITY_HIT` is an absolute override** — a non-empty hit runs the whole panel no matter how
small the diff, and separately raises the Claude slot's effort to `high` in 2-1. The two uses read
the same capture; never re-derive the condition from a prose path list.

#### Quorum-and-go — proceed on 2 usable reviews, past an elapsed floor

Reached only when the panel short-circuit above did not fire. That gate decides whether the panel
launches at all; this rule decides how long to wait once it has. The panel's wall clock is `max()`
of its sources, so one slow engine sets the whole cycle's latency no matter how fast the others were.

Stamp the launch **to a file**, in the same turn you launch 2-1, 2-2 and 2-3. A later turn is a
fresh shell, so a plain `PANEL_START=$(date +%s)` variable would be unset by the time the floor
reads it — the arithmetic would then treat it as `0` and the floor would pass on the first check:

```bash
PANEL_STAMP="$(git rev-parse --git-dir)/drc-panel-start"
date +%s > "$PANEL_STAMP"
```

Stop waiting once **both** of these hold:

1. **Quorum — 2 sources have returned a *usable* review.** Usable means the source actually
   reviewed: a findings array (an empty `[]` counts — an engine that reviewed and found nothing
   did review) or review text. A source that errored, exited `75` (Codex workspace lock — nothing
   ran), or was never launched (`agy_available=false`, `codex_available=false`, `claude CLI
   unavailable`) does **not** count toward quorum. Record it as skipped under its own rule and drop
   it from the panel. **Counting a failure is the trap here:** two sources erroring in seconds would
   otherwise satisfy quorum and close the one engine that is actually reviewing, shipping a cycle
   with no review at all.
2. **Elapsed floor — at least 300s since the stamp.**
   ```bash
   PANEL_STAMP="$(git rev-parse --git-dir)/drc-panel-start"
   PANEL_START=$(cat "$PANEL_STAMP")
   ELAPSED=$(( $(date +%s) - PANEL_START ))
   [[ "$ELAPSED" -ge 300 ]] && echo "floor cleared"
   ```
   The floor keeps a fast pair from closing a slow third that was about to return something. 300s
   sits well inside the 1200s per-source budget, so a closed source only ever loses time it was
   already spending in the tail.

**When quorum is unreachable, it never fires.** Fewer than 2 sources still able to return a usable
review — because the rest failed, locked, or were never launched — means you wait out whoever is
left under the 1200s cap, exactly as before this rule existed. If nothing usable arrives at all,
take the "If all sources fail" rule below (inline review + note in consolidation).

When both conditions hold, **stop the outstanding source before proceeding** — `TaskStop` with its
task id (background Bash) or agent id (Agent slot). Closing without stopping is not free: Codex in
particular holds a per-workspace lock that `codex-review.sh` releases only from its `EXIT`/`INT`/
`TERM` trap, so a closed-but-still-running Codex keeps that lock and the *next* cycle's Codex slot
exits `75` and is skipped. Trading this cycle's tail for the next cycle's panel breadth is not the
bargain this rule is making.

Then record the stopped source in the consolidation table the way a timeout is recorded —
`Reviewers Skipped: quorum reached without it (2 usable reviews in, ≥300s)` — so the table still
states the panel's real breadth. **A closed source stays closed:** should its output still arrive
(the stop can race a result already in flight) while Step 3 or later is running, do not fold it in
and do not reopen consolidation, or the same diff yields a different action table run to run.
Record anything it found to `backlog.md` through the same out-of-scope path Step 3 already uses.

Quorum never *extends* a wait. The 1200s per-source cap still applies on its own; quorum only ends
a wait earlier.

**2-4 is outside this rule entirely.** Contract QA never counts toward the 2-usable-review quorum,
is never `TaskStop`-ed when quorum fires, and is always waited for before Step 3 — quorum ends the
*panel's* tail, not the cycle's verification. Counting it would let a single returned review plus QA
close the panel, shipping a diff one engine looked at; stopping it would ship a diff no one verified
against the contract at all.


#### 2-1: Claude Reviewer (`code-review`, fixed)

Reached only when the panel short-circuit above did not fire.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)  # from the panel short-circuit
SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment' | head -1 || true)  # from the panel short-circuit
EFFORT=""; [[ -n "$SECURITY_HIT" ]] && EFFORT="high"   # the ONLY security-escalation condition — both launch paths read this
```

**One reviewer, one skill — `SLOT_ID="code-review"`, always.** The Claude slot is pinned: no
candidate discovery, no per-domain second slot, no other review skill or `/review`-style command
is invoked from this cycle. `code-review` already covers correctness plus reuse/simplification;
the panel's breadth comes from the *other engines* (agy in 2-2, Codex in 2-3), not from stacking
more Claude review skills. A security-sensitive diff raises the effort level — `EFFORT="high"`,
passed as the skill's *argument*, never spliced into its name — it does **not** add a second
reviewer. Both launch paths below take `EFFORT` from the same `SECURITY_HIT` capture as the panel
short-circuit; never re-derive the condition from a prose path list. Anything else the user wants reviewed (`security-review`, a PR-review command) is
theirs to run outside this cycle.

How the reviewer is launched depends on the runtime driving this cycle (`NATIVE_ENGINE`, from Setup) — the goal is that a **Claude** engine is always in the panel, alongside agy (2-2) and Codex (2-3), no matter which runtime drives:

- **`NATIVE_ENGINE == "claude"`** (Claude Code is driving) — launch one Agent (`run_in_background: true`, no `subagent_type`) with the prompt below. Do not pin a model — omit the `model` field so each reviewer inherits the session's model (an Opus session reviews with Opus, a Sonnet session with Sonnet).
- **otherwise** (a non-Claude runtime such as Codex is driving) — the in-process agent would review as that runtime's own engine, not Claude, so shell out to the `claude` CLI to keep a Claude reviewer in the panel (mirror of how 2-2/2-3 summon their engines via companion scripts). If `CLAUDE_CLI_AVAILABLE == false`, skip this slot and record "Reviewers Skipped: claude CLI unavailable". Otherwise launch in the same turn with `run_in_background: true`:
  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -f "$SKILL_DIR/scripts/claude-review.sh" ]] || { echo "Bundled claude-review unavailable: $SKILL_DIR/scripts/claude-review.sh" >&2; exit 1; }
  PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")  # from Setup — repeated here so this block is runnable standalone
  BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")  # from Setup
  CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)  # from 2-1
  SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment' | head -1 || true)  # from 2-1
  EFFORT=""; [[ -n "$SECURITY_HIT" ]] && EFFORT="high"  # from 2-1
  bash "$SKILL_DIR/scripts/claude-review.sh" "${BASE_BRANCH}" "${EFFORT}" \
    || echo '[]'
  ```
  `claude-review.sh` emits the same findings-JSON array as the Agent path (it embeds the same reviewer prompt, including the `EFFORT` argument), so Step 3 consolidates both identically.

Reviewer prompt (Agent path):
```
Review changes on branch ${FEATURE_BRANCH} against ${BASE_BRANCH}.
1. git diff ${BASE_BRANCH}...HEAD --name-only
2. Invoke Skill "code-review" with args "${EFFORT}" to review — the skill name is exactly `code-review`; the effort goes in the args field, never in the name. Empty args = default effort. Do not invoke any other review skill or command.
3. Return findings as JSON array:
   [{"file":"...","line":N,"severity":"P0".."P3","confidence":0-100,"problem":"...","fix":"...","source":"code-review"}]
   confidence = certainty the issue is real in THIS code (not a pattern match). 100 = verified by reading actual code path.
If docs/design/{slug}.md exists for this branch's slug, also verify the diff fulfills its User Stories and Implementation/Testing Decisions and flag scope creep or missing requirements as additional findings.
Only flag issues introduced or made significantly worse by this PR.
Do NOT flag: pre-existing issues, linter-owned style, generated/vendored files, speculative concerns, >5 style nits.
Do not end silently: when finished, deliver the JSON array to the orchestrator with
SendMessage(to: "main"). Do not assume the final report is returned on its own —
skip this and the whole review is lost after the work is already done.
Send the array even when it is empty ([]) so the slot is recorded as reviewed, not stalled.
```

**Result-handoff rule (applies to every agent this skill spawns).** Any agent launched with a
`name` — and, as cheap insurance, any launched with `run_in_background: true` — must be told
**in its initial prompt** to report via `SendMessage(to: "main")`. For a named agent, messaging
is the delivery channel: it finishes the review and the findings are silently dropped otherwise.
There is no way to add the instruction after the spawn. Full rule: *Result-handoff rule* in
`delegation-template.md` (bundled with `dev:harness-curate`).

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
codex_status=0
bash "$SKILL_DIR/scripts/codex-review.sh" "${CODEX_MODE}" "${BASE_BRANCH}" "${CODEX_COMPANION_PATH}" \
  || codex_status=$?
# if/elif, not a trailing `[ ... ] && echo`: a false test at the end of the block would make the
# whole block exit non-zero on the success path — a passing review reported as a failed command.
if [ "$codex_status" -eq 75 ]; then
  echo '{"codex_review":"locked"}' >&2
elif [ "$codex_status" -ne 0 ]; then
  echo '{"codex_review":"failed"}' >&2
fi
```

Exit `75` is not a failed review — it is the script's per-workspace lock reporting that another
cycle already holds this workspace's Codex slot, so no companion was launched. Record it as
`Reviewers Skipped: codex review already running` and do **not** count it as a dead reviewer:
nothing ran, so there is no review to treat as empty, and the run is retryable as-is once the
other cycle finishes.

If all sources fail → inline review + note in consolidation.

#### 2-4: Contract QA (`qa-verifier`, only under `--qa-pending`)

Runs only when `--qa-pending` is set; without the flag the caller already verified before handing
off and this slot does not exist. Launch it with `run_in_background: true` **in the same turn as
2-1/2-2/2-3** — that concurrency is the whole point of the slot. Subject to the *Result-handoff
rule* above: the brief must end with an instruction to return the verdict via
`SendMessage(to: "main")`, including when nothing blocking was found.

Spawn `qa-verifier`. The brief carries the caller's restated Sprint Contract — acceptance criteria
verbatim — the in-scope paths, and the lint/test command, in `docs/delegation.md`'s four-field
format (Objective / Output format / Tools to use / Boundaries).

**Brief it adversarially.** The objective is *find violations*, not *confirm compliance*: tell it to
hunt for each way the change could fail a criterion and to record a pass only where it has evidence.
Do **not** pass your own reasoning about why the implementation is correct — the verifier grades the
diff against the contract, and a supplied conclusion is what it will confirm.

**Independence is what must not be dropped, not the role name.** The agent that implemented never
verifies its own output — including the main thread, when the caller implemented inline because
`implementer` was absent from its roster.

**`qa-verifier` absent from the roster:** spawn `general-purpose` instead, with the same four-field
brief plus effort tier, carrying the standing-checks floor because no role file states it. The
roster probe, the installed-plugin caveat and the full fallback are canonical in `dev:harness-init`
→ `references/harness-invariants.md` → *Absent-Role Fallbacks*.

Three rules separate this slot from the review sources, each contradicting a rule the panel already
has — apply them as written rather than by analogy to 2-1/2-2/2-3:

1. **Short-circuit-exempt.** A trivial diff skips the review engines; 2-4 launches anyway (see *The
   short-circuit never skips 2-4* above).
2. **Not a quorum source.** It never counts toward quorum and is never stopped by it; Step 3 waits
   for it unconditionally (see *2-4 is outside this rule entirely* above).
3. **Allow 1200s for 2-4 as well, and a breach is a hard stop, not a skip.** The Step 2 intro
   grants its budget to the review sources; this rule grants 2-4 the same 1200s so the deadline it
   can breach is defined. A review source that breaches its budget is
   recorded as skipped and the cycle proceeds on the rest. Contract QA breaching means the change
   was never verified against its contract — stop, report, and do not merge. Re-running the slot is
   the fix; recording it as skipped is not.

### Step 3: Consolidate + Confirm

Follow **`references/consolidation-guide.md`** for deduplication, the Contest Round (confidence 50–74 band), confidence filtering (< 50 drops to low-confidence list), scope classification, and backlog.md recording.

**Contract QA (2-4) folds in as a fourth source, on its own terms.** Its blocking findings are
in-scope P0 by construction and bypass the three gates the review sources pass through: no
confidence filter, no Contest Round, no verifier gate — the verifier gate re-checks a finding at
file:line against the contract, which is exactly what 2-4 already did, so running it again buys
nothing and can refute a verified contract miss. Non-blocking observations from 2-4 are ordinary
findings and take the normal path. `--auto` approves in-scope *review* findings without asking; it
must **never** wave through a blocking contract finding — those are fixed in Step 4 or the cycle
stops, with or without the flag.

**Classify each blocking contract finding before fixing it.** A finding caused by an unclear,
incomplete or wrong Sprint Contract is a *contract* defect: correct the contract and re-brief from
it. Only a finding that survives a correct contract is an implementation defect. Sending a contract
defect to the implementation path re-litigates it as one and burns the single retry Step 4 allows.

**Verifier gate (P0/P1) and Contest Round (confidence 50–74) — spawn in parallel, not sequentially.** The two gates target disjoint findings (P0/P1 vs the 50–74 confidence band) and never compete for the same candidate, so launch both in the same turn with `run_in_background: true` and wait for both before proceeding. Both prompts are subject to the **result-handoff rule** from Step 2 — each must end with an explicit instruction to return its verdicts via `SendMessage(to: "main")`, including when the verdict list is empty.

- **Verifier gate:** If any P0 or P1 in-scope candidates survived, spawn one verifier sub-agent (do not pin a model — inherit the session's model) to re-check each at file:line — confirm (a) exists in working tree, (b) introduced by this branch's diff, (c) concrete path to breakage. Return `confirmed | refuted | uncertain` with one-line evidence. Refuted → "Refuted by verifier" section, never applied. Skip verifier when no P0/P1s exist.
- **Contest Round (bounded, single pass — see consolidation-guide.md Section 3):** Collect contestable findings — confidence 50–74. If the set is empty, skip — do not spawn an agent. Otherwise spawn exactly one sub-agent (do not pin a model — inherit the session's model) with the diff and the full batch of contestable findings; it returns `confirmed | refuted` per finding with file:line evidence. This is one round only — it does not loop or re-run to convergence. `confirmed` → promoted into the action table (tagged `contest-confirmed` in the Verdict column). `refuted` → "Refuted by contest round" section, never applied.

If `--auto` NOT set: STOP, present consolidated table, wait for confirmation.
If `--auto` set: treat all in-scope (non-refuted) as approved.

Before proceeding:
1. Write out-of-scope items to `backlog.md` (format in consolidation-guide.md). Never `tasks.md` — it is the Sprint Contract and is deleted at sprint close.
2. If no in-scope items: skip Step 4, but still run Step 4.5 (retrospect). Run Step 5 if `backlog.md` was modified or Step 4.5 edited any repo file. Step 6 always runs (unless `--no-hub`).

### Step 4: Apply Improvements

Apply accepted changes. Find test command: `package.json scripts.test`, `Makefile`, `pytest.ini`, `pyproject.toml`, `go.mod`, `Cargo.toml`. Run tests. On failure: revert via `git restore --staged <files> && git restore <files>`, report which suggestion failed, ask user to skip or retry.

**If 2-4 reported blocking findings, re-verify once after applying the fixes.** Spawn `qa-verifier`
(or the `general-purpose` fallback) a second time against the corrected contract, briefed the same
way as in 2-4. Still blocking after that one retry → stop and report; do not proceed to Step 5 or
merge. One retry, not a loop.

**Re-check the version bump if these fixes changed the branch's file footprint.** Under
`--qa-pending` the caller bumped before handing off, so a Step 4 fix that newly touches another
plugin or another skill's `SKILL.md` leaves that bump stale — re-run `scripts/bump-version.sh` for
the newly-touched target (or edit the `version:` frontmatter by hand) and stage it with Step 5.
Nothing new touched → the caller's bump already covers this branch; do not bump twice.

### Step 4.5: Retrospect (pre-merge, signal-gated)

Reflect on this cycle **before committing**, so any durable lesson lands *inside this PR* instead of becoming a stray change on `main` after merge. This is the only in-cycle retrospect point — cheap, skippable, and a no-op for most cycles.

Quick self-check: did this cycle surface a **user correction**, a **recurring gotcha / setup fix**, or a **reusable workflow**? If none, skip and go to Step 5 — silence is the normal outcome, not a failure.

If a signal exists, call the Skill tool with "dev:harness-capture" and route its write-back **by weight** so the PR stays scoped:

| Lesson | Write-back |
|--------|-----------|
| Preference / approach correction | **auto-memory** — outside the repo, so write now with no merge impact |
| Small doc or gotcha tied to this change | inline edit to `docs/*.md` / `AGENTS.md` / `CLAUDE.md` → rides into the Step 5 commit, validated by Step 6 CI |
| New skill, skill overhaul, or multi-file doc rewrite | record to `backlog.md` as a follow-up (same channel as an out-of-scope finding) — do **not** inline: it would balloon the PR, and a skill edit would force a mid-cycle version re-bump |

`--auto`: `harness-capture` runs **non-interactively** (its cycle-tail `--auto` path) — it writes the light memory/doc delta directly, with this PR's review + CI as the veto, and defers any destructive memory prune to `backlog.md` instead of pausing. Interactive: it shows the proposed delta and waits for confirm. Heavy items always defer to `backlog.md`, never inline.

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

commit-guard applies here exactly as in Step 1 — a rejection exits 1 with no commit created, and `guard_skipped: true` means the commit was unchecked. Reusing Step 1's `COMMIT_MESSAGE` keeps the `[TYPE]` prefix valid; if you rewrite the message, keep the prefix.

`--no-hub`: report summary and end here.

### Step 6: CI + Merge

Follow **`references/ci-failure-handling.md`**. Summary:

**Never merge with an unresolved contract-QA blocker.** A 2-4 finding still blocking after Step 4's
one retry, or a 2-4 slot that breached its 1200s budget, ends the cycle here — green CI does not
substitute for the contract check.

1. `scripts/ci-wait.sh <PR_NUMBER>` — wait up to 15 min, check `passed` and `reason`.
2. On failure with no `reason` (real CI failure): `scripts/ci-failure-logs.sh` → classify fix. Trivial → apply directly. Logic change → re-run Steps 2–3.
   On failure with `reason:"rework-cap"`: the script's own 3-strike counter tripped — hard stop, report `.failures` and ask the user. Do not count strikes yourself.
   On failure with `reason:"timeout"` (CI still running after 15 min): NOT a failure — do not fetch logs, does not increment the counter. Stop and ask the user (keep waiting / check dashboard / abandon PR). See ci-failure-handling.md for detail.
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
| Review source >1200s | Skip that source, proceed with the rest; note "timeout (>1200s)" |
| Review source still running at quorum | Not a failure — `TaskStop` that source (so Codex releases its workspace lock), proceed to Step 3; note "quorum reached without it (2 usable reviews in, ≥300s)". Distinct from a >1200s timeout; do not fold in output that still arrives |
| 2-4 contract QA fails, or >1200s | Stop, report — never recorded as a skipped source. Contract QA is mandatory under `--qa-pending`; re-run the slot rather than proceeding unverified |
| 2-4 still blocking after Step 4's one retry | Stop, report; no Step 5, no merge |
| `--qa-pending` with no Sprint Contract restated | Stop, ask the caller for it — do not invent acceptance criteria |
| No actionable suggestions | Skip Step 4; still run Step 4.5 + Step 6 (Step 5 only if edits exist) |
| Push fails | Report, suggest manual resolution |
| `--no-push` + clean tree (nothing to commit) | Fatal — `commit-and-push.sh` exits 1, "nothing to do" |
| Commit rejected by commit-guard | `commit-and-push.sh` exits 1, `{"error": "commit blocked by commit-guard: ..."}`, no commit created. Fix the branch or the `[TYPE]` message — never retry the same call. The guard runs before `git add`, so the index is untouched; just re-run the script |
| Guard error is a traceback, not a guard reason | `guard.py` exists but crashed. Also exit 1, also no commit — a broken guard is treated as a rejection, never as a pass. Fix `guard.py`; do not work around it |
| `guard_skipped: true` in the commit JSON | The guard could not run at all (missing `guard.py` or no `python3`); the commit is UNCHECKED. Report it — do not treat the commit as guarded |
| CI fails 3× (`reason:"rework-cap"`) | Stop, ask user — the script counts, not you |
| CI timeout (`reason:"timeout"`) | Stop, ask user — does not increment the counter |
| Merge fails | Report `merge_ok`, do not force-delete |

## Scripts Reference

| Script | Usage |
|--------|-------|
| `scripts/preflight.sh` | Pre-flight checks, outputs JSON. Caches the result per branch at `$(git rev-parse --git-dir)/task-review-cycle-preflight.json`, so only the first run in a cycle pays the hub probes; `--refresh` forces a live run |
| `scripts/commit-and-push.sh` | Stage, commit, push, create PR; idempotent with `--pr`. Calls `hooks/commit-guard/guard.py --precommit-check` before committing (the PreToolUse hook cannot see a commit made inside a script); reports `guard_skipped` when it could not |
| `scripts/agy-review.sh` | Antigravity review launcher |
| `scripts/codex-review.sh` | Codex review launcher |
| `scripts/ci-wait.sh <pr>` | Wait for CI, outputs `{passed: bool}`; counts consecutive real failures and reports `reason:"rework-cap"` at 3 |
| `scripts/ci-failure-logs.sh` | Fetch failed CI logs as JSON |
| `scripts/merge-and-cleanup.sh` | Merge PR, clean local/remote branches |
| `scripts/hub.sh` | Hub adapter (GitHub / Forgejo) — called by other scripts |
