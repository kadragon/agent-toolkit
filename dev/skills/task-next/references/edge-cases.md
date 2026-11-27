# task-next — Edge cases

Rarely-hit branches of `dev:task-next`, split out of `SKILL.md` so the hot path stays small.

**Work already in flight** — inspect a feature branch in this checkout, a `.worktrees/<slug>` run
named by `--resume <slug>` or the user, before selecting new queue work, even when the checkout
is clean. Commits and changed files locate candidate work;
neither proves implementation, versioning, validation, or review complete.

```bash
EDGE_DIR="<absolute directory of this edge-cases.md>"   # task-new reaches this file without loading task-next's SKILL.md
STATE="$EDGE_DIR/../scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled state helper unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" inspect
```

Run in the candidate checkout. The probe includes staged, unstaged, and untracked changes and
the branch's saved contract; it deliberately returns no resume stage.

**Which checkout.** A feature branch checked out in this checkout is inspected here, unasked —
except under `--tree`, which leaves this checkout to its owner (`SKILL.md` → *Working tree gate*). A
`.worktrees/<slug>` run is inspected only on `--resume <slug>` or when the user names that
worktree — any other may be a live session's, so its mere presence never triggers this edge case
(`SKILL.md` → *Working tree gate*). Prefix the probe with `cd "<absolute .worktrees/<slug> path>"
&&`, not main's unrelated dirty state; no matching worktree → say so and stop. A resumed
`.worktrees/<slug>` run finishes every remaining stage in that worktree as a `cycle.md` →
*Worktree cycle* (hub route, `worktree_path` on the merge; re-set the Herdr label with the claim's `hc label` line) — under `references/tree.md`'s
implementer/QA rules when its `tasks.md` holds a claim block. Two explicit resumes report and stop
instead: a worktree on a `wt/<slug>` branch is a parallel batch unit, resumed through the batch row
below while its batch is unmerged — after that merge, name the unit and its archive and ask
whether to run it as its own cycle or remove it; and a worktree whose probe shows nothing in flight is not
handed to *Nothing in flight*, which switches this checkout and selects new work.

**Recovering the contract.** Read the saved original, evidence, and `notes` beside it first —
notes list approaches a stuck run already tried; do not repeat them — then an active
`tasks.md` block or an explicitly approved contract still in the conversation. Legacy run with no
copy → reconstruct with the user from the backlog/spec and diff, marking reconstruction explicitly.
A missing contract is unknown scope, not permission to review only the diff or declare completion.
Recover the Git authorization fields with it (`git-authorization.md`).

**Nothing in flight.** `contract` null, `changes` empty, and no commits ahead of the base means
this branch owns no cycle — a branch created ahead of the work, or one whose cycle already merged
and was retired. Say so, `git checkout <base>` (nothing here is lost), and return to the
caller's normal selection path — left on this branch, cycle.md → *Branch* exits 3 and routes the
new cycle through a worktree. Do not ask for a contract for work that does not exist, and do not
report blocked.

**Choose the earliest unmet obligation** (only once one of the three shows work):

| Evidence | Resume at |
|----------|-----------|
| Scope/approach requires a new material decision | `cycle.md` → *Plan gate* |
| An implementation criterion unmet or unknown, other than a check explicitly pending the final suite | `cycle.md` → *Implement* |
| All implementation criteria supported; required version change incomplete | `cycle.md` → *Version bump* |
| Implementation/version complete; cleanup incomplete | `cycle.md` → *Cleanup* |
| Targeted check missing, failed, stale, or bound to different inputs | `cycle.md` → *Validation evidence* |
| Targeted checks complete; review, final suite, CI, or merge pending | `cycle.md` → *Hand off* and resume review at its recorded checkpoint |
| Parallel batch, not yet merged: integration branch `notes` record unit outcomes | `batch.md` → *A5* for the recorded merged units only; excluded/conflicted units stay on their `wt/<slug>` branches |

Read the current branch/PR state before resuming a review; a commit ahead is not proof Step 1 ran.
If merge is already confirmed complete, report completion rather than rerun cleanup or bump again.
Use `cycle.md` → *Plan gate* for approval: an explicit same-session continuation of known scope
proceeds without another yes/no; ambiguous ownership or scope needs one focused question. An
archived contract is evidence of *prior* approved scope, not of approval to resume it now — a
cross-session or unattended run that cannot ask that question stops and reports blocked rather
than resuming a branch another session or worktree may still own. On a declined resume,
preserve work and ask which action the user wants; do not infer authorization to discard it.

**Deferred backlog item (≥2 candidates)** — surface the blocker and confirm it is resolved; if
not, skip to the next candidate. All deferred → stop with the blocker report in `SKILL.md`
Step 2, adding each candidate just inspected with the same label: an item deferred in prose
carries no marker, so the parked list does not list it. On the issues backend a deferred issue
carries the `deferred` label and is already parked; one deferred only in its body prose is handled
the same way, and the fix (adding the label) is the user's, not this cycle's.

**Deferred item in a group** — warn and continue with the group's non-deferred items; all
deferred → skip the group. On the issues backend the deferred sub-issues are already in the
candidate's `excluded[]`; name them, and leave the parent out of `## Covers` (`cycle.md` →
*Covered refs*).

**Parent issue with no open sub-issue** (issues backend) — two cycles that each covered part of a
parent leave it open with nothing under it, and it then lists as a lone candidate. Check that its
sub-issues closed through merged PRs; then the cycle covers just its ref, with no implementation
beyond what its body still asks for.

**Review finding spans multiple PRs** — scope narrowly to the specific `file:line`; record the
broader items back to the queue via the review cycle's out-of-scope path.
