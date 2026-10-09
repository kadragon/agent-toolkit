# Design Rationale

Why `harness-init`'s rules are what they are. The rules themselves live in `SKILL.md`; this file holds the evidence, the failure modes that produced each rule, and the bounds that keep it from misfiring. Read a section when you are about to deviate from the corresponding step, when a rule looks arbitrary, or when re-examining the harness after a model upgrade.

## Core philosophy

Three sources inform the design:

1. **Anthropic** — Generator-Evaluator separation; every harness component encodes a model-limitation assumption that needs periodic re-examination. (The "context reset over compaction" guidance from the same source is itself one such assumption — re-check it per model; see `workflows-template.md` → Context Anxiety.)
2. **OpenAI** — AGENTS.md is a map, not an encyclopedia (~100 lines); the repo is the system of record; golden principles are enforced mechanically; garbage collection is automated.
3. **Practical experience** — progressive disclosure (index → detail), agent-readable lint errors, sub-agent context manifests.

Key insight: **if the agent struggles, that is a harness defect**, not an agent defect. Fix the environment, not the prompt.

**Simplification principle.** Find the simplest solution; add complexity only when needed. Every component encodes an assumption about what the model cannot do alone — start minimal, add scaffolding on concrete failures. A harness built for the weakest model slows a stronger one down.

## Why init creates nothing speculative

The default-off decisions in Steps 4b, 4c, 5, 6, and the conditional docs in Step 4 are one rule applied five times: **an artifact that anticipates a problem the repo has not had yet is not insurance, it is noise.**

- A guessed **agent role** appears in the session's agent list and in AGENTS.md, promising a delegation that never happens. The operator learns the harness describes a repo that does not exist, and starts skimming all of it.
- A guessed **orchestrator** is the same failure one level up — it instructs the model to spawn agents that were never created.
- A **sweep** installed at init audits drift in a harness minutes old: guaranteed-empty findings, plus a cadence decision made before anyone knows the cadence.
- A **lint-message rewrite** at init edits the user's own configuration on the theory that an agent will one day misread an error.
- A **doc** whose content the agent would read from the code anyway is the case the ETH result below measured as actively harmful.

Each has an evidence trigger instead, and `dev:harness-curate` is the mechanism that watches for it: it mines transcripts, so it sees which delegations actually recur. That is knowledge init cannot have.

The corollary matters as much as the rule: **an empty roster is a designed state, never a finding.** `scripts/validate-harness.sh` reports these absences as `INFO`, and a permanent `WARN` for a file the repo correctly does not have is how operators learn to skim the report.

## Non-inferability filter (Step 3)

The target is redundant *description*: prose restating what the agent would discover by reading the code — architecture summaries, style rules the linter owns, a paraphrase of the README.

This is not a style preference. An ETH Zurich study ([arxiv 2602.11988](https://arxiv.org/abs/2602.11988)) found LLM-generated context files *reduced* task success in 5 of 8 settings (+2.45–3.92 steps/task, +20–23% inference cost) precisely because they restated facts the agent already reads from code; human-curated, non-inferable files gained ~4pp instead. So before writing a *descriptive* line, ask "would the agent already know this from the repo?" — if yes, delete it.

It does **not** prune navigational pointers (the `## Docs Index`, "read `docs/x.md` when …") or a concrete non-obvious command or example. Those name real files but earn their tokens by cutting discovery cost, which is the point of a map.

**Retain verified safety boundaries and navigation.** All generic blocks now pass the same
filter; no `harness:verbatim` marker exempts boilerplate from pruning. A claim that higher-level
instructions already cover a rule requires reading and quoting those instructions for the
targeted platforms. Multi-tool support does not automatically justify whole copied blocks.

## Conditional sections and size

Golden Principles records real project invariants, without a minimum count. Delegation applies
when configured Claude/Codex roles or actual workflows exist. Token Economy is optional,
project-specific guidance. An edit policy may be concise or an existing valid pointer rather
than a named four-item section. Validate presence mechanically; assess relevance/enforcement
manually. Correctly absent optional sections produce INFO, not recurring warnings.

The generation target remains 100 lines. Validation warns at 101–200 and strongly above 200;
session warnings start above 200 (explicit overrides retained). There is no size-only failure:
the former >120 failure contradicted the 100–200 soft zone and treated line count as correctness.
Broken references and malformed configuration still fail. Regression fixtures cover 99/100/101
and 199/200/201 with message and exit semantics, plus minimal and existing harnesses.

## Instruction-layer reconciliation (Step 0b)

Honor higher-level prohibitions without asking the user to choose which layer wins. Local
thresholds specialize only choices those layers permit; an inspected layer with no numeric
gate provides no number to attribute to it. Ask only for a material unresolved local decision,
and complete independent work while awaiting it. Existing-policy audits belong to
`dev:harness-curate`; this check covers rules the current init writes.

## Docs language (Step 1)

Conversation language and docs language are unrelated: the first is a UI preference for one session, the second governs version-controlled repo artifacts. Defaulting to the chat language is the **observed failure** — Korean docs written into a repo whose Language Policy, authored in the same session, said docs are English.

Domain terms with no real equivalent in the target language (a local platform's proper name, a regulatory term, a framework's own field labels) stay in the source language: they are data, not prose, and translating them destroys the referent.

**Why matcher text is carved out.** Trigger phrases, `description:` fields, and router route patterns are matched against what the operator actually *types*. A pattern in the wrong language never fires, so an English docs policy does not license stripping Korean trigger alternates from a repo whose operator prompts in Korean.

## Token Economy overlap

Use project-specific guidance only where it changes useful behavior. Check the actual targeted
instruction layers before retaining a duplicate; tool count alone is no reason to copy a generic
block. Output length is not a delegation trigger. A repository's evidence and authorized workflow
set its delegation boundaries, including the distinct benefit of independent verification.

## Auto-delegation is description-driven

Auto-invocation runs off each `SKILL.md` / agent `description:` field, and field reports put it well below 100% even with good descriptions ([Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)", 2025-11-06](https://scottspence.com/posts/claude-code-skills-dont-auto-activate)). Anthropic's skill-creator docs report that directive phrasing ("ALWAYS invoke when X — do NOT inline-execute") improved auto-invocation on 5 of 6 public skills over descriptive phrasing ("Triggers on X").

That is why directive descriptions are the primary mechanism and the trigger router is an evidence-gated fallback: the router costs a hook on every prompt plus a routes file to keep in sync, and a stale router is worse than none. This repo's own harness ships no router and relies on descriptions alone.

## Relation to the platform's own `/init`

Claude Code ships a built-in `/init` (and newer interactive variants) that bootstraps a basic CLAUDE.md plus optional skills/hooks. This skill **complements** it rather than duplicating it: harness-init produces the multi-layer harness — AGENTS.md map, docs knowledge base, path-scoped rules, enforcement chain, maturity progression — that platform `/init` does not. If the repo already ran `/init`, treat its CLAUDE.md as Step 1 input and migrate or extend it; do not overwrite blindly.
