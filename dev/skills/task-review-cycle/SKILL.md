---
name: task-review-cycle
description: >-
  Internal review-cycle primitive for `task-review`. Not a standalone entry
  point — do not invoke without an explicit caller argument.
---

# Dev Review Cycle

## Caller gate

This skill is a callable primitive. Before Setup, look for `--from <caller>` in the invocation.

- **Present** → strip it and run. Any caller name counts (`task-review`, `task-new`, `task-next`).
- **Absent** → stop before Step 0. Do not commit, push, open a PR, or merge. Say the review cycle
  is reached through `/task-review` and let the human fire it (`docs/invocation.md` → *The
  invariant*). The gate catches router auto-selection, which carries no token.

## Arguments

- `--from <caller>` — required caller token.
- `--auto` — skip the Step 3 confirmation; apply every in-scope finding.
- `--no-hub` — commit locally, review, apply, stop. No push, PR, CI, or merge.
- `--lite` / `--pr` — request a merge path; required CI and risk gates still apply.
- `--panel` — add agy and Codex engines when independent perspectives address a concrete risk.
  Step 1's `SCRIPT_HIT` floor turns it on regardless.

**Sprint Contract.** Recover the caller's archived original if not restated (Tag / Scope /
Acceptance criteria / Out of scope / Lint-test command). It is branch-keyed under the common Git dir:

```bash
STATE="<absolute parent directory of the loaded SKILL.md>/../task-next/scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled state helper unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" inspect
```

`contract` non-null is the original; `evidence` carries the recorded validation run. Implementation
callers with a missing contract return to recovery, not diff-only review. Only a standalone
`task-review` with neither a restated nor a recoverable contract may grade the diff alone;
disclose that limit. Preserve the archive through merge, then retire it (Step 6). Approval and
check-reuse rules: `../task-next/references/cycle.md` → *Plan gate* and *Validation evidence*.

## Prerequisites and Setup

GitHub remote → `gh` authenticated. Forgejo/Gitea → `FORGEJO_TOKEN` or `GITEA_TOKEN` set
(`DRC_HUB_API_URL` overrides the API base). `--no-hub` needs no auth. `SKILL_DIR` is the absolute
parent directory of the `SKILL.md` loaded this turn.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")   # append --no-hub when that flag is set
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
FEATURE_BRANCH=$(jq -r '.feature_branch' <<<"$PREFLIGHT")
CLAUDE_CLI_AVAILABLE=$(jq -r '.claude_cli_available' <<<"$PREFLIGHT")
MERGE_STRATEGY=$(jq -c '.merge_strategy' <<<"$PREFLIGHT")
```

Stop if the bundled scripts cannot be resolved or `has_errors` is `true`. The result is cached per
branch, so later blocks re-run it for free for the fields they need (shell state does not persist).

## Step 0: Feature branch

On the base branch: derive a short slug from the diff, then `git checkout -b <type>/<slug>`.

## Step 1: Commit, route, PR

Derive `COMMIT_MESSAGE` from `git diff --stat HEAD` and `git log --oneline -5`; the `[TYPE]`
prefix is mandatory (commit-guard runs inside the script and rejects otherwise). A clean resumed
branch reuses its commit; if its diff against the base is empty and no review remains, report no
work and stop before this block.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
COMMIT_MESSAGE="<[TYPE] derived message>"
DIRTY=$(git status --porcelain)
if [[ -n "$DIRTY" ]]; then
  RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --no-push --message "${COMMIT_MESSAGE}")
else
  RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --verify-head)
fi
```

`--verify-head` commits nothing; it guards the existing HEAD and returns the `resumed` sentinel.
Skipping it is the one path on which a commit made outside this harness reaches a PR or `main`
unchecked. Non-zero exit → HEAD itself is rejected. `guard_skipped: true` → report it.

**Route by risk** — `references/risk-routing.md`, evaluated on every run including explicit path
flags. Its floor block is mandatory: `SECURITY_HIT`/`BINARY_HIT`/`MODE_OR_RENAME` force hub with
required CI (neither `--lite` nor a judgment call may route them lite), and `SCRIPT_HIT` turns
`--panel` on whatever path is chosen. Judgment escalates above that floor, never below it.
`--no-hub` stays local-only and stops before merge; report required remote checks as pending.

Announce chosen path, rationale, mandatory checks, and any panel reason in one line.

