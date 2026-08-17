## Batch mode (`--all`)

Triggered by `--all`. Implements **multiple** units in parallel (each in its own git worktree),
then collapses them onto **one integration branch** that goes through a **single** version bump,
cleanup pass, and `task-review-cycle --auto` → one PR, one CI run, one merge.

**Why one integration branch, not N PRs.** The shared single-copy files — `plugin.json` manifests,
`backlog.md`, `tasks.md`, `CHANGELOG.md` — cannot be edited per-unit in parallel without collision.
`task-review-cycle` also detects its branch from the session's current checkout and cannot be aimed
at a worktree. So worktrees do **code only**; every shared-file edit happens once, serially, on
the integration branch in the main checkout. This sidesteps the whole class of cross-worktree
merge/CWD failures.

### A1 — Gather

Run the **full scan** from Step 1 (skip the fast path — batch mode always needs the complete list). The output is a list of **units**: each unit is
one heading group. Heading-based grouping naturally scopes each unit to one logical area, which
minimizes (but does not guarantee) conflicts when units merge into the integration branch in A6
— shared imports/utilities may still collide, which A6 handles.

### A2 — Filter to batch-eligible

A unit is **batch-eligible** only if ALL hold:
- Trivial: tag is NOT `[FEAT]`/`[REFACTOR]`, total in-scope files ≤2 (across the heading group), no new public API/schema. Non-trivial units need interactive plan-mode approval
  (single-pick Step 3) that cannot run N-way in parallel.
- In-scope files do **not** include any convergence-owned shared file (`plugin.json` manifests,
  `backlog.md`, `tasks.md`, `CHANGELOG.md`). Those are edited only in A6; a unit whose actual
  task is to edit them would collide with convergence — run it solo.

List excluded units explicitly: "Excluded from batch (needs solo run): `<unit>` — `<reason>`".
If filtering leaves 0 eligible units, report that and stop.

### A3 — Multi-select

Do NOT use `AskUserQuestion` (4-option cap is too small for a batch). Render a numbered list,
one line per eligible unit: index, type tag, short slug, file:line (bundles list member count
and area). Accept a comma list (`1,3,4`), inclusive ranges (`1-3`), `all`, or a combination.
Map back to units; ignore out-of-range indices and report them. Empty/unparseable reply →
re-prompt once, then stop. Non-interactive run: skip the prompt — select every eligible unit
(`--all` already asked for them) and announce the list, subject to the cost gate below. See
`dev:harness-init` → `references/harness-invariants.md` → *Non-Interactive Gate Defaults*.

**Cost gate** — each selected unit costs roughly implementer + qa-verifier (the review cycle
runs only **once** for the whole batch, not per unit). If the user selects **more than 6 units**,
state the rough multiplier and ask for explicit confirmation before A4. This gate never
auto-defaults: in a non-interactive run, abort and report instead of confirming on the user's
behalf. CLAUDE.md token economy
applies — the parallelism must earn its cost.

### A4 — Parallel implement (worktrees, code only)

