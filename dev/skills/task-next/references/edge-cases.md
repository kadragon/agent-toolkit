# task-next — Edge cases

Rarely-hit branches of `dev:task-next`, split out of `SKILL.md` so the hot path stays small.

**Work already in flight** — a feature branch (or a `--tree` worktree) with uncommitted work from
a previous session. Run three cheap ordered checks to produce a diagnosis; this automates the
diagnosis text only — always still ask yes/no before resuming.

1. **Commits already ahead of `main`?**
   ```bash
   commits=$(git log main..HEAD --oneline 2>/dev/null)
   [[ -n "$commits" ]] && echo "commits exist — task-review-cycle Step 1 already ran"
   ```
   Non-empty → the review cycle already committed. Offer to re-enter it: call the Skill tool with
   "dev:task-review-cycle" and `args: --from task-next --auto`, restating the Sprint Contract
   (see *Recovering the contract* below).

2. **No commits ahead, but an active Sprint Contract?** The working-tree gate already routes a
   dirty main checkout with a matching `.worktrees/` path here — diagnose "`--tree` run in flight
   in `<path>`" and route the user to inspect or resume that worktree, or abort it via `tree.md`'s
   QA-failure cleanup block.

   ```bash
   active_block=$(grep -c "^status: active" tasks.md 2>/dev/null)
   ```
   Zero is not proof no sprint is running — a single-item cycle keeps its contract inline. Fall
   through to check 3 in that case. Non-zero → stage by what has changed, untracked files
   included:
   ```bash
   code_diff=$(git diff --stat -- . ':!tasks.md' ':!backlog.md' ':!CHANGELOG.md' ':!**/plugin.json' 2>/dev/null)
   untracked=$(git ls-files --others --exclude-standard -- . ':!tasks.md' ':!backlog.md' ':!CHANGELOG.md' ':!**/plugin.json' 2>/dev/null)
   bump_diff=$(git diff --stat -- '**/plugin.json' 2>/dev/null)
   ```
   - all empty → contract written, no implementation: resume at `cycle.md` → *Implement*.
   - `code_diff`/`untracked` non-empty, `bump_diff` empty → resume at `cycle.md` → *Version bump*.
   - `bump_diff` non-empty → resume at `cycle.md` → *Hand off*.

3. **Neither matched** → generic offer: "I see uncommitted changes on `<branch>`. Hand off to the
   review cycle?" with the contract restated per below.

**Recovering the contract.** The review cycle grades the diff against the Sprint Contract, and a
resumed run may find `tasks.md` already pruned. Restate it verbatim when this session still has
it; otherwise reconstruct it with the user from the diff and the backlog item, and say so — never
hand off a contract you invented.

On **yes**: resume at the diagnosed step. On **no**: ask whether to (a) stash and start fresh,
(b) commit the in-flight work first, or (c) cancel.

**Deferred backlog item (≥2 candidates)** — surface the blocker and confirm it is resolved; if
not, skip to the next candidate. All deferred → report and stop.

**Deferred item in a group** — warn and continue with the group's non-deferred items; all
deferred → skip the group.

**Review finding spans multiple PRs** — scope narrowly to the specific `file:line`; record the
broader items back to `backlog.md` via the review cycle's out-of-scope path.
