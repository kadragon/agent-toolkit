# Backlog

## Harness — `task-*` prose reduction

Source: `docs/design/harness-altitude-audit.md`. Highest-value work in this file: it pays every run
by shrinking the procedure a `task-next` invocation loads before reading any repo file. One h3 per
item so each is independently selectable. Every item here carries the same acceptance bar — before
editing, enumerate the current behaviors as a checklist; every deleted line must map to a row that
is preserved elsewhere or explicitly retired with a reason, and report the measured `wc -w` delta.

### Script the deterministic `task-*` nodes

- [ ] [HARNESS] Script branch derivation, CHANGELOG `## Unreleased` insertion and backlog-line deletion in `task-next`/`task-new`, and have both invoke the existing `scripts/bump-version.sh` instead of restating the bump rules in prose.

### Tighten the `backlog_candidates.py` guard

- [ ] [FIX] `task-next/SKILL.md:44,115` test `[[ -d "$SKILL_DIR/scripts" ]]` — the directory, not the script. A missing/unreadable `backlog_candidates.py` or a failing `python3` passes the guard. Test the file and the exit status; add a test per failure mode. **Blocks the fallback deletion below** — until this lands, the fallback covers real uncovered states.

### Drop the `task-next` Step 1 hand-grep fallback

- [ ] [HARNESS] Delete `task-next/SKILL.md:59–142` (~95 lines re-stating `backlog_candidates.py` in prose). Replace with one line stating the skill stops if the bundled script is unavailable. *(blocked by: tighten-guard)*

### Collapse the pre-merge cleanup variants

- [ ] [HARNESS] Merge the three near-identical cleanup procedures (`task-next/SKILL.md:293–344`) into one parameterized block plus a 3-row source table (tasks.md h1 / tasks.md finding group / backlog.md group).

### Single-source the CHANGELOG Entry Contract

- [ ] [DOCS] The `≤160 chars` rule is restated in 6 locations across 5 files (`docs/conventions.md:40`, `harness-invariants.md:109`, `task-new/SKILL.md:136`, `task-next/SKILL.md:302,310,318`, `batch.md:127`). Keep one canonical statement in `harness-invariants.md`; link from the rest. Pairs with the lint below.

### Cut the QA delegation rationale

- [ ] [DOCS] `task-next/SKILL.md:268–276` argues *why* the qa-verifier spawn is an exception to the delegation gate. Reduce to one sentence; move the argument to `docs/delegation.md`, read once rather than every run.

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

### CHANGELOG Entry Contract lint (edge #10)

- [ ] [CONSTRAINT] Enforce the ≤160-char single-line rule with a lint in `harness-check.yml`. Real payoff is deleting the 6 prose restatements above, not the block itself.

### qa-verifier evidence check (edge #6)

- [ ] [CONSTRAINT] `PreToolUse(Bash)` on `git commit`, gated on an evidence file tied to the current diff. The acceptance condition is **"an evidence file exists and matches the current diff"** — not "verification was independent", which this cannot check. Word the hook message accordingly. While the hook is open, also assert `tasks.md` has a `status: active` block (edge #9, ~3 lines, not worth a standalone item).

### Numeric cap on CI rework (edge #8, C3)

- [ ] [HARNESS] Count `ci-wait.sh` non-zero exits and hard-stop at 3. Scored 2.5/3 — decidable from exit codes, and CI minutes are a resource a re-run does not reclaim. Low priority; the prose-reduction section outranks it. Do **not** extend this to C2 ("same fix attempted 3×") — that predicate needs model judgment and was cut.

### Cut — do not re-file without new evidence

Re-filing requires evidence of the specific kind each item failed on, not a restated intuition:

- **Review transport accounting (edge #7)** — cut on verified grounds: `task-review/SKILL.md:90,162,281` already distinguish reviewed-empty from skipped and surface both, and both route to the same action. Re-file only with a recorded cycle where the two states led to *different* correct actions.
- **Semantic same-fix detector (edge #8, C2)** — failed Decidable. Re-file only with a deterministic predicate (an exact rule over files/exit codes) that does not require judging whether two attempts are "the same fix".
- **Edges #9, #11, #12** — scored 1.5/3, 0.5/3, 1/3 individually. #9 rides the hook above; the other two need a recorded failure that escaped the session.