Hub path — push and open the PR before any review:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
COMMIT_MESSAGE="<[TYPE] message from above>"
RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --pr --base "${BASE_BRANCH}" --message "${COMMIT_MESSAGE}")
PR_NUMBER=$(jq -r '.pr_number' <<<"$RESULT")
PR_URL=$(jq -r '.pr_url' <<<"$RESULT")
```

Idempotent: the local commit above is reused. `pr_number` null but `pr_url` not → take
`basename "$PR_URL"`. Both null → halt.

## Step 2: Review

**One reviewer, always — a foreground shell-out, never a spawned agent.** `SECURITY_HIT`
non-empty (Step 1 floor) or material behavioral risk → `EFFORT="high"`, else empty. Reuse eligible passing evidence per the shared
cycle; execute missing/stale required checks before review. A failed or absent required result
blocks merge, even if the reviewer cannot assess it. Capture the contract with a
**quoted** heredoc delimiter — interpolating it runs the backticks and `$(...)` a contract carries
(a `"` breaks the block outright), and quoting also stops bash 3.2 mis-scanning it. Bash `timeout: 600000`:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/claude-review.sh" ]] || { echo "Bundled claude-review unavailable: $SKILL_DIR/scripts/claude-review.sh" >&2; exit 1; }
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
EFFORT="<high when Step 1's SECURITY_HIT was non-empty or the risk is material, else empty>"
CONTRACT=$(cat <<'SPRINT_CONTRACT'
<Sprint Contract verbatim, archive path, and validation evidence including commit/tree, command,
 environment, exit code, and log location, prefixed "Lint/test evidence:";
 leave this body empty only for a standalone task-review with neither a restated nor a
 recoverable contract — never for an implementation caller>
SPRINT_CONTRACT
)
bash "$SKILL_DIR/scripts/claude-review.sh" "${BASE_BRANCH}" "${EFFORT}" "${CONTRACT}" \
  || echo '{"code_review_slot":"inner-run-unavailable","detail":"claude-review.sh exited non-zero"}'
```

It grades requirements and code quality as separate axes in one read-only pass, printing the
findings array on stdout. It never runs the lint/test command (`--permission-mode plan`); it grades
an execution-based criterion against the evidence line above, staying silent on one when that line
is absent rather than failing it. Grading happens outside this session, so the agent that wrote the
code never certifies it. Bash enforces `timeout` where the `Agent` tool has none, and an agent's
completion notification can be lost (upstream claude-code #49150, #58637, #68117) — which is how
this cycle used to sit forever on a finished review. Same shape as `hamelsmu/claude-review-loop`
and `ktaletsk/council`.

`CLAUDE_CLI_AVAILABLE` `false`, or the `code_review_slot` sentinel on stdout → record
`Reviewers Skipped: <reason>` and review inline (diff, correctness, naming, error handling,
coverage, the contract). Disclose that independent review was unavailable; required checks still
apply, and inline review cannot satisfy a policy that requires an independent reviewer.

**`--panel`** — launch those sources per `references/review-sources.md` in the turn *before* the
reviewer call, so they run while it holds the foreground. **Do not wait on them.** Once the
reviewer's array is in hand, consolidate whichever have reported, record each one that has not as
`Reviewers Skipped: still running`, and go to Step 3.

**Never stop a panel source** — the codex run persists a sidecar that
`references/late-source-reclaim.md` reclaims before the merge, and that reclaim is what makes not
waiting safe. Not-waiting and not-stopping are separate: #248 removed the quorum rule because it
*killed* a source still working. Never bound a wait with a `sleep` either — it outlives the cycle
that started it (nine were orphaned on one run).

## Step 3: Consolidate and confirm

Follow `references/consolidation-guide.md`: merge duplicates across sources, drop confidence < 50
and the excluded categories, classify in/out of scope, sort by severity. A `contract` finding is
in-scope P0, never dropped by confidence or by `--auto`.

Without `--auto`: present the table and wait. With `--auto`: every in-scope finding is approved.
Out-of-scope findings go to `backlog.md` under `## Review Backlog` (format in the guide) — never
`tasks.md`.

## Step 4: Apply

In this order, because everything before the last step changes the tree the checks must run on:

1. Apply approved findings with focused checks. On failure revert that file (`git restore
   --staged <file> && git restore <file>`), report which failed, ask. A fixed `contract` finding
   → re-run the reviewer once; still failing → stop, never merge.
