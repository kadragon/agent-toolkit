---
name: task-review-cycle
description: >-
  Internal review-cycle primitive for `task-review`. Not a standalone entry
  point — do not invoke without an explicit caller argument.
version: 1.0.0
---
# Dev Review Cycle
## Caller gate

Require `--from <caller>` before Setup; absent → stop without Git writes and direct the human
to `/task-review`. Any caller name is a trace, not authentication. Before Setup, read
`../task-next/references/git-authorization.md`: verify the originating user instruction,
recover the original contract with approval source/actions/limits verbatim, and establish the
allowed route. No-push selects `--no-hub` for every preflight call before auth probes.
Missing legacy authority denies affected actions; flags never expand approval.
## Arguments

- `--from <caller>` — required caller trace only.
- `--auto` — approve in-scope P0/P1 review fixes, not Git effects.
- `--no-hub` — local commit/review only; still requires commit permission.
- `--lite` / `--pr` — request a path within authority and mandatory CI/risk gates.
- `--panel` — force agy + Codex and hub unless `--no-hub`; default on non-lite routes.

**Sprint Contract.** Recover the archived original and evidence before writes:

```bash
STATE="<absolute parent directory of the loaded SKILL.md>/../task-next/scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled state helper unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" inspect
```

Implementation callers with no contract return to recovery. Only standalone `task-review`
without an original may grade the diff alone; archive its verified authority and disclose that
limit. Preserve the archive through merge. Check reuse: shared cycle's *Validation evidence*.
## Prerequisites and Setup

GitHub remote → `gh` authenticated. Forgejo/Gitea → `FORGEJO_TOKEN` or `GITEA_TOKEN` set
(`DRC_HUB_API_URL` overrides the API base). `--no-hub` needs no auth. `SKILL_DIR` is the absolute
parent directory of the `SKILL.md` loaded this turn.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/preflight.sh" ]] || { echo "Bundled preflight unavailable: $SKILL_DIR/scripts/preflight.sh" >&2; exit 1; }
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")   # append --no-hub when that flag is set
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

Derive `COMMIT_MESSAGE` from `git diff --cached --stat` (empty index: `--stat HEAD`) and
`git log -5`; the `[TYPE]` prefix is mandatory (commit-guard in the script rejects otherwise).
Capture it — and the Step 2 contract — with a **quoted** heredoc delimiter, never an interpolated
assignment (`docs/conventions.md`). A clean resumed branch reuses its commit; if its diff against
the base is empty and no review remains, report no work and stop here.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
COMMIT_MESSAGE=$(cat <<'COMMIT_MSG'
<[TYPE] derived message>
COMMIT_MSG
)
DIRTY=$(git status --porcelain)
if [[ -n "$DIRTY" ]]; then
  BASE_BRANCH="<from Setup>"
  RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --no-push --prefer-staged --base "${BASE_BRANCH}" --message "${COMMIT_MESSAGE}")
else
  RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --verify-head)
fi
```

`--prefer-staged` commits a non-empty index alone; an empty index ahead of the base runs `--verify-head`:
no commit, HEAD guarded (the only check on outside commits), `resumed` returned. `unstaged_left` lists
dirt left out (in scope → stage, re-run). Non-zero exit → HEAD rejected; `guard_skipped: true` → report.

**Route by risk** — `references/risk-routing.md`, evaluated on every run including explicit path
flags. Its floor block is mandatory: all four captures force hub with required CI — neither
`--lite` nor a judgment call may route one lite. The panel follows the path: on for hub and
`--no-hub`, off for lite, since the codex reclaim's only free runway is `ci-wait.sh`. Judgment
escalates, never below. `--no-hub` stays local-only and stops before merge; report required remote
checks as pending. Announce chosen path, rationale, mandatory checks, and panel on/off in one line.

Before choosing lite, run `cycle_state.py authorize --action base-merge` and `--action
base-push`; both must pass. PR-only routes hub; no-push already selected local review. Unknown commit
authority stops before Step 1 with work/evidence preserved (`git-authorization.md`).
Hub path — push and open the PR before any review:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
COMMIT_MESSAGE=$(cat <<'COMMIT_MSG'
<[TYPE] message from above>
COMMIT_MSG
)
RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --pr --no-commit --base "${BASE_BRANCH}" --message "${COMMIT_MESSAGE}")
PR_NUMBER=$(jq -r '.pr_number' <<<"$RESULT")
PR_URL=$(jq -r '.pr_url' <<<"$RESULT")
```

Idempotent: `--no-commit` reuses the commit above and never stages a stray dirty file.
`pr_number` null but `pr_url` not → take `basename "$PR_URL"`. Both null → halt.

## Step 2: Review

**Lite → Codex alone (`references/risk-routing.md` → *Lite reviewer*), then Step 3.** Otherwise
**one Claude reviewer — a foreground shell-out, never a spawned agent.** `SECURITY_HIT` non-empty
(Step 1 floor) or material behavioral risk → `EFFORT="high"`, else empty. Reuse eligible passing
evidence per the shared cycle; execute missing/stale required checks before review. A failed or
absent required result blocks merge, even if the reviewer cannot assess it. Bash `timeout: 600000`:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/claude-review.sh" ]] || { echo "Bundled claude-review unavailable: $SKILL_DIR/scripts/claude-review.sh" >&2; exit 1; }
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
EFFORT="<high when Step 1's SECURITY_HIT was non-empty or the risk is material, else empty>"
CONTRACT=$(cat <<'SPRINT_CONTRACT'
<Sprint Contract verbatim, archive path, and validation evidence including commit/tree, command,
 environment, exit code, and log location, prefixed "Lint/test evidence:"; empty only in the
 one case the Sprint Contract paragraph above allows>
SPRINT_CONTRACT
)
bash "$SKILL_DIR/scripts/claude-review.sh" "${BASE_BRANCH}" "${EFFORT}" "${CONTRACT}" \
  || echo '{"code_review_slot":"inner-run-unavailable","detail":"claude-review.sh exited non-zero"}'
