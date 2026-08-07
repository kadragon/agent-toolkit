# Backlog

## Harness — PR #203 follow-ups (Codex review, landed after merge)

Codex's review of PR #203 returned after the merge, so these were never applied in-cycle. Items 3
and 4 were reproduced against the merged code this session; 1 and 2 are read-verified but not
executed.

- [ ] [FIX] `reconcile-harness.py` `failed` branch closes a hand-authored `[>]` sprint without reverting its backlog line, and the next `tasks.md`-absent run deletes that `[>]` via `remove_orphan_markers` — failed work is lost instead of returning to `[ ]`. Either revert on `failed` for `[>]` lines only, or drop `[>]` from the documented state table in `references/backlog-template.md`
- [ ] [FIX] `task_nodes.py prune_lines` prose-only exemption uses `alive.get(h, 1) > 1`, which spares EVERY h1, not just the file root. Reproduced: `# Backlog` + `# Other` + `## Group`, drain the group → `## Group` goes but `# Other` and its intro prose stay orphaned. Restrict the exemption to the first heading in the file
- [ ] [FIX] `references/tasks-template.md` `## Covers` example shows `- [FIX] mktemp guard in codex-review.sh`, missing the `- [ ] ` prefix, and still names `# Sprint Title` as the fallback target. `prune-backlog` matches verbatim, so a contract copied from this template exits 1 and leaves items queued. Fix the example to the full checkbox line and drop the stale fallback claim
- [ ] [PLAN] `task-next --tree` with a single-item group now writes no `tasks.md` and leaves the item `- [ ]`, so the main checkout stays clean and a second invocation re-picks the same candidate instead of seeing it in flight. Decide whether `--tree` needs an in-flight lock or should force the file-backed contract

## Self-improvement loop — Signal 8 verifier-grounded failures (D1)

Source: `docs/design/harness-self-improvement-loop.md` D1.

## Self-improvement loop — loop contract + prediction schema (D5+D3)

Source: `docs/design/harness-self-improvement-loop.md` D3, D5.

## Self-improvement loop — validation gate in curate routing (D2)

Source: `docs/design/harness-self-improvement-loop.md` D2.

## Self-improvement loop — prediction re-audit step (D4)

Source: `docs/design/harness-self-improvement-loop.md` D4.

## Self-improvement loop — capture prediction line (D6)

Source: `docs/design/harness-self-improvement-loop.md` D6.

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

### Cut — do not re-file without new evidence

Re-filing requires evidence of the specific kind each item failed on, not a restated intuition:

- **commit-guard merge coverage** — cut at ≈1/3 after scoring, which is what the item itself asked for before any build. Both named sites were read, and neither is a mistake to catch. (1) `merge-and-cleanup.sh:86–89` runs its `git merge --ff-only FETCH_HEAD` only inside `if [ "$MERGE_OK" = "true" ]` — the remote PR merge has already landed — and immediately after `git fetch origin "$BASE_BRANCH"`, so it fast-forwards local `main` onto a commit that is already on the remote. It creates no state and pushes nothing; there is nothing there to guard. (2) `task-next`'s lite path merges to `main` **by design**, reached only when the user picks `[1] 라이트 패스` at Step 2.5 — a decision, not the unintended landing the commit guard exists for. (3) Decisive: the only opt-out `guard.py` implements is the repo-wide `<!-- commit-guard: allow-main -->` marker read by `_marker_present`, and both guards consult it. Marking the repo to let the lite path merge would also switch off the branch guard on `git commit` — trading a 3/3 mechanism for a 1/3 one. A separate marker avoids that only by adding a second opt-in surface to maintain. *Silent* and *Costly* therefore rest on a hypothetical third site; only *Decidable* holds outright. Re-file only with a recorded incident where a merge landed on `main` unintentionally — not from either site above.
- **qa-verifier evidence check (edge #6)** — cut on verified grounds, re-scored from 2.5/3 to ~0.5/3. Three findings, in order of decisiveness. (1) *Decidable fails outright:* the gate cannot fire where the item assumed it would — `task-review` commits through `commit-and-push.sh`, which `commit-guard` did not see at the time this was cut (`docs/design/harness-altitude-audit.md` → *Superseded*, which also records the dev v4.0.33 `--precommit-check` fix that closed it). (2) *Silent and Costly hold only on the lite path:* the full cycle puts every commit through three reviewers, the P0/P1 verifier agent, and CI before merge, so a skipped QA is caught pre-merge and the residual failure is bounded — failing the doc's own "2/3 ships only if the residual failure is unbounded" clause. Only `task-next`'s lite path (direct `merge --no-ff` + push to `main`, no PR, no CI) leaves it unbounded. (3) *The diff match is unworkable even if (1) were fixed:* `task-review` Step 5 commits code edited in Step 4 — review findings applied **after** QA ran — so the evidence hash is stale on every cycle where any finding is applied, and excluding bookkeeping files does not help because these are real code edits. Separately, the gated actor holds the write primitive: an orchestrator with Bash can create the evidence file in one command, so the hook cannot establish even that *something* ran. Re-file only with a recorded cycle where QA was skipped on the lite path and the miss reached `main`.
- **Review transport accounting (edge #7)** — cut on verified grounds: `task-review/SKILL.md` already distinguishes reviewed-empty from skipped and surfaces both — see its *Collect Reviews* 600s-breach rule, the three "Reviewers Skipped: …" labels, and the reviewer prompt's *"Send the array even when it is empty ([]) so the slot is recorded as reviewed, not stalled"* — and both route to the same action. Re-file only with a recorded cycle where the two states led to *different* correct actions.
- **Semantic same-fix detector (edge #8, C2)** — failed Decidable. Re-file only with a deterministic predicate (an exact rule over files/exit codes) that does not require judging whether two attempts are "the same fix".
- **Edges #9, #11, #12** — scored 1.5/3, 0.5/3, 1/3 individually. #9 (assert `tasks.md` has a `status: active` block) was only ever viable as ~3 lines riding inside the edge #6 hook; with #6 cut it has no carrier and does not stand alone at 1.5/3. All three need a recorded failure that escaped the session.
