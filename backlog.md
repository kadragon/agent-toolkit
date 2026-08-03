# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

### qa-verifier evidence check (edge #6)

- [ ] [CONSTRAINT] `PreToolUse(Bash)` on `git commit`, gated on an evidence file tied to the current diff. The acceptance condition is **"an evidence file exists and matches the current diff"** — not "verification was independent", which this cannot check. Word the hook message accordingly. While the hook is open, also assert `tasks.md` has a `status: active` block (edge #9, ~3 lines, not worth a standalone item).

### Cut — do not re-file without new evidence

Re-filing requires evidence of the specific kind each item failed on, not a restated intuition:

- **Review transport accounting (edge #7)** — cut on verified grounds: `task-review/SKILL.md:90,162,281` already distinguish reviewed-empty from skipped and surface both, and both route to the same action. Re-file only with a recorded cycle where the two states led to *different* correct actions.
- **Semantic same-fix detector (edge #8, C2)** — failed Decidable. Re-file only with a deterministic predicate (an exact rule over files/exit codes) that does not require judging whether two attempts are "the same fix".
- **Edges #9, #11, #12** — scored 1.5/3, 0.5/3, 1/3 individually. #9 rides the hook above; the other two need a recorded failure that escaped the session.
