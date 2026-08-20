# task-next — Edge cases

Rarely-hit branches of `dev:task-next`, split out of `SKILL.md` so the hot path stays small. Open
this file when one of the cases named in `SKILL.md` → *Edge cases* fires.

**Work already in flight** — feature branch with uncommitted changes from a previous session.
This is the routing target when the Prerequisites "Working tree gate" finds an in-flight branch
rather than stray dirty files. Run 3 ordered, cheap checks to produce a specific diagnosis
before asking for confirmation — this only automates the *diagnosis* text, not the resume
action itself; always still ask yes/no.

1. **Commits already ahead of `main`?**
   ```bash
   commits=$(git log main..HEAD --oneline 2>/dev/null)
   [[ -n "$commits" ]] && echo "commits exist — task-review-cycle Step 1 already ran"
   ```
   If `$commits` is non-empty, `task-review-cycle` Step 1 (commit) already ran. Diagnosis:
   offer `task-review-cycle --from task-next --auto` directly — plus `--qa-pending` and the
   restated Sprint Contract unless QA is *known* to have run (see **Whether QA is still owed**
   below). Commits ahead of `main` no longer prove it did: on the default full-cycle path QA
   happens inside the cycle at 2-4, after the Step 1 commit.

2. **No commits ahead, but an active Sprint Contract?**

   The working-tree gate already routes a dirty main checkout with a matching `.worktrees/` path
   here. Diagnose "`--tree` run in flight in `<path>`" (read the matching path captured by the
   gate) and route the user to inspect/resume that worktree, or abort it via `references/tree.md`'s
   QA-failure cleanup block, instead of the diff-based verdict below.

   ```bash
   active_block=$(grep -c "^status: active" tasks.md 2>/dev/null)
   ```
   A zero here is not proof no sprint is running — a single-item backlog.md cycle keeps its
   Sprint Contract inline and never writes `tasks.md` (see **Mark active** in Step 3), so this
   check alone cannot see it. If `$active_block` is zero, fall through to check 3's generic
   fallback rather than concluding no sprint is active. If `$active_block` is non-zero, check
   what's already changed to distinguish stage. Include
   untracked files (`git diff --stat` alone misses new files an implementer created but never
   staged — e.g. a brand-new script):
   ```bash
   code_diff=$(git diff --stat -- . ':!tasks.md' ':!backlog.md' ':!CHANGELOG.md' ':!**/plugin.json' 2>/dev/null)
   untracked=$(git ls-files --others --exclude-standard -- . ':!tasks.md' ':!backlog.md' ':!CHANGELOG.md' ':!**/plugin.json' 2>/dev/null)
   bump_diff=$(git diff --stat -- '**/plugin.json' 2>/dev/null)
   ```
   - `$code_diff` and `$untracked` both empty, `$bump_diff` empty → Sprint Contract written, no
     implementation yet. Diagnosis: resume at **Step 3 – Implement**.
   - `$code_diff` or `$untracked` non-empty, `$bump_diff` empty → implementation in progress, no
     version bump yet. Diagnosis: resume at **Step 3 – version bump**, then Step 4's handoff. On
     the default full-cycle path there is no QA stage left to resume here — it is owed to the
     cycle's 2-4 slot; on the lite path, `--tree` and `--all`, resume at their QA step as before.
   - `$bump_diff` non-empty → implementation and version bump both done. Diagnosis: resume at
     **Step 4 – Handoff**.

3. **Neither of the above matched** → state is genuinely unclear from these cheap checks; fall
   back to the generic offer: "I see uncommitted changes on `<branch>`. Skip to
   `task-review-cycle --from task-next --auto`?" — with `--qa-pending` and a restated contract
   per **Whether QA is still owed** below, which this branch almost always triggers.

**Whether QA is still owed.** A resumed run must decide this before handing off, and it is not
inferable from commits: on the default full-cycle path QA lives in the cycle's 2-4 slot, *after*
the Step 1 commit. Treat QA as owed unless this session has the verifier's own verdict in hand, or
the run was a lite/`--tree`/`--all` path (all three verify before handing off). QA owed → hand off
with `--qa-pending` **and** the Sprint Contract restated verbatim, or the cycle stops and asks for
it. When the contract cannot be recovered — the usual case under check 3, where `tasks.md` may
already be pruned — do not append the flag blind: reconstruct the contract with the user from the
diff and the backlog item first, and say that is what you are doing.

Present the diagnosis (or check 3's fallback to the generic offer) and ask for confirmation:
- **Yes:** resume at the diagnosed step (or call the Skill tool with "dev:task-review-cycle" and `args: --from task-next --auto` — adding `--qa-pending` plus the restated contract when QA is owed — for
  check 1 / the generic fallback).
- **No:** ask whether to (a) stash and start a fresh task, (b) commit the in-flight work
  first, or (c) cancel. Do not proceed until the tree is clean or the user redirects.

**Deferred backlog item (≥2 candidates)** — item has `*(deferred: ...)*`. Surface the blocker
and confirm it is resolved before proceeding. If unresolved, skip to the next candidate.
If all candidates are deferred with unresolved blockers, report that and stop.
(For the single-candidate case, see Step 2 table.)

**Deferred item in a group** — if any item in a heading group is deferred and the blocker
is unresolved, note it as a warning but continue with the non-deferred items in that group.
If all items in the group are deferred, skip the group (see Step 2 deferred-items rule).

**Review finding spans multiple PRs** — scope narrowly to the specific `file:line` ref.
Record broader related items back to `backlog.md` via the out-of-scope path in task-review.
