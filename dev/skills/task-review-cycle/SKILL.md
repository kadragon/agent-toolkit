---
name: task-review-cycle
description: >-
  Internal review-cycle primitive for `task-review`. Not a standalone entry
  point — do not invoke without an explicit caller argument.
version: 1.13.1
---
# Dev Review Cycle
Review workflow adapted from [How the Claude Code team does code review](https://claude.dev/blog/solving-code-review-at-anthropic/) (2026-10-15).

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
- `--panel` — force the panel (`references/risk-routing.md` → *Panel*).

**Sprint Contract.** Recover the archived original and evidence before writes:

```bash
STATE="<absolute parent directory of the loaded SKILL.md>/../task-next/scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled state helper unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" inspect
```

Recover a missing implementation contract first. Only standalone `task-review` without a contract
can grade the diff alone; archive verified authority and disclose the limit. Preserve the archive
through merge. For check reuse, see the shared cycle's *Validation evidence*.
## Prerequisites and Setup

Set `SKILL_DIR` to the absolute parent of the loaded `SKILL.md`. Preflight reports hub auth errors.

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

Stop on missing scripts or `has_errors: true`. Substitute the Setup values in later blocks.

## Step 1: Commit, route, PR

Derive `COMMIT_MESSAGE` from `git diff --cached --stat` (empty index: `--stat HEAD`) and
`git log -5`; the `[TYPE]` prefix is mandatory (commit-guard in the script rejects otherwise).
Capture it — and the Step 2 contract — with a **quoted** heredoc delimiter, never an interpolated
assignment (`docs/conventions.md`). A clean resumed branch reuses its commit; if its diff against
the base is empty and no review remains, report no work and stop here. End the body with
`Verification:` + the exact command and exit code of each `cycle_state.py inspect` → `evidence`
record, only when `tree_matches_current` is true (else `none recorded`): `retire` deletes the
archive, so commit and PR body keep the only record (`cursor/plugins@9b93e81:pstack/skills/poteto-mode/playbooks/opening-a-pr.md`).

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

`unstaged_left` lists dirt left out (in scope → stage, re-run). Non-zero exit → HEAD rejected;
`guard_skipped: true` → report.

**Route by risk** — `references/risk-routing.md`, evaluated on every run including explicit path
flags. Its floor block is mandatory: every capture forces hub with required CI — neither
`--lite` nor a judgment call may route one lite. Judgment escalates, never below. `--no-hub` stays local-only and stops before merge; report required
remote checks as pending. Announce path, rationale, mandatory checks, and panel on/off in one line.

Before choosing lite, run `cycle_state.py authorize --action base-merge` and `--action
base-push`; both must pass. PR-only routes hub; no-push already selected local review. Unknown commit
authority stops before Step 1 with work/evidence preserved (`git-authorization.md`).
Hub path — push and open the PR before any review:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
BASE_BRANCH="<from Setup>"
COMMIT_MESSAGE=$(cat <<'COMMIT_MSG'
<[TYPE] message from above>
COMMIT_MSG
)
RESULT=$(bash "$SKILL_DIR/scripts/commit-and-push.sh" --pr --no-commit --base "${BASE_BRANCH}" --message "${COMMIT_MESSAGE}")
PR_NUMBER=$(jq -r '.pr_number' <<<"$RESULT")
PR_URL=$(jq -r '.pr_url' <<<"$RESULT")
```

`pr_number` null but `pr_url` not → take `basename "$PR_URL"`. Both null → halt.

## Step 2: Review
Apply `references/review-sources.md` → *Data-sharing policy* to every primary, panel, and fallback reviewer.
**Lite → one reviewer, the engine that did not drive this cycle (`references/risk-routing.md` → *Lite reviewer*), then the advisory pass below.** Otherwise
**one Claude reviewer — a foreground shell-out, never a spawned agent.** `SECURITY_HIT` non-empty
(latest floor run) or material behavioral risk → `EFFORT="high"`, else empty. Reuse eligible passing
evidence per the shared cycle; execute missing/stale required checks before review. A failed or
absent required result blocks merge, even if the reviewer cannot assess it. Bash `timeout: 600000`:

```bash
CLAUDE_ALLOWED="<true only when the policy permits Claude>"
[[ "$CLAUDE_ALLOWED" == true ]] || { echo '{"code_review_slot":"policy-excluded"}'; exit 0; }
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
BASE_BRANCH="<from Setup>"
EFFORT="<high when the latest floor run's SECURITY_HIT was non-empty or the risk is material, else empty>"
CONTRACT=$(cat <<'SPRINT_CONTRACT'
<Sprint Contract verbatim, archive path, and validation evidence including commit/tree, command,
 environment, exit code, and log location, prefixed "Lint/test evidence:"; empty only in the
 one case the Sprint Contract paragraph above allows>
SPRINT_CONTRACT
)
bash "$SKILL_DIR/scripts/claude-review.sh" "${BASE_BRANCH}" "${EFFORT}" "${CONTRACT}" \
  || echo '{"code_review_slot":"inner-run-unavailable","detail":"claude-review.sh exited non-zero"}'
```

The read-only pass returns code and contract findings, grading execution criteria from supplied evidence.

`CLAUDE_CLI_AVAILABLE` `false`, a `code_review_slot` sentinel, or timeout → record `Reviewers Skipped: <reason>`.
Use the permitted fallback on lite, or grade the diff against the contract inline. Apply
the same review scope to any fallback. Disclose inline grading as self-grading and satisfy any
required independence with an allowed reviewer.

**Panel** (`references/risk-routing.md` → *Panel*) — launch agy + Codex per
`references/review-sources.md` one turn before the reviewer call. **Never wait on, stop, or
`sleep`-bound** either; reclaim results per `references/late-source-reclaim.md`.

**Advisory comments** — run `references/review-sources.md` → *Advisory comments pass* once
per cycle. A skipped or empty pass leaves the blocking verdict unchanged.

## Step 3: Consolidate and confirm
Follow `references/consolidation-guide.md` for the review table, approval, backlog and dispositions.
Follow *Report review send-backs to dispatch* for each verdict, including the Step 4 re-review.

## Step 4: Apply

1. Apply approved findings with focused checks. For each blocking finding, search the branch
   diff for the same bug pattern under its Blocking category; verify, fix and check every in-scope
   instance in the same pass. A check fails → fix forward within that finding's scope once.
   Still failing: a `contract` finding → stop, never merge; any other → undo that
   finding's own edits (`git restore --staged <file> && git restore <file>` only when no other
   applied finding touched the file), file it under `backlog.md` → `## Review Backlog`, and
   continue. A fixed `contract` finding → re-run the reviewer once; still failing → stop, never
   merge. Then handle advisory `comments` findings per `references/comment-rules.md` → *Applying*;
   keep their edits separable from blocking fixes so failed cleanup can be withdrawn independently.
2. A fix newly touched another plugin or skill `SKILL.md` → bump it per the shared cycle's
   *Version bump* (`[[ -f scripts/bump-version.sh ]] && bash scripts/bump-version.sh …`).
3. **Retrospect (signal-gated).** A user correction, recurring gotcha, or reusable workflow this
   cycle → call the Skill tool with "dev:harness-capture" now. Review has already run, so it
   writes auto-memory only and files every docs/`AGENTS.md`/skill delta to `backlog.md`.
4. Run full required checks on the final changed candidate and refresh evidence per the shared
   cycle. If checks fail after advisory comment edits, withdraw those edits and rerun the required
   checks on the remaining candidate; defer the cleanup and base the merge gate on that candidate.
   Finalize the dispositions after checks confirm which edits remain.

## Step 5: Commit
```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/commit-and-push.sh" ]] || { echo "Bundled commit helper unavailable: $SKILL_DIR/scripts/commit-and-push.sh" >&2; exit 1; }
FILES_TO_STAGE="<exact files changed in Step 4, verified against git status --short>"
COMMIT_MESSAGE=$(cat <<'COMMIT_MSG'
<[TYPE] message from Step 1, its Verification: line rebuilt from the Step 4.4 evidence>
COMMIT_MSG
)
# lite or --no-hub:
bash "$SKILL_DIR/scripts/commit-and-push.sh" --no-push --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
# hub:
bash "$SKILL_DIR/scripts/commit-and-push.sh" --files "${FILES_TO_STAGE}" --message "${COMMIT_MESSAGE}"
```

Skip the commit if Step 4 made no changes. GitHub: authorize `pr-write`, then update the PR body
with `gh pr edit`. `--no-hub`: reclaim late panel sources, report and stop.

## Step 6: Merge

PR-only, unverified base-merge authority, or dispatch pre-merge stop: reclaim late panel results,
finish checks, report the PR ready, and preserve its archive before any merge preparation.

**Lite path** — the route was chosen on the pre-review diff. When Step 5 committed a Step 4 fix,
re-run the floor block of `references/risk-routing.md` first; `FLOOR_HIT` non-empty → the route
is hub from here: Step 1's hub block, Step 2's hub review, Steps 3–5, then the hub path below.
Otherwise the lite reviewer ran in the foreground in Step 2 (a timeout kills it), so nothing to reclaim;
merge locally and push `main`:

```bash
FEATURE_BRANCH="<from Setup>"
BASE_BRANCH="<from Setup>"
STATE="<absolute task-next skill directory>/scripts/cycle_state.py"
python3 "$STATE" authorize --branch "$FEATURE_BRANCH" --action base-merge || exit 1
python3 "$STATE" authorize --branch "$FEATURE_BRANCH" --action base-push || exit 1
git checkout "$BASE_BRANCH" && git pull --ff-only origin "$BASE_BRANCH" || { git checkout "$FEATURE_BRANCH"; exit 1; }
git merge --no-ff "$FEATURE_BRANCH" -m "Merge branch '$FEATURE_BRANCH'" || { git merge --abort; git checkout "$FEATURE_BRANCH"; exit 1; }
python3 "$STATE" authorize --branch "$FEATURE_BRANCH" --action base-push || exit 1
git push origin "$BASE_BRANCH" && git branch -d "$FEATURE_BRANCH"
```

A failed step ends the block — report it. Push rejected → keep the local merge and feature branch,
never reset hard; recover within established authority. Lite is done only once the base push lands.

**Retire the archive only after confirming merge on either path**, including a user-run merge:
`python3 "<SKILL_DIR>/../task-next/scripts/cycle_state.py" retire --branch "<FEATURE_BRANCH>"`.

**Hub path** — first, in the feature checkout (its worktree, if any), `python3
"$SKILL_DIR/scripts/pre_merge_resync.py" --base <BASE_BRANCH>`: `up-to-date` → go on; `resynced`
pushed a merge of base, bump and CHANGELOG redone, so CI restarts; `conflict`/`denied`/`error` →
stop, keep the PR. Merge refused as behind → once more. Rebase-only `MERGE_STRATEGY` → skip; behind → stop.
Then `references/ci-failure-handling.md`: `scripts/ci-wait.sh <PR_NUMBER>` (under the 600s
ceiling), reclaim a skipped panel source after CI green (`references/late-source-reclaim.md`), then
resolve the helper; non-zero → stop, no merge. Then issue the merge as a second, separate command
starting with the printed path — no `bash` prefix, no variable: the only shape an auto-mode allow
rule matches. Exit 126/127 → stop and report; never retry as `bash <path>`:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -x "$SKILL_DIR/scripts/merge-and-cleanup.sh" ]] && echo "$SKILL_DIR/scripts/merge-and-cleanup.sh" || { echo "Bundled merge helper not executable" >&2; exit 1; }
# second command:
<printed path> <PR_NUMBER> <BASE_BRANCH> <FEATURE_BRANCH> '<MERGE_STRATEGY_JSON>'
```

## Error handling
| Failure | Action |
|---------|--------|
| Bundled script unresolvable, or preflight `has_errors` | Stop, report |
| Commit rejected by commit-guard (`{"error": "commit blocked…"}`) | Fix the branch or the `[TYPE]`; never retry the same call |
| Guard crashed (traceback) or `guard_skipped: true` | Treat as unchecked — report; fix `guard.py`, do not work around it |
| Reviewer sentinel, non-zero exit, or 600s timeout (Codex: marker/empty output) | Record `Reviewers Skipped`; lite → its fallback (*Lite reviewer*); hub, or both lite reviewers failed → review inline (self-grading, disclosed); report it |
| Panel source fails, exits 75, or has not reported when the reviewer returns | Record `Reviewers Skipped: <reason>`, proceed without waiting; codex failure or late return → reclaim before merge |
| Contract finding still open after the one retry | Stop; no Step 5, no merge |
| CI `rework-cap`, or a second consecutive `timeout` | Stop, ask the user |
| CI first `timeout` | Re-run `ci-wait.sh` once |
| CI `checks-never-registered` | Re-run `ci-wait.sh` once; recurs → stop, ask the user; never merge on it |
| Merge fails (`merge_ok: false`; `queued` = enqueued, `unconfirmed` = state unknown) | Report; never force-delete |
| Merge/push denied by the auto-mode classifier or a missing allow rule | Never retry another way; keep PR, branch, archive. Quote the denied command as issued (paths and values resolved) and ask the user to allow it in their own permission config; for the merge helper suggest `Bash(/…/dev/*/skills/task-review-cycle/scripts/merge-and-cleanup.sh *)` (version directory as `*`; a `bash`-led rule is dropped). Never write the rule yourself. On their go-ahead re-run once as that literal command; denied again → stop, report |
| Merge/push blocked by an explicit deny rule or managed policy | An allow rule cannot override it: stop, report the blocking source; keep PR, branch, archive |
