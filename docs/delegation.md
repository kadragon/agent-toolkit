# Delegation

Apply platform/base/global constraints first. The local policy below specializes only what
those layers permit; it never relaxes a higher-level prohibition or invents an exception.

Default inline; delegate research or implementation only when the user or an applicable
skill directs it and the work meets this repository's provisional threshold: 10+ files
to investigate, 3+ genuinely independent units, or substantial context pressure.
These thresholds remain local policy pending evidence for changing them.

An authorized workflow's independent verification is assessed separately for its
independence benefit and cost; neither file count nor parallelism alone gates it.
It remains optional unless an already authorized workflow requires it, including the
existing review/worktree QA. Eligibility never mandates a spawn.

## Pattern Selection

After the permission and local-policy checks above pass, select by task shape:

| Task shape | Route |
|---|---|
| One isolated research/verification task with a material context or independence benefit | Subagent eligible; no parallel sibling required |
| Independent parallel tasks requiring findings to be exchanged during execution | Agent Team eligible where supported |
| Independent parallel tasks whose results can be combined at completion | Subagents eligible |
| Tightly coupled/sequential work, or no material isolation benefit | Inline |

These routes describe eligibility, not a requirement to spawn. A sequential workflow may
still contain an independently useful verification step.

## Role Routing

No row below grants permission. After the applicable checks above pass, match the job to the role:

| Job | Delegate to | Model | Context to pass |
|-----|-------------|-------|-----------------|
| Read-only map of an unexplored plugin area | `explorer` | sonnet | Plugin dir path |
| Implementation task from `backlog.md` | `implementer` | sonnet | Backlog item, conventions, target files |
| Verifying an implementation | `qa-verifier` | sonnet | Modified files, test/lint commands |
| Skill quality assessment requested | `skill-evaluator` | opus | Skill path, eval-criteria.md |

`qa-verifier` never runs on its own output — whoever implemented must not be the one who verifies.
That constraint holds whenever a verifier runs; it does not by itself mandate spawning one.

