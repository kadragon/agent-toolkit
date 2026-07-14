---
name: to-tickets
description: >-
  Use to break an approved `docs/design/{slug}.md` spec (or a conversation, for smaller
  multi-ticket work) into vertical-slice `backlog.md` items, each sized for exactly one
  Sprint Contract, written in dependency (topological) order. Confirms ticket
  granularity/blocking order with the user before writing. Automates `docs/workflows.md`
  `plan` workflow step 3. Trigger: "break this into tickets", "write backlog items for this",
  "티켓으로 쪼개줘", "백로그 항목 만들어줘". NOT for a single trivial task — write one Sprint
  Contract directly instead.
version: 1.0.0
---

# To Tickets

> Inspired by mattpocock/skills (https://github.com/mattpocock/skills) — adapted for this repo's markdown-only backlog (no issue tracker, no CONTEXT.md/ADR pipeline).

Breaks a spec (or a resolved conversation) into `backlog.md` items sized for individual Sprint
Contracts, ordered so dependencies land before dependents. Deliberately does **not** build a
Wayfinder-style ticket-graph/map system — this repo's backlog is a single markdown file, not
an issue tracker, and a full dependency-graph engine would be over-engineering for that scale.
The only dependency mechanism is the lightweight `*(blocked by: <n>-<slug>)*` marker, which
reuses and generalizes the `*(deferred: ...)*` skip pattern already present in
`backlog_candidates.py`.

## When to use

Input is either an approved `docs/design/{slug}.md` (the common case, produced by
`Skill(dev-tools:to-spec)`) or a conversation that has already resolved enough scope to
decompose directly (skip `to-spec` for smaller multi-ticket work that doesn't warrant a full
spec doc). Automates `docs/workflows.md` `plan` workflow **step 3** ("Generate `backlog.md`
items from approved spec").

## Flow

1. **Read the source.** If given a spec path, read `docs/design/{slug}.md` in full — User
   Stories and Implementation Decisions drive the slice boundaries. If given a conversation,
   use the resolved scope directly.
2. **Slice vertically.** Each ticket must be sized for exactly one Sprint Contract
   (`docs/eval-criteria.md` template) — a self-contained, independently mergeable unit of
   behavior, not a horizontal layer (e.g. not "write all the models" then "write all the
   UI"). Prefer end-to-end slices even if narrow in surface area.
3. **Order topologically.** Determine which tickets depend on others (e.g. a schema change
   before the feature that reads it). Sort the ticket list so a dependency's ticket always
   precedes its dependents.
4. **Draft numbered ticket titles + one-line scope each**, and **confirm with the user**
   before writing anything: granularity (is this too coarse/fine?) and blocking order (does
   the dependency chain look right?). Do not write to `backlog.md` until the user confirms.
5. **Write to `backlog.md`.** Append each confirmed ticket as a `- [ ]` item under the
   appropriate heading (existing domain heading if one fits, otherwise a new `## ` group).
   Use the item text to carry the `[type]` tag per `docs/conventions.md` (e.g. `[FEAT]`,
   `[FIX]`).
6. **Mark blocked items.** Any ticket that must not start before another ticket in this same
   batch (or an existing unresolved backlog item) completes gets the marker appended to its
   item line, verbatim format:
   ```
   - [ ] [FEAT] <ticket description> *(blocked by: <n>-<slug>)*
   ```
   where `<n>` is the blocking ticket's position number in this batch (or an existing
   reference number/slug if blocking on prior work) and `<slug>` is its kebab-case short
   name. `backlog_candidates.py` already skips a heading whose every open item carries a
   `*(deferred: ...)*` or `*(blocked by: ...)*` marker — do not invent a new
   dependency-graph engine or a separate marker syntax.
7. **Hand off.** Report the written tickets and their order. The next `Skill(dev-tools:next-tasks)` run (Step 1 candidate-gathering) picks them up naturally in the order written; blocked items stay invisible to candidate selection until their `*(blocked by: ...)*` marker is removed (by hand, once the blocking ticket lands).

## Boundaries

- Do not write production code from this skill.
- Do not build a ticket-graph/map file — the `blocked by` marker on the item line is the only
  dependency mechanism.
- Do not write to `backlog.md` before the user confirms granularity and order.