2. A fix that newly touched another plugin or skill `SKILL.md` → re-run `scripts/bump-version.sh`
   for it.
3. **Retrospect (signal-gated).** Only if this cycle surfaced a user correction, a recurring
   gotcha, or a reusable workflow: call the Skill tool with "dev:harness-capture" now, so a light
   memory or `docs/` delta rides into this commit (heavy → `backlog.md`). No signal → skip.
4. Run full required checks on the final changed candidate and refresh evidence per the shared
   cycle — last, so the recorded tree is the tree that was checked.

## Step 5: Commit

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/commit-and-push.sh" ]] || { echo "Bundled commit helper unavailable: $SKILL_DIR/scripts/commit-and-push.sh" >&2; exit 1; }
FILES_TO_STAGE="<exact files changed in Step 4, verified against git status --short>"
COMMIT_MESSAGE="<[TYPE] message from Step 1>"
# lite or --no-hub:
bash "$SKILL_DIR/scripts/commit-and-push.sh" --no-push --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
# hub:
bash "$SKILL_DIR/scripts/commit-and-push.sh" --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
```

Skip when Step 4 changed nothing. `--no-hub`: report and end here.

## Step 6: Merge

**Lite path** — reclaim a skipped codex source (`references/late-source-reclaim.md`), then merge locally and push `main`:

```bash
FEATURE_BRANCH="<from Setup>"
BASE_BRANCH="<from Setup>"
git checkout "$BASE_BRANCH" && git pull origin "$BASE_BRANCH"
git merge --no-ff "$FEATURE_BRANCH" -m "Merge branch '$FEATURE_BRANCH'"
git push origin "$BASE_BRANCH" && git branch -d "$FEATURE_BRANCH"
```

Push rejected (branch protection) → `git reset --hard origin/<base>`, `git checkout <feature>`,
continue on the hub path from Step 1's PR block. Report: "라이트 패스 완료 — main에 직접 병합 및
푸시됨. PR·CI 없음."

**Retire the archive on either path**, only after the merge is confirmed — one left behind
resurrects this cycle's contract for the next branch deriving the same name:
`python3 "<SKILL_DIR>/../task-next/scripts/cycle_state.py" retire --branch "<FEATURE_BRANCH>"`.

**Hub path** — follow `references/ci-failure-handling.md`: `scripts/ci-wait.sh <PR_NUMBER>`
(15 min; `reason:"rework-cap"`, `reason:"timeout"` and `reason:"checks-never-registered"` stop and ask), then reclaim a skipped codex source after CI green (`references/late-source-reclaim.md`), then:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/merge-and-cleanup.sh" ]] || { echo "Bundled merge helper unavailable: $SKILL_DIR/scripts/merge-and-cleanup.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/merge-and-cleanup.sh" <PR_NUMBER> <BASE_BRANCH> <FEATURE_BRANCH> '<MERGE_STRATEGY_JSON>'
```

## Error handling

| Failure | Action |
|---------|--------|
| Bundled script unresolvable, or preflight `has_errors` | Stop, report |
| Commit rejected by commit-guard (`{"error": "commit blocked…"}`) | Fix the branch or the `[TYPE]`; never retry the same call |
| Guard crashed (traceback) or `guard_skipped: true` | Treat as unchecked — report; fix `guard.py`, do not work around it |
| Reviewer sentinel, non-zero exit, or the 600s Bash timeout | Record `Reviewers Skipped`, review inline, note it in the report |
| Panel source fails, exits 75, or has not reported when the reviewer returns | Record `Reviewers Skipped: <reason>`, proceed without waiting; codex failure or late return → reclaim before merge |
| Contract finding still open after the one retry | Stop; no Step 5, no merge |
| CI `rework-cap` / `timeout` / `checks-never-registered` | Stop, ask the user |
| Merge fails (`merge_ok: false`) | Report; never force-delete |

Scripts: `preflight.sh` (probes, cached per branch), `commit-and-push.sh` (stage, guard, commit,
push, `--pr`, `--verify-head`; idempotent), `claude-review.sh`, `agy-review.sh`, `codex-review.sh`,
`ci-wait.sh` (3-strike counter), `ci-failure-logs.sh`, `merge-and-cleanup.sh`, `hub.sh` (adapter).
