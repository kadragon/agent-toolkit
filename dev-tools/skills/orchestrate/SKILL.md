---
name: orchestrate
description: Multi-agent delegation playbook — decide whether to use a single sub-agent, Agent fan-out, or the Workflow tool, plus model routing, verify/fix loops, and a delegation brief template. Use when about to orchestrate work across agents, fan out parallel tasks, set up a Workflow, run a verify-until-green loop, or split a task across sub-agents ("orchestrate", "fan out", "parallel agents", "write a workflow", "split this across agents", "delegate this"). For general task delegation — NOT the PR review-and-merge flow (see dev-review-cycle).
---

# Orchestrate

The main thread is the orchestrator. Default to delegation; do broad work through sub-agents, not inline. This skill is the **decision layer** — for Workflow recipe syntax (pipeline/parallel/loop), read the Workflow tool's own description; don't duplicate it here.

## Decision tree — task shape → tool

1. **Clear, bounded, 1–2 files?** → do it inline. Don't delegate trivial work.
2. **Need to read/search across many files, scope uncertain?** → one `Explore` (broad sweep) or `cavecrew-investigator` (compressed locator). You keep the conclusion, not the file dumps.
3. **Several independent tasks, no shared state?** → `Agent` fan-out — one message, multiple Agent calls, run concurrently.
4. **Multi-stage with control flow (find→verify→fix, migrate-each-site, audit-then-confirm)?** → `Workflow` tool. Deterministic loops/conditionals/fan-out beat model-driven juggling.
5. **Unknown-size discovery (find all bugs / edge cases)?** → Workflow loop-until-dry: keep spawning finders until K rounds return nothing new.

Barrier rule: only put a barrier between stages (a `parallel()` step, which awaits all of stage N-1) when stage N needs **all** of stage N-1 (dedup, early-exit-on-zero, cross-item compare). Otherwise `pipeline` — no wasted wall-clock.

## Verify/fix loop (the "keep going until green" discipline)

Don't declare done at first green. For behavior-changing work, loop until the gate passes:

```
diagnose → fix → run gate (test/build/lint/typecheck) → still failing? repeat
```

Encode as a Workflow `pipeline` where the last stage runs the gate, or a loop that re-spawns a fixer until the gate exits 0. Adversarial check for findings: spawn N independent skeptics prompted to **refute**; keep the finding only if a majority can't.

## Model routing

| Work | Model |
|------|-------|
| Cheap, parallel, mechanical (locate, grep-summarize, format) | Haiku |
| Hard reasoning, design, synthesis, adversarial review | Opus |
| Default / unsure | inherit (omit override) |

Don't set a model override unless highly confident the tier fits. When unsure, inherit.

## Delegation brief — every sub-agent gets all four

- **Goal** — the outcome, one sentence.
- **Constraints** — what not to touch, style to match, scope ceiling.
- **Exit criterion** — verifiable: "test X passes", "returns file:line table", "exits 0".
- **Context/files** — paths, commands, prior findings it needs.

Vague brief = delegation problem, not agent problem. Sub-agent output is the return value, not a human message — ask for raw data (use a `schema` in Workflow for structured returns).

## Anti-patterns

- ❌ Delegating a trivial edit (overhead > work). → inline.
- ❌ Fanning out **dependent** tasks in parallel (B needs A's result). → pipeline or sequence.
- ❌ Silent caps — if you bound coverage (top-N, sampling, no-retry), `log()` what was dropped. Silent truncation reads as "covered everything."
- ❌ Grinding 10 files inline because spinning up an agent "feels heavier." That's the exact failure this skill exists to break.
