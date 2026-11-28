# Escalation

Read this when a child stalls, its review cycle sends the change back, or its result turns out
wrong, and when a later phase of an escalated task launches.

## Review send-backs

Before choosing the next rung for two consecutive send-backs, check `dispatch.py collect` →
`scope_decision_categories`. It compares blocking categories in reviews of the same change,
including reviews of different candidate commits. Count each verdict once. For a child that
reports without `review_sendbacks`, compare the last two confirmed verdicts for that change
using their review output.

When the two verdicts share a category, keep the current child and pause escalation. Show the
user the shared category and a concrete finding from each verdict. Ask them to narrow the
guarantee or explicitly bound what it covers and excludes. Resume after they choose and the
child records the clarified contract. When the two verdicts have distinct categories, follow
the existing ladder below.

## Ladder

- Escalate one step when the session stalls on the same blocker twice, its review cycle sends
  the change back twice, or its result turns out wrong. `luna`, `terra` and `sol` are Codex
  model families; the launcher resolves each to its newest listed slug.
- First ask: did it not try hard enough, or did it not know enough? (Claude Code team's
  model-versus-effort heuristic.) Skipped searches, files or tests, an early stop or an unchecked
  result is not trying hard enough — raise effort. Confident errors of fact, API or domain, or a
  wrong approach that persists at the raised effort, is not knowing enough — raise the model tier.
  When the evidence does not say which, raise effort first, since it is the cheaper step.

| Effective quota bias | Ladder |
|----------------------|--------|
| `none` | `sol/medium → sol/high → opus/high → opus/xhigh` |
| `codex` | `sol/medium → sol/high → sol/xhigh` |
| `claude` | `sonnet/medium → sonnet/high → opus/high → opus/xhigh` |

- A pair on the ladder takes the next rung. Any other pair takes the lowest rung that is at
  least as high on both axes and higher on at least one (haiku = luna < sonnet < opus = sol).
  A "not know enough" diagnosis may skip the remaining effort rungs of its tier. Under bias `codex`,
  move from `sol` to `opus/high` only with an allowed `--bias-exception` or an explicit user pin.
- `terra` writing or visual work raises effort on `terra` up to `xhigh`, then takes
  `opus/high` (`sol/high` under bias `codex`) and continues on that bias's ladder.
- A pair on `opus` stays on Claude: `opus/medium → opus/high → opus/xhigh`. This covers top-tier
  work under bias `none`, work the `codex` bias keeps on `opus` (SKILL.md step 3), and work the
  user put on `opus`. Reapply the launch gate with the current quota and any valid override.
- When the next rung is on a `critical` CLI, ask the user. A stall at the top rung (opus/xhigh
  or sol/xhigh) goes to the user; `fable` and `astra` are never a rung.
- Carry the latest escalated pair as the floor for later phases as a tier and an effort: take
  the higher tier and effort from that pair and the new phase's starting pair, then pick the
  CLI for that tier by the new phase's bias. An `opus` floor stays on `opus` (line above). Any
  other floor that is not a rung of that bias's ladder takes its lowest rung at least as high on
  both axes. A `terra` floor carries only its effort: a later writing or visual phase starts
  `terra` at that effort, and any other phase ignores it. Without escalation, each phase uses its
  own starting pair.

## Relaunch

Escalating relaunches the same phase. Check the replacement pair before stopping the current child
with `launch --dry-run`. If quota refuses it, keep the current child and
choose a permitted rung or ask the user. For a `--tree` run, read the worktree slug first
with `dispatch.py peek <receipt>`. When authorized to end the old child, run
`dispatch.py collect <old-receipt> --close --force` and confirm it closed. Clean up the old
receipt per [Close the child terminal](../SKILL.md#close-the-child-terminal). Then launch per
SKILL.md step 4 with the new pair and the same first message. For a `--tree` run, keep its
worktree and use `/dev:task-next --resume <slug>` as the first message.
