# Design Rationale

Why `harness-init`'s rules are what they are. The rules themselves live in `SKILL.md`; this file holds the evidence, the failure modes that produced each rule, and the bounds that keep it from misfiring. Read a section when you are about to deviate from the corresponding step, when a rule looks arbitrary, or when re-examining the harness after a model upgrade.

## Core philosophy

Three sources inform the design:

1. **Anthropic** — Generator-Evaluator separation; every harness component encodes a model-limitation assumption that needs periodic re-examination. (The "context reset over compaction" guidance from the same source is itself one such assumption — re-check it per model; see `references/workflows-template.md` → Context Anxiety.)
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

**Two limits — both places the filter has actually misfired:**

1. A block carrying `<!-- harness:verbatim … -->` is out of scope. It was mandated deliberately, so "the agent already knows this" is not an argument against it.
2. The filter licenses cutting what the agent would rediscover *from the repo*. It does **not** license cutting a line because some higher-precedence instruction file (the base harness, `~/.claude/CLAUDE.md`, a parent AGENTS.md) supposedly already says it. That is a different claim and far easier to get wrong, because those files are not in front of you while you edit. If you cut on those grounds, quote the covering text in the proposal; if you cannot quote it, you have not verified it, so keep the line. And a quote only settles it on a **single-tool** repo — AGENTS.md is read by Codex/Cursor/Copilot too, each with its own base instructions, so "Claude's base harness already says this" leaves the line load-bearing for every other reader.

**Why the mandated blocks carry their marker.** The `## Maintenance` edit policy and `## Token Economy` rules are copied verbatim, and the mandate lives in a skill that only loads while harness-init runs. An AGENTS.md carrying those blocks *unmarked* reads to any later trimming pass (`claude-md-improver`, `/doctor`, a human editor) as generic boilerplate — exactly the shape the filter deletes. The marker travels with the file and lets the block defend itself, for ~8 tokens, rendered invisibly in Markdown.

## Instruction-layer reconciliation (Step 0b)

**Why ask instead of deciding.** Precedence between layers is **not spec**. Never assert a winner you cannot quote a source for — which is exactly why a contradiction is a question for the user rather than a silent call.

**How to ask.** Surface it before generating the affected file, not after: quote both sides verbatim (`file:line` for the global file; for base instructions, quote the covering text and label it `[base instructions — {model id}, this session]`, since no `file:line` exists), state which side you recommend and why, then ask which is authoritative. Batch every conflict into one prompt — one round-trip, not one per rule.

**Asking does not mean halting the run.** Generate every artifact the conflict does not touch first, then ask, then write the affected ones. That ordering is itself what a global hard-stop rule typically requires — this operator's, verbatim: *"Material ambiguity affecting scope, irreversible effects, external communication, or expected output → finish everything independent of the answer first, then Grill: one question at a time (or one batched question prompt), each with recommended answer + rationale; answer in code → read, don't ask."* Read the invoking layer's own wording rather than assuming this one; `Skill(dev:task-grill)` is available when the conflicts need real interviewing. <!-- notation-exempt: availability note, not a step this file runs -->

**Running without a user to ask — never block.** This skill is reachable from a subagent or teammate, where the ask has no recipient. The same operator layer covers it: *"Running AS a subagent/teammate: no user access — never block. State the assumption, finish the work, surface the open question in the return value."* So: generate the non-conflicting artifacts, skip the conflicting rule rather than guessing at it, state the assumption, and surface the conflict — both sides quoted — in the return value. The Step 9 checklist item is satisfied by surfacing it upward, not by having an answer.

**Two bounds, so the gate doesn't become noise:**

- It fires on *contradiction*, not resemblance. Similar phrasing about different subjects, and a repo rule that merely reaches a tool the global file cannot, are not conflicts. Reuse the non-findings list in `dev:harness-curate` → `references/signal-taxonomy.md` §7 rather than re-deriving one.
- It covers rules **this run is about to write**. Auditing conflicts already sitting in an existing `AGENTS.md` / `docs/` / `.claude/rules/` belongs to `dev:harness-curate`'s Signal 7 — Audit mode points there instead of re-implementing that sweep.

## Docs language (Step 1)

Conversation language and docs language are unrelated: the first is a UI preference for one session, the second governs version-controlled repo artifacts. Defaulting to the chat language is the **observed failure** — Korean docs written into a repo whose Language Policy, authored in the same session, said docs are English.

Domain terms with no real equivalent in the target language (a local platform's proper name, a regulatory term, a framework's own field labels) stay in the source language: they are data, not prose, and translating them destroys the referent.

**Why matcher text is carved out.** Trigger phrases, `description:` fields, and router route patterns are matched against what the operator actually *types*. A pattern in the wrong language never fires, so an English docs policy does not license stripping Korean trigger alternates from a repo whose operator prompts in Korean.

## Token Economy overlap

Current Claude models are already told to batch independent tool calls, not to re-read a file they just edited, and not to restate the user. On a **Claude-Code-only** repo, trim those items and keep only the repo-specific ones (what to delegate, what "conclusion only" means here). On a multi-tool repo the block stays whole — the repo copy is that rule's only reach on Codex/Cursor/Copilot. Either way, drop any item whose entire content is "the model already behaves this way on every tool you target" — the same load-bearing test the sweep applies to everything else.

## Auto-delegation is description-driven

Auto-invocation runs off each `SKILL.md` / agent `description:` field, and field reports put it well below 100% even with good descriptions ([Scott Spence, "Claude Code Skills Don't Auto-Activate (a workaround)", 2025-11-06](https://scottspence.com/posts/claude-code-skills-dont-auto-activate)). Anthropic's skill-creator docs report that directive phrasing ("ALWAYS invoke when X — do NOT inline-execute") improved auto-invocation on 5 of 6 public skills over descriptive phrasing ("Triggers on X").

That is why directive descriptions are the primary mechanism and the trigger router is an evidence-gated fallback: the router costs a hook on every prompt plus a routes file to keep in sync, and a stale router is worse than none. This repo's own harness ships no router and relies on descriptions alone.

## Relation to the platform's own `/init`

Claude Code ships a built-in `/init` (and newer interactive variants) that bootstraps a basic CLAUDE.md plus optional skills/hooks. This skill **complements** it rather than duplicating it: harness-init produces the multi-layer harness — AGENTS.md map, docs knowledge base, path-scoped rules, enforcement chain, maturity progression — that platform `/init` does not. If the repo already ran `/init`, treat its CLAUDE.md as Step 1 input and migrate or extend it; do not overwrite blindly.
