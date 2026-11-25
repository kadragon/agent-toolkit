# Escalation

Read this when a child stalls, its review cycle sends the change back, or its result turns out
wrong, and when a later phase of an escalated task launches.

- Escalate one step when the session stalls on the same blocker twice, its review cycle sends
  the change back twice, or its result turns out wrong. Raise effort before the model, since
  it is the cheaper step. `luna`, `terra` and `sol` are Codex `gpt-6-luna`, `gpt-6.1-terra` and
  `gpt-6.2-sol`.

| Effective quota bias | Ladder |
|----------------------|--------|
| `none` | `terra/medium → terra/high → opus/high → opus/xhigh` |
| `codex` | `terra/medium → terra/high → terra/xhigh → sol/high → sol/xhigh` |
| `claude` | `sonnet/medium → sonnet/high → opus/high → opus/xhigh` |

- A pair on the ladder takes the next rung. Any other pair takes the lowest rung that is at
  least as high on both axes and higher on at least one (haiku = luna < sonnet = terra < opus = sol).
- When the next rung is on a `critical` CLI, ask the user. A stall at the top rung (opus/xhigh
  or sol/xhigh) goes to the user; `fable` and `gpt-6.2-astra` are never a rung.
- Carry the latest escalated pair as the floor for later phases as a tier and an effort: take
  the higher tier and effort from that pair and the new phase's starting pair, then pick the
  CLI for that tier by the new phase's bias. Without escalation, each phase uses its own
  starting pair.

## Relaunch

Escalating relaunches the same phase. For a `--tree` run, read the worktree slug first
(`hc read --lines 60 <address>`). When authorized to end the old child, run
`dispatch.py collect <old-receipt> --close --force` and confirm it closed. Clean up the old
receipt per [Close the child terminal](../SKILL.md#close-the-child-terminal). Then launch per
SKILL.md step 4 with the new pair and the same first message. For a `--tree` run, keep its
worktree and use `/dev:task-next --resume <slug>` as the first message.
