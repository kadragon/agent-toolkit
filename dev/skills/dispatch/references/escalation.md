# Escalation

Read this when a child stalls, its review cycle sends the change back, or its result turns out
wrong, and when a later phase of an escalated task launches.

- Escalate one step when the session stalls on the same blocker twice, its review cycle sends
  the change back twice, or its result turns out wrong. Raise effort before the model, since
  it is the cheaper step: `sol/medium → sol/high → opus/high → opus/xhigh → fable/xhigh`
  (`sol` is codex `gpt-6.2-sol`; models rank haiku < sonnet = sol < opus < fable).
- A pair on the ladder takes the next rung. Any other pair takes the lowest rung that is at
  least as high on both axes and higher on at least one: sol/low → sol/medium,
  haiku/low → sol/medium, sonnet/medium → sol/high, opus/medium → opus/high,
  sonnet/xhigh → opus/xhigh.
- Under a `claude` quota bias read `sol` on the ladder as claude `sonnet`, so a climb does not
  land back on the CLI that is running ahead: sonnet/medium → sonnet/high → opus/high.
- When the next rung is on a `critical` CLI, ask the user. A stall after fable/xhigh goes to
  the user.
- Never step down from an escalated pair inside one task: once a phase escalates, later
  phases take the pair from the tables or the escalated pair, whichever is higher on each
  axis. Without an escalation each phase re-reads the tables, so a spec phase at xhigh can
  hand off to an implementation phase at high.

## Relaunch

Escalating relaunches the same phase, not the next one, and never goes through `hc send`:
`hc kill <address>`, `hc rm <address>`, then launch per SKILL.md step 4 with the same first message
and the new pair. A `--tree` run resumes its worktree instead: read the slug from the session
before killing it (`hc read --lines 60 <address>`) and launch with `/dev:task-next --resume <slug>`
as the first message.
