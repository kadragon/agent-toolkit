# Backlog

## Harness — task-* graph enforcement

Source: `docs/design/task-graph-audit.md` — 5 of 12 pipeline edges are mechanically enforced, and all
five check a node's output rather than a transition. One h3 per item so each is independently
selectable.

### qa-verifier gate (edge #6)

- [ ] [CONSTRAINT] Block implement → commit unless an independent qa-verifier ran — `PreToolUse(Bash)` on `git commit`, evidence file tied to the current diff.

### Review transport accounting (edge #7)

- [ ] [CONSTRAINT] Track each review slot's declared transport (Agent `SendMessage` vs captured stdout) so an unreturned slot is distinguishable from a timeout.

### Loop caps C1/C2/C3 (edge #8)

- [ ] [HARNESS] Semantic retry counter plus a blocking event (`PreToolUse`/`SubagentStop`) — the shipped `PostToolUse` circuit breaker cannot block or model these cycles.

### Deterministic node scripting

- [ ] [HARNESS] Script branch derivation, CHANGELOG insertion and backlog-line deletion in `task-next`/`task-new`, and have both invoke the existing `scripts/bump-version.sh`.

### CHANGELOG Entry Contract lint (edge #10)

- [ ] [CONSTRAINT] Enforce the ≤160-char single-line rule mechanically instead of restating it across four files.