The **main session owns worktree lifecycle** — do NOT use the Agent `isolation: "worktree"`
flag (that worktree is scoped to one agent's lifetime; it may not survive the later A5/A6
steps). Keep worktrees **inside** the repo (an external `../` path can fall outside an agent's sandbox);
ensure `.worktrees/` is git-ignored — if it is not yet, add it to `.gitignore` (this edit lands
on the integration branch in A6). `git fetch` first, then base every worktree on the **same**
`origin/main` the A6 integration branch will use — otherwise a stale local base inflates merge
conflicts in A6 and drops units that would have merged cleanly. For each selected unit, before
fan-out:

```bash
git worktree add ".worktrees/<slug>" -b "wt/<slug>" origin/main   # one per unit
```

Then fan out one implementer agent per unit in a single message (concurrency self-caps). Each
agent's brief (four-field per `docs/delegation.md`) gives the **absolute worktree path** and
these explicit CWD instructions (agents spawn in the main checkout CWD, not the worktree):

> "Your spawn CWD is the main checkout. The Bash tool is stateless — CWD resets each call.
> Every Bash command must begin with `cd <absolute-worktree-path> &&`
> (e.g. `cd /path/to/worktree && git commit -m '...'`).
> Read/Edit/Write tool calls must use absolute paths under `<absolute-worktree-path>/`.
> Do NOT read or edit any file in the main checkout.
> Never run `git push --force`/`--force-with-lease`, `git reset --hard`, `git clean -f`/`-fd`,
> or `git branch -D` — if a fix seems to need one, stop and ask the user instead.
> If the same fix is attempted 3+ times on the same file without the lint/test command
> passing, stop and report to the user instead of continuing to retry.
> When you finish (or get stuck), deliver your result via SendMessage(to: 'main') — do not end
> silently, even if the run failed. See SKILL.md's Result-handoff rule."

Then the brief continues:
1. Implement the unit's **code only**. Do NOT touch `backlog.md`, `tasks.md`, `plugin.json`,
   or `CHANGELOG.md` — all cleanup edits happen once in A6.
2. **Return** the Sprint Contract text (Scope / Acceptance criteria / Out of scope / Lint-test
   command per `docs/eval-criteria.md`; one acceptance checkbox per bundled item) as part of the
   agent's output — it is NOT written to `tasks.md` here. A5 reads it from this return value.
3. **Commit the code to `wt/<slug>`** (e.g. `[WIP] <unit>`), leaving a clean tree. Return the
   worktree path, branch, the Sprint Contract, and a change summary — via SendMessage(to: 'main')
   per the instruction above, not just as a final response.

The agent must NOT verify its own output. If an agent fails or returns unusable output, drop
that unit: `git worktree remove --force .worktrees/<slug>` and `git branch -D wt/<slug>`, then
record it for the final report — do not abort the others.

### A5 — Parallel QA

For each successfully-implemented unit, spawn a `qa-verifier` agent (separate from the
implementer) pointed at that unit's worktree path, verifying against the Sprint Contract that
unit returned in A4. Include the same CWD instructions in each brief: every Bash command must
begin with `cd <absolute-worktree-path> &&`; Read/Edit/Write use absolute paths under the
worktree; the same destructive-command guard applies — QA must not run
`git reset --hard`/`push --force`/`clean -f`/`branch -D` either. Same result-handoff
instruction too: tell each QA agent to deliver its verdict via SendMessage(to: 'main'),
including an empty/no-blocking-findings verdict — see SKILL.md's Result-handoff rule. Fan out
all QA agents in one message.

For any unit with blocking findings, fan out **one** implementer→qa-verifier retry per blocking
unit (all retries in one message — they are independent; do not serialize). Still blocking after
one retry → drop the unit (remove its worktree + branch as in A4) and record it. One unit's
failure never blocks the others.

### A6 — Collapse to one integration branch, then converge once

All of this runs in the **main checkout** (correct CWD/branch for the convergence tools), not in
any worktree.

1. **Create the integration branch off latest base** — `git fetch`, then
   `git checkout -b <type>/batch-<slug> origin/main` (pick the dominant `[type]` across units, else
   `fix/`). `<slug>` is a short batch descriptor.
2. **Merge each verified unit branch in** — for each unit, `git merge --no-ff wt/<slug>`.
   Disjoint areas (A1) keep this clean. On conflict: `git merge --abort`, drop that unit (record
   it), and continue with the rest — the integration branch keeps the units that merged cleanly.
   Keep the merged-units list and the conflicted-units list from this step — A7 consumes them
   directly and must not re-derive merged-vs-conflicted from any later `git branch` command (the
   integration PR is squash-merged, so post-merge branch state cannot distinguish the two).
   If every unit conflicts/drops, abandon: `git checkout main && git branch -D <type>/batch-<slug>`,
   then jump to A7 cleanup and report (do not leave the checkout stranded on a dead branch).
3. **Collect cleanup targets — once.** For each merged unit, record what to delete:
   - **backlog units** → all open `- [ ]` lines directly under the unit's heading group in `backlog.md` (read the heading section; every `- [ ]` item under it is a deletion target). Findings groups (`### PR #N` under `## Review Backlog`) are backlog units like any other — same file, same rule.
   - **sprint blocks** → the unit's `# <title>` block in `tasks.md`, deleted with `--block`
4. **Version bump — once.** `bash scripts/bump-version.sh <plugin> <major|minor|patch>` per touched
   plugin, a single time for the whole batch (it keeps both manifests in sync). Bump level per that
   script's header / `docs/conventions.md`; hand-edit only where the script is absent.
5. **Pre-merge cleanup — once.** Same subcommands as single-pick (SKILL.md → *Pre-merge cleanup*),
   run once over the whole batch's collected targets:
   ```bash
   SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
   NODES="$SKILL_DIR/scripts/task_nodes.py"
   [[ -r "$NODES" ]] || { echo "Bundled script missing or unreadable: $NODES" >&2; exit 1; }
   python3 "$NODES" prune-tasks --file tasks.md --block "<sprint h1 title>"   # only if a sprint block exists
   printf '%s\n' "<every completed backlog.md item line>"  | python3 "$NODES" prune-backlog --file backlog.md
   python3 "$NODES" changelog --file CHANGELOG.md --title "<batch-slug>" --units <N> \
     --plugin <plugin> --version <X.Y.Z> [--link docs/<owning-doc>.md]
   ```
   A heading is dropped only where this batch emptied it, `## Review Backlog` in `backlog.md` goes
   the same way once empty, and `--units <N>` produces the batch entry's `(<N> units)` clause. **No
   per-unit breakdown** in the entry — the units are enumerated in the PR body. A batch title over
   the cap is refused at write time by the repo's `scripts/ci/check_changelog_entries.py`. What no
   script can decide — the ban on explanatory clauses — lives in the *CHANGELOG Entry Contract* in
   `harness-invariants.md`; read it rather than reconstructing the limits.
   - **Blocked-analysis sync**: apply the same bidirectional sync as single-pick Step 3 (SKILL.md → Pre-merge cleanup → *Blocked-analysis sync*), scoped to items the A1 full scan inspected this batch — mark newly-found blocked items, clear markers whose blocker landed in this same batch. Disclose in the PR body; skip silently if nothing synced.

   Leave all edits uncommitted — `task-review-cycle` Step 1 commits them.
6. **Hand off — once.** Call the Skill tool with "dev:task-review-cycle" and `args: --from task-next --auto`. Running from the
   main checkout on `<type>/batch-<slug>`, it correctly detects the branch, commits the integration
   work, opens **one** PR, collects reviews, applies in-scope findings, records out-of-scope items
   to `backlog.md`, waits CI, and merges.

**If the integration PR fails CI and must be abandoned:** close the PR; the unit branches still
exist, so you can re-run convergence after fixing, or fall back to single-pick per unit.

### A7 — Cleanup & report

The main session removes every worktree it created (`git worktree remove .worktrees/<slug>`;
`--force` for any with leftover changes). For unit branches, use A6 step 2's recorded
merged-units and conflicted-units lists to decide — do not use a `git branch -d`/`-D` exit code as
the signal, since the integration PR is squash-merged and no `wt/<slug>` commit stays reachable by
identity from `main` afterward (so `-d` would fail even for cleanly merged units). For every unit
on the **merged** list, force-delete `git branch -D wt/<slug>` — its work is safely in the
integration branch, then the PR, then `main`. Units on the **conflicted** list passed QA in A5 but
failed the integration merge — their `wt/<slug>` branch must **not** be deleted; leave it intact
for manual resolution. Units dropped earlier (A4/A5 implementer/QA failure) were already
force-removed at that point and never reach A7. If the batch was abandoned (all units
conflicted/dropped), the integration branch was already deleted in A6 step 2. Then emit a summary
table: each unit → merged-into-PR / dropped (reason) / conflicted (branch `wt/<slug>` preserved
for manual resolution), plus the single PR link and final merge status. This is the only place
per-unit outcomes are surfaced, so do not skip it.
