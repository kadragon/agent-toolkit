# Competing Hypotheses Playbook

Adversarial debugging pattern. Multiple teammates each investigate a
different root-cause hypothesis AND try to disprove the others'. The theory
that survives peer attack is much likelier to be correct than the one a
single agent lands on via sequential investigation.

Source: Claude Code Agent Teams docs → "Investigate with competing
hypotheses". Use as an **on-demand** workflow, not a default.

## When to Use

- Root cause is genuinely unclear after a first pass by one agent
- Bug is reproducible but spans multiple layers (network / state / render)
- Stakes warrant extra tokens (user-facing incident, data loss risk)

Do NOT use for:
- Clear stack traces pointing to one file
- Lint / type errors
- Any bug fixable in <30 minutes by a single agent

## Prerequisites

- Agent Teams enabled: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`
- A reproducer committed to the repo
- A `findings-{bug-id}.md` shared-state file

## Procedure

1. **Lead** writes `findings-{bug-id}.md` with:
   - One-line bug statement
   - Reproducer steps
   - Empty sections per hypothesis: `## H1`, `## H2`, `## H3`, `## Consensus`

2. **Lead** spawns 3-5 teammates, each assigned ONE hypothesis. Each
   teammate's Spawn Prompt Contract:
   - **Objective:** investigate {Hn} AND actively attempt to disprove other
     hypotheses as teammates post evidence
   - **Output format:** append to `findings-{bug-id}.md` under your `## Hn`
     section with evidence paths + verdict (supports / weakens / inconclusive)
   - **Tools to use:** Read, Grep, Bash (for reproducer variants), Edit on
     the findings file only
   - **Boundaries:** no production-code edits; shared findings file is the
     only mutable target

3. **Teammates** work in parallel, messaging each other with challenges:
   - "H2 claims X but the log at {path:line} contradicts — please address"
   - Sender uses `message` (not `broadcast`) to keep cost linear

4. **Lead** monitors via `TaskCompleted` hook — when a teammate marks its
   hypothesis task done, lead reads the updated finding and decides whether
   to:
   - Extend investigation (add evidence request)
   - Drop the hypothesis (mark `## Hn` as disproven)
   - Converge (all remaining hypotheses point to same root cause → write
     `## Consensus` and close the team)

5. **Lead** writes the fix OR delegates to an `implementer` role with the
   consensus section pinned as context.

## Token Budget Guardrails

- **Hypothesis count cap:** 5. More hypotheses usually means the bug isn't
  understood well enough to split — go back to single-session scoping.
- **Per-teammate call cap:** 30 tool calls. Embed in spawn prompt. If a
  teammate can't reach a verdict in 30 calls, the hypothesis is probably
  wrong or too broad.
- **Wall-clock cap:** 45 minutes. Lead forcibly closes with whatever
  consensus exists.

## Failure Modes

- **Hypothesis overlap** — two teammates converge early and stop
  adversarially testing each other. Lead must explicitly prompt: "H1 and H2
  both point to {X}. Before accepting, test {Y} that would distinguish them."
- **Rubber-stamp debate** — teammates politely agree instead of challenging.
  Counter by spawning one teammate explicitly as "devil's advocate — your
  job is to find at least one flaw per hypothesis".
- **Anchoring** — first hypothesis posted dominates. Counter by having all
  teammates post initial verdicts BEFORE reading each other's findings
  (first round blind).

## Integration

Add to `docs/workflows.md` as an optional workflow named `debate`, with
entry condition "bug investigation where first-pass diagnosis failed". Most
projects will invoke it rarely — that's correct.
