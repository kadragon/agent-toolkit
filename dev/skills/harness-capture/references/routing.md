# Routing — siblings, cross-cutting lessons, and deferral

Load this when a lesson could belong to more than one asset, or when a routing decision is
tempted toward "later". The always-loaded `SKILL.md` carries the short form of each rule;
everything here is the reasoning.

**Attribution.** Checking a target's siblings before routing a lesson to one of them is adapted
from **Task Observer ("One Skill to Rule Them All") by Eoghan Henn, rebelytics.com**,
https://github.com/rebelytics/one-skill-to-rule-them-all, licensed **CC BY 4.0**
(https://creativecommons.org/licenses/by/4.0/).

*Changes made in this adaptation:* the persistent cross-session observation log, its numbering
and archival protocol, the weekly review, the skill-authoring and staging rules, the
handoff-doc mode, and the in-session capture log are **not** carried over — this repo's
cross-session mining lives in `dev:harness-curate` and its skill authoring in `skill-creator`.
No text is copied verbatim.

## Siblings: check the family before routing to one member

An insight found while using one asset usually applies to its siblings, and nothing in the
routing table asks. This repo has real families: the `task-*` cycle skills, the `harness-*`
skills, the `scripts/ci/check_*.py` checkers, the hooks under `dev/hooks/`. Before routing a
note to one member, resolve it against the family and either widen the delta or state in one
line why it does not apply.

Fast test: **could this sentence survive having the asset's name removed?** If yes it belongs to
every sibling. A rule that declares itself generic inside one artefact ("this applies to any
file-writing script, not just X") is the cheapest possible propagation signal — treat that
phrasing as an automatic multi-asset flag.

A lesson that applies to *every* asset of a kind is not a sibling case at all; it is
cross-cutting, and it goes to the owning cross-cutting doc (`docs/writing-for-agents.md` for how
agent-facing documents are written, `docs/conventions.md` for shell and commit rules), never
copied into each skill.

## Deferral is a decision and needs the same justification as acting

"Let's wait until this has seen a few days of real use" reads as diligence, which is why it goes
unchallenged. Before writing any "later" into a routing decision, name two things: **which
specific observation would change the decision, and when it could realistically arrive.** If you
cannot name one, the evidence is either already conclusive or more of it changes nothing — act
now. A criterion you can name must also be able to occur: ask who would have to act for it to
fire, and whether they have reason to do the opposite. A deferral whose criterion cannot fire is
a silent drop wearing a precise phrasing.

Deferring to `backlog.md` is a legitimate route for heavy work — a new skill, a multi-file
rewrite — and it is not this pattern, because the queue is a place a later session actually
reads.
