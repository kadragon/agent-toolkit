# Writing for Agents

How to write a document an agent consumes — a `SKILL.md`, a reference file, `AGENTS.md`, a
`docs/` page reached by a pointer. The packaging differs; the writing does not. The goal is a
document that makes the agent take the same *process* every run, not one that produces the same
prose.

Adapted from [mattpocock/skills](https://github.com/mattpocock/skills)
`skills/productivity/writing-for-agents`. Scope split, so nothing here is restated elsewhere —
except where a shipped skill needs a portable inline fallback, as `dev:harness-capture` → *Writing
the delta* does for three of these levers:
frontmatter syntax lives in `docs/platform-specs.md`, who may fire a skill in
`docs/invocation.md`, how a finished skill is *graded* in `docs/eval-criteria.md`. This page is
about the writing itself.

## Context pointers

A **context pointer** is a reference held in the agent's context that names out-of-context
material and encodes the condition for reaching it. A skill `description:` is one. So is a row
in `AGENTS.md`'s docs index, and a `see docs/x.md` line inside a skill.

The pointer's *wording*, not its target, decides whether the material is reached. A must-have
target behind a weakly worded pointer is a variance bug: sharpen the wording first, and inline
the material only if sharpening fails.

A pointer does two jobs — state what the material is, and list the **branches** that should
trigger reaching it (a branch is a distinct case the target handles). Every word of an
always-loaded pointer costs on every turn, so it is pruned harder than the body:

- **Front-load the leading word** — the pointer's first words do its triggering work.
- **One trigger per branch** — synonyms that rename a single branch are one branch written
  twice.
- **Cut identity the body already carries.**

**A pointer that leaves this repo needs a fallback.** A skill shipped in `dev/` or `prod/` runs
in repos that never had this one's `docs/`, and `harness-init` generates those files only
conditionally — so `docs/conventions.md` → *Regression Test Rules*, read as "not restated here",
becomes a dead end wherever the section does not exist. State the rule's one-line inline form
beside the pointer, on the file-absent branch. Nothing in CI catches this: the pointer resolves
here, which is the only place the checkers look.

## The two loads

Every document and pointer spends one of two budgets:

- **Context load** — the cost of always-loaded material: an `AGENTS.md` line, a skill
  description, anything in context every turn, spending tokens and attention whether or not it
  fires.
- **Cognitive load** — the cost on the human: knowing which documents exist and when to reach
  for each. Not a cost to minimise; it is the price of human agency. Spend it where human
  judgement matters, remove it where it does not.

Material reached only through a pointer escapes context load at the price of the pointer's own
line. Material with no pointer at all rides entirely on cognitive load.

## Information hierarchy

A document is built from **steps** (ordered actions) and **reference** (definitions, rules,
facts consulted on demand). They mix freely. The decision is where each piece sits on a ladder
ranked by how immediately the agent needs it:

1. **In-file step** — what the agent does, in order. The primary tier.
2. **In-file reference** — consulted on demand. Often a legitimately flat peer set (every rule
   of a review on one rung); that is an arrangement, not a smell.
3. **Disclosed reference** — pushed into a separate file behind a context pointer, loaded only
   when the pointer fires.

Push too little down and the top bloats; push too much and the agent cannot find what it needs.
**Progressive disclosure** is the move down the ladder, and branching is its cleanest test:
inline what every branch needs, disclose what only some branches reach. In a document that has
steps, undisclosed reference buries them and turns attending to them into a coin flip.

**Co-location** is the within-file companion: the ladder decides how far down a piece sits,
co-location decides what sits beside it. Keep a concept's definition, rules, and caveats under
one heading so reading one part brings its neighbours along. (Distinct from duplication:
duplication repeats one meaning in two places; scattering fragments one meaning across many.)

**Sprawl** is the failure mode here — a document simply too long, even when every line is live
and unique. Attention thins across the excess. The cure is the ladder: disclose reference behind
pointers, and split by branch or sequence so each path carries only what it needs.

## Completion criteria

Every step ends on a **completion criterion** — the condition that tells the agent the work is
done. Two properties make it a lever:

- **Clarity** — can the agent tell done from not-done? A vague bound ("understanding reached")
  invites **premature completion**, the step ending while attention slips to *being done*. The
  visible steps still ahead supply that pull; the criterion's clarity is the resistance. Sharpen
  the bound first; only if it is irreducibly fuzzy *and* you observe the rush, split the sequence
  so the later steps are out of view. Hiding works only across a real context boundary — a
  hand-off or a subagent dispatch. An inline skill call leaves the later steps in context and
  clears nothing.
- **Demand** — how much the criterion requires. "Every modified model accounted for" forces
  thorough work where "produce a change list" does not. Demand drives the digging the agent does
  inside a step, and it is not step-bound: "every rule applied" binds a body of flat reference
  the same way, which is how an all-reference document still carries an exhaustiveness bar.

The strongest criteria are both checkable and exhaustive. This repo's mechanical gates are the
extreme form: an exit code is a completion criterion no wording can soften.

## Leading words

A **leading word** is a compact concept already in the model's pretraining that the agent thinks
with while running the document — *tight*, *red*, *seam*, *fog*, *tracer bullet*. Repeated as a
token, never as a sentence, it accumulates a distributed definition and anchors a whole region of
behavior in very few tokens by recruiting priors the model already holds. Coining your own works
if you define it clearly, but a made-up word recruits no priors: reach for an existing one first.

It anchors twice — in the body for *execution* (the agent reaches for the same behavior every
time the word appears), and in a pointer for *invocation* (when the same word lives in the
prompts, the docs, and the code, the agent links them and reaches the material more reliably).

Hunt for passages that collapse into one token:

- "fast, deterministic, low-overhead" → *tight* (a tight loop).
- "a reproduction you can believe in" → *red* — a fuzzy gate becomes a binary observable state.

**Negation** is the failure mode beside this lever. Steering by prohibition drags the forbidden
behavior into context and makes it *more* available: *don't think of an elephant*. State the
positive target instead ("write one-line comments"), so the banned behavior is never spoken. A
prohibition earns its place only as a hard guardrail that cannot be phrased positively — and even
then, pair it with the positive target.

## Pruning

- **Single source of truth.** Keep each meaning in one authoritative place, so changing the
  behavior is a one-place edit. Duplication costs maintenance and tokens, and inflates a
  meaning's rank on the ladder past its real one. (The accidental inverse of a leading word,
  which repeats a token on purpose, never the meaning.)
- **The environment is a source of truth too** — `package.json` scripts, config files, the
  directory layout, `--help` output. A document that restates it is a **cache**, earning its load
  only when the lookup is expensive. Cache what the agent cannot find by looking: the unwritten
  convention, the reason behind a choice, the gotcha no config confesses.
- **Relevance.** Does the line still bear on what the document does? A line loses relevance by
  never bearing on the task (exposition, or a branch that should be disclosed) or by going stale.
  Without pruning, the default fate is **sediment**: stale layers that settle because adding
  feels safe and removing feels risky.
- **No-ops.** An instruction the model already obeys by default pays load to say nothing. The
  test — does this change behavior versus the default? — is model-relative, not reader-relative,
  so two people disagreeing about a no-op are disagreeing about the default and settle it by
  running the document, not by debate. When a sentence fails the test, delete the whole sentence
  rather than trimming words. The test also grades leading words: a word too weak to beat the
  default (*be thorough*, when the agent is already thorough-ish) is a no-op, and the fix is a
  stronger word, not a different technique.

This is the same bar `AGENTS.md` → *Maintenance* applies to itself, and the one
`dev:harness-curate` applies when it proposes retiring an asset.
