# Multi-Agent Coordination Patterns

Five patterns, when to pick each, and their failure modes. Source: Anthropic's
"Multi-agent coordination patterns" (2026) + internal experience.

Most coding work is **sequential with shared state** and does NOT benefit from
multi-agent. Pick a pattern only when the task clears the selection flowchart
in `docs/delegation.md`. When unsure, default to **Orchestrator-Subagent**.

## 1. Generator-Verifier

One agent generates output; a separate agent grades it against explicit,
written criteria. Rejection loops back to the generator.

- **Use when:** Output has objective pass/fail criteria (tests pass, schema
  valid, rubric met).
- **Key rule:** The verifier is only as good as its criteria. A verifier told
  to "check if it's good" rubber-stamps. Write gradeable criteria first — see
  `docs/eval-criteria.md` → Sprint Contract.
- **Already embedded:** This harness uses Generator-Verifier as the default
  implementation workflow (generator implements, QA/evaluator grades).

## 2. Orchestrator-Subagent

A lead agent decomposes work into bounded subtasks, delegates each to a
subagent, then synthesizes. Subagents do NOT talk to each other.

- **Use when:** Work decomposes cleanly into independent units; findings go
  one-way (subagent → lead).
- **Limitation:** The orchestrator is an information bottleneck. If two
  subagents need to share an intermediate finding, this pattern wastes tokens
  routing everything through the lead.
- **Already embedded:** This is the default pattern in `docs/delegation.md`.

## 3. Agent Teams

Multiple persistent workers share a task list and message each other directly.
Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (Claude Code v2.1.32+).

- **Use when:** Work is genuinely parallel AND teammates need to share
  findings mid-flight (cross-layer refactor, adversarial debugging, parallel
  code review with cross-domain concerns).
- **Limitation:** Each teammate has a full context window — token cost scales
  linearly. Coordination overhead grows with team size. Start with 3-5
  teammates max.
- **Setup:** See `references/agent-teams-onboarding.md`.

## 4. Message Bus

Agents publish to / subscribe from shared topics. New agents integrate without
rewiring existing ones.

- **Use when:** Event-driven pipelines with a growing agent ecosystem
  (security ops, alert triage, emergent workflows from webhooks).
- **Limitation:** Debugging cascading events is hard; routing errors fail
  silently. Overkill for normal software projects.
- **Not recommended** as an init-time pattern. Add only when the project
  actually runs an event bus.

## 5. Shared State

Agents read/write a persistent store directly, no central coordinator.
Findings propagate immediately via the store.

- **Use when:** Research synthesis, knowledge accumulation, long-running work
  where agents build on each other's output.
- **Limitation:** Without explicit coordination, agents duplicate work or take
  contradictory directions. Needs strong file ownership discipline — see
  `docs/workflows.md` → File Ownership Declaration.
- **Partial adoption:** `backlog.md` / `tasks.md` / `handoff-{feature}.md` are
  a lightweight shared-state substrate this harness already ships.

---

## Selection Flowchart (mirror this in `docs/delegation.md`)

```
Q1. Does the task decompose into >1 genuinely parallel subtask?
    No  → single session. Stop.
    Yes → Q2.

Q2. Do the subtasks need to share findings mid-flight (not just report at end)?
    No  → Orchestrator-Subagent.
    Yes → Q3.

Q3. Is there an objective written criterion the output must satisfy?
    Yes → Generator-Verifier (wrap Q2's answer with a verifier gate).
    No  → Q4.

Q4. Does this project run an event bus / webhook fan-out?
    Yes → Message Bus (only if infra already exists).
    No  → Q5.

Q5. Long-running, research-like, agents build on each other's notes?
    Yes → Shared State (backlog.md + handoff files).
    No  → Agent Teams (if parallel exploration genuinely helps) or stop
          and reconsider whether multi-agent is right at all.
```

## When NOT to Use Multi-Agent

Skip multi-agent entirely when ANY of these hold:

- All agents would need identical context
- Heavy inter-agent data dependencies (one blocks the next)
- Real-time coordination required (turn-taking, not parallel)
- Small, sequential edits (<3 files, <200 LOC change)
- Most coding tasks — the research-vs-coding asymmetry is real: code changes
  have fewer parallelizable independent subtasks than literature searches do

Anthropic's data: multi-agent shines for **valuable, highly parallelizable
tasks with information exceeding one context window**. That's a narrow slice.
