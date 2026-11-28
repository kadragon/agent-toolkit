## Reserved dispatch intake

For a dispatched `--tree` task with a `Queue reservation`, verify the original request and per-unit
Git limits first. Check that the handoff's `ref` matches the invocation and assigned unit. From
the launch repository, send the following JSON to the installed `scripts/queue_backend.py
claim-reservation` using the values from the handoff:

```json
{"contract":1,"repo":"/abs/repo","reservation":"<id>","delivery":"/abs/run.json","base":"<pinned commit>","ref":"<unit ref>"}
```

The helper validates the reserved snapshot, creates its pinned worktree, and writes the normal
active claim to `tasks.md`. On a mismatch or any error, report blocked and stop. On success, use
the returned `worktree`, `branch`, `base`, `candidate`, and `covers`. Continue in that worktree
at Step 3 after reading the selected bodies with `show`. Read the Phase index's Branch, Plan gate
and Sprint Contract sections, then archive the contract as usual. The helper already performed
the worktree creation and claim checks. Set the Herdr worktree label as described under
Branch. Treat the returned `covers` as the initial claim. Recompute the issue closing refs under
*Covered refs* if the approved plan narrows its scope. The dispatched pre-merge stop and all authorization and review gates still apply.

## `--tree` mode (single task, worktree isolation)

Triggered by `--tree`. Runs Steps 1–2 as default single-pick does, but from the base (`SKILL.md`
→ *Working tree gate* `--tree` row, Step 1 `--ref`), then runs the whole
code cycle as a `cycle.md` → *Worktree cycle* in `.worktrees/<slug>`: `tasks.md`, contract
archive, edits, version bump, `CHANGELOG.md`, cleanup, commits, PR and merge all happen there,
and implementation changes stay in that worktree. A user's direct `--tree` invocation
establishes direction for implementation and QA delegation, subject to the applicable
delegation policy. For a dispatched run, verify the direction in the originating human
request. A flag added by the dispatcher establishes isolation only. When delegation is
unestablished, implement inline and apply the shared cycle's QA rules.

**Branch (replaces `git checkout -b` under `--tree`):** derive the branch, pin the base commit
and level the local base, then create the worktree per *Worktree cycle* with `BASE` = the printed
SHA:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
NODES="$SKILL_DIR/scripts/task_nodes.py"
[[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }
BRANCH=$(printf '%s\n' "<each selected item line, verbatim>" \
  | python3 "$NODES" branch --title "<selected heading title>")
rc=$?
[[ -n "$BRANCH" ]] || { echo "branch derivation failed — see stderr above" >&2; exit 1; }
# exit 3 (this checkout is off the base) is fine here: --tree never touches this checkout
[[ $rc -eq 0 || $rc -eq 3 ]] || { echo "branch exited $rc — see stderr above" >&2; exit 1; }
# the commit pinned for task-next selection or task-new intake, or empty when unpinned
BASE_SHA="<the SHA Step 1 printed, or empty>"
BASE=$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD) \
  || { echo "origin/HEAD unset — run: git remote set-head origin --auto" >&2; exit 1; }
if [[ -z "$BASE_SHA" ]]; then
  git fetch origin || exit 1
  BASE_SHA=$(git rev-parse --verify "$BASE^{commit}") || exit 1
fi
# level the local base with $BASE_SHA only when this checkout is clean on it; any other state is
# someone else's work, so skip — the worktree is built from $BASE_SHA and never needs the local base
CURRENT=$(git branch --show-current)
DIRTY=$(git status --porcelain)
if [[ "$CURRENT" == "${BASE#origin/}" && -z "$DIRTY" ]]; then
  git merge --ff-only "$BASE_SHA" || echo "local $CURRENT cannot fast-forward to $BASE_SHA — left as is" >&2
fi
echo "branch: $BRANCH  base: $BASE_SHA ($BASE)"
```

Create the worktree with `BASE` set to the printed SHA, not the moving `origin/<name>`: on
`backlog` the worktree's `backlog.md` is then exactly the one Step 1 selected from, so it holds
every selected line and `prune-backlog` finds them; on the issues backend the SHA pins only the
branch base. This checkout's branch and uncommitted edits — `backlog.md`
and `docs/design/` included — stay where they are and never reach the worktree or the PR.

**Claim — right after `git worktree add`, before the plan gate.** For a `backlog.md` group or
an issues-backend candidate (`## Covers` holds refs, `cycle.md` → *Covered refs*), follow
`cycle.md` → *Worktree cycle* → *Claim*: append the full claim block if the base tracks
`tasks.md`, or create the file with that block. For a `tasks.md` h1 block (`status: open`), flip
that block to `status: active` in the worktree's copy. The shared claim step covers branch
collisions and the re-check after writing the claim. A declined plan → revert only this claim
(delete the `tasks.md` it created, or restore the base-tracked file with `git restore tasks.md`),
confirm `git status --porcelain` in the worktree is empty, then `git worktree remove` it and
`git branch -d` the branch — no forced removal — and clear the Herdr label
(`cycle.md` → *Worktree cycle*).

**Mark active:** after the plan gate, add the Sprint Contract to that same worktree `tasks.md`
block — every `--tree` run writes it, even for one item. Archive the contract per `cycle.md` →
*Sprint Contract*, prefixing the command with `cd "<printed worktree path>" &&` — the
archive is keyed by the branch of the checkout it runs in, and an un-prefixed save keys it to
the base branch, which `cycle_state.py` refuses.

**Implement (`cycle.md` → *Implement*):** when delegation is authorized, spawn
`implementer`; its brief carries the rules in
`cycle.md` → *Implement*, worktree briefs included. The agent must NOT touch `plugin.json`
manifests, `backlog.md`, `tasks.md`, or `CHANGELOG.md` — the parent does those edits in the same
worktree after QA. A stuck report → the parent records it as a `note` from the worktree
(`cycle.md` → *Stuck-fix stop*).

Git authority for both briefs, worktree commits and the handoff: `git-authorization.md` (run
`authorize` from the worktree). No commit authority → keep the worktree intact and report.

**QA:** evaluate independent verification separately from implementation delegation. Preserve
the direct `--tree` workflow's required independent QA even if implementation runs inline.
For a dispatched isolation-only run, apply the shared QA requirements and applicable reviewer
authority. Give the verifier the worktree, Sprint Contract, queue backend selected at intake,
and targeted checks for pre-review QA. Its final response carries the verdict. One
fix-and-re-verify retry.

**If QA fails after one retry:** stop and report unmet criteria; the worktree, branch and
archive are preserved per *Worktree cycle* → *Stopped run*. Resuming is the default. Only when
the user explicitly authorizes abandoning the run, remove the worktree and branch — its
`tasks.md` goes with the worktree — and clear the Herdr label (`cycle.md` → *Worktree cycle*).

**After QA passes:** in the worktree, `cycle.md` → *Version bump*, *Cleanup* (`prune-tasks` on
the worktree `tasks.md`, plus `prune-backlog` and the `AGENT_QUEUE_BACKEND=backlog` changelog
command for the selected file queue), then
*Validation evidence* on the complete candidate. Hand off per Step 4 from the worktree (covered refs included on the issues backend), stating
the absolute worktree path so the review cycle runs there, takes the hub path, and passes the
path to `merge-and-cleanup.sh` (*Worktree cycle* → *Route*, *Merge*).
