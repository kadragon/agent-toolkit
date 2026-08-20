# Backlog

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

## Harness — `task-*` cycle latency

Source: latency measurement of 2026-08-19, recorded here so no run re-derives it. GitHub Actions
`harness-check` completes in 13–22s across the last 25 runs, so **CI is not the bottleneck**. PR
create→merge is ~3–17 min (median ~10 min), and that window is almost entirely
`task-review-cycle` Step 2 (review panel) plus Step 3 (verifier + contest agents). One non-trivial
cycle runs **four sequential agent waves** — implement → `qa-verifier` → 3-source panel →
verifier/contest — and the panel's wall clock is `max()` of its three sources, not the sum. Recent
merged PRs run 5–28 files and +8/-7 to +720/-20; median ≈9–13 files, ≈50–100 lines.

Ordered so the isolated, low-risk items land before the Step 2 restructure they would otherwise
conflict with.

- [ ] **Run QA in parallel with the review panel** — `qa-verifier` is its own blocking wave in front of the panel in both `task-new` and `task-next` Step 3, so the panel cannot start until contract QA has finished. Commit and open the PR right after implement, then launch `qa-verifier` in the same turn as 2-1/2-2/2-3 and fold its contract findings into the Step 3 consolidation table as a fourth source. Version bump and pre-merge cleanup move into the Step 5 commit. Four waves become three. The independence rule is unchanged: whoever implemented still never verifies.
- [ ] **Trim `task-next`/`task-new` SKILL.md to references** *(blocked by: qa-in-parallel)* — `task-next/SKILL.md` is 37KB and `task-review-cycle/SKILL.md` 30KB, re-prefilled on every turn of every cycle. The absent-role fallback prose is restated at each of the three spawn points in both skills, the roster-check block is duplicated across them, and `## Edge cases` is ~80 lines that a typical run never reaches. Move the rarely-hit branches into `references/` the way batch/tree mode already are, leaving the hot path in `SKILL.md`. No behavior change — this is a token cut.

## Harness — capture-before-use across block boundaries

- [ ] [harness] `check_harness_drift.py`'s capture-before-use scan is per-block, so it cannot see a `$var` read in one ```bash block that was captured in another — it passed the defective `PANEL_START` floor in `task-review-cycle` Step 2 (PR #240, caught by the review panel, not by CI). Extend the checker to track captures across the blocks of a single skill document and flag a read whose only capture lives in an earlier block, or state in `docs/conventions.md` that the linter does not own this half. Rule now written up under *Capture-Before-Use* in `docs/conventions.md`; the mechanical half is what is missing.

## Review Backlog

### PR #238 — [HARNESS] poll CI status every 5s for the first minute (2026-08-19)

- [ ] [debt] `CI_WAIT_POLL_INTERVAL=0` passes ci-wait.sh's numeric guard and busy-loops the slow polling path against the hub API (source: code-review) — `dev/skills/task-review-cycle/scripts/ci-wait.sh`, the `POLL_INTERVAL` numeric guard. Pre-existing hole, out of scope for #238, which floored only the fast-window interval it introduced.
- [ ] [harness] SKILL.md code blocks get `$N` substituted from the invocation args (source: session observation, PR #238) — `task-review-cycle` 2-1's `awk '{s+=$1}'` loaded as `awk '{s+=task-review}'` when the skill was called with `--from task-review`; the on-disk file is correct. Rewrite that site to avoid a positional, sweep the other skills for `$N` inside code blocks, and record the behavior in `docs/platform-specs.md`. The exact substitution rule is uncharacterized — one observation, not a derived mapping.
