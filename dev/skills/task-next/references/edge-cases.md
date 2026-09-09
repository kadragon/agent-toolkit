# task-next — Edge cases

Rarely-hit branches of `dev:task-next`, split out of `SKILL.md` so the hot path stays small.

**Work already in flight** — inspect a feature branch or `--tree` worktree before selecting new
queue work, even when the checkout is clean. Commits and changed files locate candidate work;
neither proves implementation, versioning, validation, or review complete.

```bash
EDGE_DIR="<absolute directory of this edge-cases.md>"   # task-new reaches this file without loading task-next's SKILL.md
STATE="$EDGE_DIR/../scripts/cycle_state.py"
[[ -r "$STATE" ]] || { echo "Bundled state helper unavailable: $STATE" >&2; exit 1; }
python3 "$STATE" inspect
```

Run in the candidate checkout. The probe includes staged, unstaged, and untracked changes and
the branch's saved contract; it deliberately returns no resume stage. For `--tree`, inspect the
matching worktree listed by `git worktree list`, not main's unrelated dirty state.

**Recovering the contract.** Read the saved original and evidence beside it first, then an active
`tasks.md` block or an explicitly approved contract still in the conversation. Legacy run with no
copy → reconstruct with the user from the backlog/spec and diff, marking reconstruction explicitly.
A missing contract is unknown scope, not permission to review only the diff or declare completion.

**Nothing in flight.** `contract` null, `changes` empty, and no commits ahead of the base means
this branch owns no cycle — a branch created ahead of the work, or one whose cycle already merged
and was retired. Say so and return to the caller's normal selection path; do not ask for a
contract for work that does not exist, and do not report blocked.

**Choose the earliest unmet obligation** (only once one of the three shows work):

| Evidence | Resume at |
|----------|-----------|
| Scope/approach requires a new material decision | `cycle.md` → *Plan gate* |
| Any acceptance criterion unmet or unknown | `cycle.md` → *Implement* |
| All implementation criteria supported; required version change incomplete | `cycle.md` → *Version bump* |
| Implementation/version complete; cleanup incomplete | `cycle.md` → *Cleanup* |
| Required check missing, failed, stale, or bound to different inputs | `cycle.md` → *Validation evidence* |
| All above complete; review/CI/merge pending | `cycle.md` → *Hand off* |

Read the current branch/PR state before resuming a review; a commit ahead is not proof Step 1 ran.
If merge is already confirmed complete, report completion rather than rerun cleanup or bump again.
Use `cycle.md` → *Plan gate* for approval: an explicit same-session continuation of known scope
proceeds without another yes/no; ambiguous ownership or scope needs one focused question. An
archived contract is evidence of *prior* approved scope, not of approval to resume it now — a
cross-session or unattended run that cannot ask that question stops and reports blocked rather
than resuming a branch another session or worktree may still own. This is the working-tree gate's
never-auto-default rule, and it outranks the Plan gate's unattended clause. On a declined resume,
preserve work and ask which action the user wants; do not infer authorization to discard it.

**Deferred backlog item (≥2 candidates)** — surface the blocker and confirm it is resolved; if
not, skip to the next candidate. All deferred → report and stop.

**Deferred item in a group** — warn and continue with the group's non-deferred items; all
deferred → skip the group.

**Review finding spans multiple PRs** — scope narrowly to the specific `file:line`; record the
broader items back to `backlog.md` via the review cycle's out-of-scope path.
