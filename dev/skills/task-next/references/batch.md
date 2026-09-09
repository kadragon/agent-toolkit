## Batch mode (`--all`)

`--all` selects multiple queue units. Execute sequentially in one session by default, then run
one integrated validation, version bump, cleanup, and review cycle. Parallel execution is a
separate cost/independence decision, not the meaning of the flag.

### A1 — Gather and select

Run Step 1's full scan. One heading group is one unit. Preserve empty-queue, blocked/deferred,
and malformed-input behavior from the candidate selector. Zero eligible units → report and stop
without creating a branch or contract.

Render a numbered list with tag, scope, and blockers. Accept comma lists, inclusive ranges, or
`all`; report out-of-range indices. Empty/unparseable input → re-prompt once, then stop.
Non-interactive `--all`: select ready units within already approved scope and announce them.

### A2 — Decide execution mode

Apply `cycle.md` → *Plan gate* once to unresolved decisions in the selected batch. Reuse approved
scope, criteria, and approach for each unit. Neither `[FEAT]` nor file count excludes a unit.

**Sequential (default):** small tasks, coupled units, shared-file edits, or work whose preparation
and hand-off cost outweighs parallel savings. Use one branch and an aggregate Sprint Contract,
with criteria and exact backlog lines per unit. Follow the shared cycle; run relevant checks
per unit and full required checks on the final candidate. Review the combined result once.
A failed unit stops dependent work; preserve changes and report the unmet criterion.

**Parallel:** use only when all selected parallel units have approved scope, independently
verifiable outcomes, no dependencies on each other, and disjoint file ownership (including
imports, tests, lockfiles, and generated outputs). Expected implementation effort must justify
worktrees and separate implementation/QA, and the platform's delegation gate must also pass.
Explain the expected benefit and ownership before fan-out. Small tasks remain sequential.

Shared convergence files (`plugin.json` manifests, `backlog.md`, `tasks.md`, `CHANGELOG.md`) are
owned by the integration session. A unit whose actual scope edits one of them runs sequentially.
More than six parallel units → confirm the implementer + QA cost explicitly; unattended runs
use sequential execution instead. Remaining steps apply only to the parallel path.

### A3 — Parallel implementation

The main session owns worktree lifecycle; do not use agent-lifetime worktree isolation.
Ensure `.worktrees/` is ignored, fetch the base once, and create the integration branch and every
unit worktree from that same fetched base. Preserve any authorized backlog-only edits on the
integration checkout. Create a worktree with `git worktree add .worktrees/<slug> -b wt/<slug>
<captured-base-commit>`; use actual values discovered this run.

Archive the aggregate contract from the integration branch before spawning. Each implementer
gets its approved unit contract, absolute worktree path, owned files, and relevant test commands.
Follow `docs/delegation.md` when present; otherwise include objective, output format, tools, and
boundaries in each brief. Every shell call must set its worktree CWD; file tools use absolute
paths. Agents may edit only their owned files, never the main checkout or convergence files.
No force push, hard reset, force clean, or force branch deletion. The same fix attempted 3+
times on one file without the checks passing → stop; the `Agent` tool has no timeout, so this cap
is the only bound on a looping unit. A stuck agent reports the failure in its final output, never
finishing silently; it cannot ask the user directly.

Each implementer archives its unit contract in the worktree, implements and runs focused checks,
then commits only unit changes on its own branch. Return branch, worktree, contract/archive path,
checks with exit codes, and unmet criteria. Incomplete/unusable results remain recoverable on
that worktree/branch; exclude them from integration and report why.

### A4 — Unit QA

Use a separate `qa-verifier` per successful unit, with the same CWD/ownership restrictions.
Grade requirements and code quality against the unit contract; reuse eligible test evidence per
`cycle.md` → *Validation evidence*. One fix-and-QA retry for a blocking finding. Still blocked
or verifier unavailable → preserve the unit and exclude it from integration; report the limit.

### A5 — Integrate and converge

1. In the main checkout on the integration branch, merge verified unit branches. On conflict,
   abort that merge and preserve the conflicting branch/worktree for resolution. Record merged,
   excluded, and conflicted units explicitly; do not infer them from post-squash ancestry.
2. If nothing integrates, stop with all recoverable work preserved. Otherwise, confirm the
   aggregate contract covers exactly the integrated units; retain excluded unit contracts and
   revise the aggregate with the explicit partial-result scope, without claiming those units done.
3. Run the shared cycle from *Version bump* through *Validation evidence*: one bump per touched
   plugin, cleanup only for integrated units, and full required checks on the integrated candidate.
   Pass `--units <N>` to the `changelog` command with the count of integrated units, so the entry
   reads as a batch. Worktree checks do not certify integration. Keep archives before pruning
   `tasks.md`.
4. Hand off once: call the Skill tool with "dev:task-review-cycle" and
   `args: --from task-next --auto`, carrying the aggregate contract, archive, evidence, and unit
   outcomes. One integration PR, CI, and merge. Failed CI keeps all unit recovery state intact.

### A6 — Cleanup and report

After confirmed successful merge, remove only clean worktrees whose units landed. Use the
recorded integrated-unit list; squash ancestry cannot prove unit identity. Delete a unit branch
only after its saved tip is confirmed included in the integrated result; any required force
operation follows the user's authorization policy. Preserve failed/conflicted/unmerged units
and archives. Report each unit's outcome, preserved branch/worktree, PR link, and merge status.
