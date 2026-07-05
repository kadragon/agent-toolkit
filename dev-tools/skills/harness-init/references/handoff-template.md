# Handoff File Template

Handoff files enable **clean context resets** between sessions or sub-agents,
preserving continuity without preserving context rot.

This works only within a single Claude Code session (scratchpad-backed). There is currently no supported mechanism for genuine multi-day/cross-session resume — don't imply otherwise.

## When to Write One

- **Early in a long-running task, while context is fresh and the plan
  is clear**, NOT when context is already degraded. A degraded agent writes
  degraded handoffs. Survives compaction within the same session.
- **Before spawning a fresh subagent** for a long-running task that the
  current session was about to hit context limits on.
- **Before switching teammates** on a task in Agent Teams mode.

## Where

- Per-feature: `handoff-{feature}.md` in the session scratchpad dir (path from
  the system prompt). Gone automatically when the session ends.
- Ad-hoc sub-agent spawn: pass inline as part of the spawn prompt, referenced
  via file path.

## Required Schema

```markdown
# Handoff: {feature or task name}

**Started:** {YYYY-MM-DD}
**Last updated:** {YYYY-MM-DD HH:MM}
**Current owner:** {agent id / "orchestrator" / session id}

## Objective

{1-3 sentences. What is this work trying to accomplish, from the user's POV?
Not "what have we done" — "what is the goal.")

## Completed Phases

- [x] {phase 1} — {1-line result}. Key artifact: `{path or link}`
- [x] {phase 2} — {1-line result}. Key artifact: `{path or link}`

Each entry MUST be a concrete, checkable outcome. "Investigated auth" is bad.
"Confirmed that JWT expiry check lives in `src/auth/jwt.ts:42` and fires
before body parse" is good.

## Current Phase

- [ ] {in-flight work}

What the next agent should pick up immediately. Include exact next step.

## Open Questions

- {question 1 — who/what needs to resolve it, and by when}
- {question 2}

Keep this list short. If it exceeds ~5 items, the work isn't decomposed
enough — split into sub-handoffs.

## External State

Things the next agent can't infer from the repo alone:

- **User decisions:** "{user chose X over Y on {date}} because {reason}"
- **Environment:** "{test DB seeded with fixture Z}"
- **Pending external:** "{PR #123 waiting on review}"

Omit the section if there's nothing external.

## Next Agent Contract

**Objective:** {what the next agent should produce}
**Output format:** {file diff / PR / report / backlog items}
**Tools to use:** {grep, specific MCP, test harness, …}
**Boundaries:** {what NOT to touch — modules, files, workflows}

This section mirrors the **Spawn Prompt Contract** from
`references/delegation-template.md` → "Spawn Prompt Contract". A handoff IS a
deferred spawn prompt.

## Decision Log (optional)

For judgment calls that future agents might second-guess:

- **{date}** — Chose {option A} over {option B}. Reason: {1 sentence}.
```

## Anti-Patterns

- **Narrative handoff** — "I looked at the auth module and thought about X
  then realized Y…". Useless. Replace with concrete artifacts + decisions.
- **Handoff written at 90% context** — the handoff itself is now degraded.
  Write earlier, or do a context reset first and regenerate from primary
  sources.
- **Handoff as dumping ground** — do not paste tool outputs. Summarize the
  conclusion + the path where the evidence lives.
- **Missing "Next Agent Contract"** — without the 4 delegation fields, the
  next agent will re-derive scope from scratch. That's the bug this file
  exists to prevent.

## Lifecycle

1. **Create** early in a long-running task (Step 2 of `code` workflow if
   scope warrants it).
2. **Update** in-place when a phase completes — append to Completed Phases,
   replace Current Phase.
3. **Cleanup is automatic** — the scratchpad dies with the session. No manual delete needed.