```

It grades requirements and code quality as separate axes in one read-only pass, printing the
findings array on stdout. It never runs the lint/test command (`--permission-mode plan`); it grades
an execution-based criterion against the evidence line above, staying silent on one when that line
is absent rather than failing it. Grading runs outside this session in a foreground shell-out.

`CLAUDE_CLI_AVAILABLE` `false`, the `code_review_slot` sentinel, or the 600s Bash timeout → record
`Reviewers Skipped: <reason>` and review inline (diff, correctness, naming, error handling,
coverage, the contract). 600s is the Bash tool's ceiling, not a tuned budget; this fallback and lite's
contract grading are where independence fails — the author grades their own code. Disclose it; required
checks stay the only mechanical guard, and inline review cannot satisfy a policy that requires an
independent reviewer.

**Panel** (every non-lite route) — launch agy + Codex per `references/review-sources.md` in the
turn *before* the reviewer call, so they run while it holds the foreground. **Never wait on them.**

**Never stop one either** — the panel sidecar `references/late-source-reclaim.md` reclaims before
the merge is what makes not-waiting safe, and #248 removed the quorum rule because it *killed* a
source still working. Never bound a wait with a `sleep`: it outlives the cycle (nine orphaned once).

## Step 3: Consolidate and confirm
Follow `references/consolidation-guide.md`. A `contract` finding is in-scope P0, never dropped by
confidence or by `--auto`.

Without `--auto`: present the table and wait. With `--auto`: every in-scope P0/P1 finding is
approved. Out-of-scope findings and in-scope P2/P3 go to `backlog.md` under `## Review Backlog`
(format in the guide) — never `tasks.md`.

## Step 4: Apply

In this order, because everything before the last step changes the tree the checks must run on:

1. Apply approved findings with focused checks. On failure revert that file (`git restore
   --staged <file> && git restore <file>`), report which failed, ask. A fixed `contract` finding
   → re-run the reviewer once; still failing → stop, never merge.
2. A fix that newly touched another plugin or skill `SKILL.md` → re-run `scripts/bump-version.sh` for it.
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
COMMIT_MESSAGE=$(cat <<'COMMIT_MSG'
<[TYPE] message from Step 1>
COMMIT_MSG
)
# lite or --no-hub:
bash "$SKILL_DIR/scripts/commit-and-push.sh" --no-push --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
# hub:
bash "$SKILL_DIR/scripts/commit-and-push.sh" --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
```

Skip the commit when Step 4 changed nothing. `--no-hub`, either way: reclaim a late panel source
(`references/late-source-reclaim.md`), report, end.

## Step 6: Merge

PR-only: reclaim late panel results, finish checks and report the reviewed PR; stop before
merge. Unknown merge authority preserves the PR and archive. Never retire an unmerged cycle.

**Lite path** — the Codex run finished in Step 2, so nothing to reclaim; merge locally and push `main`:

```bash
FEATURE_BRANCH="<from Setup>"
BASE_BRANCH="<from Setup>"
STATE="<absolute task-next skill directory>/scripts/cycle_state.py"
python3 "$STATE" authorize --branch "$FEATURE_BRANCH" --action base-merge || exit 1
python3 "$STATE" authorize --branch "$FEATURE_BRANCH" --action base-push || exit 1
git checkout "$BASE_BRANCH" && git pull --ff-only origin "$BASE_BRANCH"
git merge --no-ff "$FEATURE_BRANCH" -m "Merge branch '$FEATURE_BRANCH'"
python3 "$STATE" authorize --branch "$FEATURE_BRANCH" --action base-push || exit 1
git push origin "$BASE_BRANCH" && git branch -d "$FEATURE_BRANCH"
```

Push rejected → preserve the local merge and feature branch; report the failure. Never
reset hard automatically. Recover the hub path within established authority; report lite
completion only after direct base push succeeds.

**Retire the archive on either path**, only after the merge is confirmed — one left behind
resurrects this cycle's contract for the next branch deriving the same name: `python3
"<SKILL_DIR>/../task-next/scripts/cycle_state.py" retire --branch "<FEATURE_BRANCH>"`.

**Hub path** — follow `references/ci-failure-handling.md`: `scripts/ci-wait.sh <PR_NUMBER>`
(15 min), then reclaim a skipped panel source after CI green
(`references/late-source-reclaim.md`), then:

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
| Reviewer sentinel, non-zero exit, or 600s timeout (lite: Codex marker/empty/timeout) | Record `Reviewers Skipped`; lite → Claude reviewer, else review inline; report it |
| Panel source fails, exits 75, or has not reported when the reviewer returns | Record `Reviewers Skipped: <reason>`, proceed without waiting; codex failure or late return → reclaim before merge |
| Contract finding still open after the one retry | Stop; no Step 5, no merge |
| CI `rework-cap` / `timeout` / `checks-never-registered` | Stop, ask the user |
| Merge fails (`merge_ok: false`; `queued` = enqueued, `unconfirmed` = state unknown) | Report; never force-delete |

Scripts: `preflight.sh`, `commit-and-push.sh`, `claude-review.sh`, `agy-review.sh`,
`codex-review.sh`, `ci-wait.sh`, `ci-failure-logs.sh`, `merge-and-cleanup.sh`, `hub.sh` (adapter).
