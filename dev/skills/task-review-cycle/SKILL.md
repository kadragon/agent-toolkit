---
name: task-review-cycle
description: >-
  Internal review-cycle primitive for `task-review`. Not a standalone entry
  point — do not invoke without an explicit caller argument.
version: 1.2.0
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

## Step 1: Commit, route, PR

Derive `COMMIT_MESSAGE` from `git diff --cached --stat` (empty index: `--stat HEAD`) and
`git log -5`; the `[TYPE]` prefix is mandatory (commit-guard in the script rejects otherwise).
Capture it — and the Step 2 contract — with a **quoted** heredoc delimiter, never an interpolated
assignment (`docs/conventions.md`). A clean resumed branch reuses its commit; if its diff against
the base is empty and no review remains, report no work and stop here. End the body with
`Verification:` + the exact command and exit code of the one `cycle_state.py inspect` → `evidence`
record, only when its `tree_matches_current` is true (else `none recorded`): `retire` deletes the
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

`--prefer-staged` commits a non-empty index alone; an empty index ahead of the base runs `--verify-head`:
no commit, HEAD guarded (the only check on outside commits), `resumed` returned. `unstaged_left` lists
dirt left out (in scope → stage, re-run). Non-zero exit → HEAD rejected; `guard_skipped: true` → report.

**Route by risk** — `references/risk-routing.md`, evaluated on every run including explicit path
flags. Its floor block is mandatory: all four captures force hub with required CI — neither
`--lite` nor a judgment call may route one lite. Panel: on for hub and `--no-hub`, off for lite.
Judgment escalates, never below. `--no-hub` stays local-only and stops before merge; report required
remote checks as pending. Announce path, rationale, mandatory checks, and panel on/off in one line.

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
(latest floor run) or material behavioral risk → `EFFORT="high"`, else empty. Reuse eligible passing
evidence per the shared cycle; execute missing/stale required checks before review. A failed or
absent required result blocks merge, even if the reviewer cannot assess it. Bash `timeout: 600000`:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/claude-review.sh" ]] || { echo "Bundled claude-review unavailable: $SKILL_DIR/scripts/claude-review.sh" >&2; exit 1; }
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
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

It grades requirements and code quality as separate axes in one read-only pass, printing the
findings array on stdout. It never runs the lint/test command (`--permission-mode plan`); it grades
an execution-based criterion against the evidence line above, silent on one when that line is absent.

`CLAUDE_CLI_AVAILABLE` `false`, the `code_review_slot` sentinel, or the 600s Bash timeout → record
`Reviewers Skipped: <reason>` and review inline (diff, correctness, naming, error handling,
coverage, the contract). This fallback and lite's contract grading are self-grading: disclose it;
it cannot satisfy a policy that requires an independent reviewer.

**Panel** (every non-lite route) — launch agy + Codex per `references/review-sources.md` in the
turn *before* the reviewer call. **Never wait on, stop, or `sleep`-bound one**: the pre-merge
reclaim (`references/late-source-reclaim.md`) is what makes not waiting safe.

## Step 3: Consolidate and confirm
Follow `references/consolidation-guide.md`. A `contract` finding is in-scope P0, never dropped by
confidence or by `--auto`.

Without `--auto`: present the table and wait. With `--auto`: every in-scope P0/P1 finding is
approved. Out-of-scope findings and in-scope P2/P3 go to `backlog.md` under `## Review Backlog`
(format and the rejected-record check in the guide) — never `tasks.md`.

## Step 4: Apply

In this order, because everything before the last step changes the tree the checks must run on:

1. Apply approved findings with focused checks. On failure revert that file (`git restore
   --staged <file> && git restore <file>`), report which failed, ask. A fixed `contract` finding
   → re-run the reviewer once; still failing → stop, never merge.
2. A fix newly touched another plugin or skill `SKILL.md` → bump it per the shared cycle's
   *Version bump* (`[[ -f scripts/bump-version.sh ]] && bash scripts/bump-version.sh …`).
3. **Retrospect (signal-gated).** A user correction, recurring gotcha, or reusable workflow this
   cycle → call the Skill tool with "dev:harness-capture" now. Review has already run, so it
   writes auto-memory only and files every docs/`AGENTS.md`/skill delta to `backlog.md`.
4. Run full required checks on the final changed candidate and refresh evidence per the shared
   cycle — last, so the recorded tree is the tree that was checked.

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

Skip the commit when Step 4 changed nothing. GitHub hub only (`hub.sh` has no edit verb): after
`authorize --action pr-write`, put the rebuilt body on the PR (`gh pr edit <PR_NUMBER> --body`).
`--no-hub`, either way: reclaim a late panel source (`references/late-source-reclaim.md`), report, end.

## Step 6: Merge

PR-only: reclaim late panel results, finish checks, report the reviewed PR, stop before merge.
Unknown merge authority keeps the PR and archive. Never retire an unmerged cycle.

**Lite path** — the route was chosen on the pre-review diff. When Step 5 committed a Step 4 fix,
re-run the floor block of `references/risk-routing.md` first; `FLOOR_HIT` non-empty → the route
is hub from here: Step 1's hub block, Step 2's hub review, Steps 3–5, then the hub path below.
Otherwise Codex ran in the foreground in Step 2 (a timeout kills it), so nothing to reclaim;
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

**Retire the archive on either path** once the merge is confirmed, a merge the user ran included (a leftover resurrects for the next
same-named branch): `python3 "<SKILL_DIR>/../task-next/scripts/cycle_state.py" retire --branch "<FEATURE_BRANCH>"`.

**Hub path** — `references/ci-failure-handling.md`: `scripts/ci-wait.sh <PR_NUMBER>` (under the 600s
ceiling), reclaim a skipped panel source after CI green (`references/late-source-reclaim.md`), then:

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
| CI `rework-cap` / `timeout` | Stop, ask the user |
| CI `checks-never-registered` | Re-run `ci-wait.sh` once; recurs → stop, ask the user; never merge on it |
| Merge fails (`merge_ok: false`; `queued` = enqueued, `unconfirmed` = state unknown) | Report; never force-delete |
| Merge/push denied by the auto-mode classifier or a missing allow rule | Never retry another way; keep PR, branch, archive. Quote the denied command as issued, paths and values resolved, and ask the user to allow it in their own permission config (Claude Code: `permissions.allow` in settings.json) — that exact text survives auto mode; a trailing ` *` for per-run arguments may be dropped as a wildcarded interpreter (code.claude.com/docs/en/permission-modes). Never write the rule yourself. On their go-ahead re-run once as that one literal command; denied again → stop, report |
| Merge/push blocked by an explicit deny rule or managed policy | An allow rule cannot override it: stop, report the blocking source; keep PR, branch, archive |
