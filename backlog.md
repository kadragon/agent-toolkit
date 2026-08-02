# Backlog

## Harness — task-* graph enforcement

Source: `docs/design/task-graph-audit.md` (edge enforcement audit — 5 of 12 pipeline edges are
mechanically enforced, all of them node-output checks, none of them transition checks).

- [ ] [CONSTRAINT] qa-verifier gate — block the implement → commit transition unless an independent
      qa-verifier ran. Use the Delegation Gate pattern already shipped in
      `dev/skills/harness-init/references/enforcement-template.md` (PreToolUse evidence file under
      `.claude/tmp/`). Closes audit edge #6.
- [ ] [CONSTRAINT] review-slot handoff accounting — a review slot that never returns via
      `SendMessage(to: "main")` must be recorded as unreturned, distinctly from a 600s timeout, so
      silently dropped findings are visible in the consolidation table. Closes audit edge #7.
- [ ] [HARNESS] shared loop-counter / circuit breaker for the three prose-capped cycles: qa retry
      (1×), stuck-fix (3×), CI failure rework (3×). `task-next/SKILL.md` documents that no such
      tooling exists. Reuse the Circuit Breaker template in `enforcement-template.md`. Closes audit
      edge #8.
- [ ] [HARNESS] script out the deterministic nodes in `task-next` / `task-new` — branch derivation
      from `[type]` tag, plugin version bump, CHANGELOG `## Unreleased` insertion, backlog line
      deletion. Currently prose instructions with 1 and 0 bundled scripts respectively, against
      `task-review`'s 11.
- [ ] [CONSTRAINT] CHANGELOG Entry Contract lint — enforce the ≤160-char, single-line,
      no-explanatory-clause rule mechanically instead of restating it in three skill bodies.
      Closes audit edge #10.