**Why the review cycle reviews out-of-process.** `task-review-cycle` always runs one reviewer,
which runs `code-review` and grades the Sprint Contract. What that buys is **independence** — a
check by something that did not write the code — which is a correctness property, not a volume
one: a 1-file fix needs it as much as a 20-file one. It is not a subagent: the cycle shells out to
a headless `claude -p` (`scripts/claude-review.sh`) in the foreground, because the Bash tool
enforces a timeout while the `Agent` tool does not, and an agent's completion notification can be
lost (upstream claude-code #49150, #58637, #68117) — which stalled cycles on reviews that had
already finished. A headless process also carries no session context, so independence is stronger
there, not weaker. `task-next --tree` and parallel `--all` units keep a per-worktree `qa-verifier` for the same
correctness reason. Those checks belong to the authorized workflow's independent verification;
research and implementation still require direction and the provisional local threshold.

## Task-specific Model Selection (provisional)

Choose model and reasoning effort per authorized delegated task by complexity, risk,
and verifiability. Optimize expected total cost: initial work, retries, lead review,
and executable verification, including elapsed time and tokens. This is an evaluation
hypothesis; improved quality or cost has not been demonstrated by paired runs.

| Advisory tier | Task signals | Selection rationale |
|---|---|---|
| Light | Clear input, low failure impact, mistakes readily detected by a cheap check | Favor a supported economical model/effort combination |
| Standard | Some ambiguity or interacting requirements, bounded impact, reliable checks | Balance reasoning capability against expected retry and review cost |
| Deep | Material ambiguity, high failure impact, or mistakes hard to detect | Consider greater reasoning capability and stronger verification |

These tiers neither authorize delegation nor impose a workflow gate or provider mapping.
Prefer a justified per-spawn choice when the runtime and higher-level instructions permit
it; otherwise use the resolved platform default. See `docs/platform-specs.md` →
*Subagent Model and Effort Resolution* before interpreting an override or omitted model.
Use only model/effort combinations supported by the active client and account.

The Role Routing table's pins are current defaults retained until evaluation. Keep
role-specific pins when evidence favors them; removing every pin is not the objective.
Headless review selection remains owned by `dev:task-review-cycle`, separately from this
subagent policy. This policy adds no router, global rules, telemetry, or duplicate roles.

Escalate reasoning capability only after an observable miss suggests it is insufficient:
for example, repeated failure on a valid reproduction after the task and inputs are clear.
Check environmental failures, unavailable tools, and contradictory requirements first;
those do not establish a model deficiency. Carry findings and unresolved issues into any
retry. Compare total retry/review cost before recommending a permanent pin change in the
queued model-selection evaluation.

## Background Routing (non-blocking)

| Trigger | Delegate to | Context |
|---------|-------------|---------|
| Every PR | `dev:task-review-cycle` skill, with `--from <your skill name>` (`/task-review` is the human entry point and supplies the token itself) | PR number or current branch |
| Harness check request | `dev:harness-curate` skill | — |

## Escalation

| Trigger | Action |
|---------|--------|
| Same failure ×2 | `codex:rescue` with an explicit brief — what failed, what was already tried |
| Once the cause is known | Encode verified recurring failures mechanically (hook/lint/test) where evidence justifies it |

## Spawn Prompt Contract (all 4 fields mandatory)

Every `Agent(...)` call must include:

```
- Objective: {what specifically to accomplish}
- Output format: {diff / report / table / verdict}
- Tools to use: {subset of role's allowlist}
- Boundaries: {files/modules this spawn must NOT touch}
```

Missing any field → reject and rewrite the spawn prompt.

## Effort Tier

This is the task/brief tool-call budget axis. It is independent of the advisory
Light/Standard/Deep model-selection axis: there is no mandatory one-to-one mapping.
A model tier grants no extra calls and leaves the stop/report rule unchanged.

Embed in every spawn prompt:

| Tier | Use for | Tool calls | Model |
|------|---------|------------|-------|
| Simple | Known-answer lookup, single-file edit, mechanical check | 3–10 | haiku/sonnet |
| Comparison | Weighing options, multi-file review, cross-module check | 10–15 | sonnet |
| Complex | Root cause unknown, architectural decision | 15+ | opus |

The tool-call count is a budget, not a guideline. Brief the stop rule with the tier: at the cap,
stop and return what was gathered, with every unfinished item marked `unverified` and why — never
keep going until the lead has to message "stop and report". Transcripts showed that nudge six
times in Codex cycles whose briefs named a tier but no stop rule.

## Data Transfer Protocols

| Strategy | Mechanism | Use when |
|----------|-----------|----------|
| Return value | Agent tool result | Sub-agent reports to orchestrator |
| File-based | Session scratchpad dir, `{phase:02d}_{agent}_{artifact}.{ext}` | Large artifacts, cross-phase handoff |
| Task-based | `TaskCreate`/`TaskUpdate` | Progress tracking, dependency gates |

Naming: `{phase:02d}_{agent}_{artifact}.{ext}` — e.g. `01_explorer_map.md`, `02_implementer_diff.md`.

The orchestrator determines its scratchpad path once (from its own system prompt) and embeds the full path explicitly in every spawn prompt — sub-agents must not guess or reconstruct it. Scratchpad is ephemeral: gone when the session ends, no cross-session resume.

## Result handoff

A role-file agent (`.claude/agents/*.md`) runs under its `tools:` allowlist, and none of those
lists grants `SendMessage` — as a subagent or as a named teammate. It reports through its **final
output**, which reaches the orchestrator as the Agent tool result (the completion notification for
a background spawn) — brief it to put the full result in its final response and never finish
silently, even when the result is empty or the run failed. Brief `SendMessage(to: "main")` only to
a spawn whose tools actually include it: a bare `Agent` with no `subagent_type`; never to a
role-file agent. Do not rely on it as the only channel — a lost notification is a known upstream
failure, which is why the review cycle returns its findings over a shell boundary instead.
