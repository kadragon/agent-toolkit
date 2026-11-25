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
  the change back twice, or its result turns out wrong. Raise effort before the model, since
  it is the cheaper step. `sol` is Codex `gpt-6.2-sol`.

| Effective quota bias | Ladder |
|----------------------|--------|
| `none` | `sol/medium → sol/high → opus/high → opus/xhigh → fable/xhigh` |
| `codex` | `sol/medium → sol/high → sol/xhigh → opus/high → opus/xhigh → fable/xhigh` |
| `claude` | `sonnet/medium → sonnet/high → opus/high → opus/xhigh → fable/xhigh` |

- A pair on the ladder takes the next rung. Any other pair takes the lowest rung that is at
  least as high on both axes and higher on at least one (haiku < sonnet = sol < opus < fable).
- When the next rung is on a `critical` CLI, ask the user. A stall after fable/xhigh goes to
  the user.
- Carry the latest escalated pair as the floor for later phases, using the higher model and
  effort from that pair and the new phase's starting pair. The Codex-bias ladder's model
  switch from sol/xhigh to opus/high sets the new floor at opus/high. If a later phase still
  needs a sol/xhigh floor and its new bias does not allow Codex xhigh, use opus/xhigh.
  Without escalation, each phase uses its own starting pair.

## Relaunch

Escalating relaunches the same phase. For a `--tree` run, read the worktree slug first
(`hc read --lines 60 <address>`). When authorized to end the old child, run
`dispatch.py collect <old-receipt> --close --force` and confirm it closed. Clean up the old
receipt per [Close the child terminal](../SKILL.md#close-the-child-terminal). Then launch per
SKILL.md step 4 with the new pair and the same first message. For a `--tree` run, keep its
worktree and use `/dev:task-next --resume <slug>` as the first message.
