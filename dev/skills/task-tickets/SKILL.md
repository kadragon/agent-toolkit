---
name: task-tickets
description: >-
  Break an approved `docs/design/{slug}.md` spec into vertical-slice
  `backlog.md` items, each sized for exactly one Sprint Contract, in dependency
  order. Confirms granularity with the user first. NOT for authoring the design
  doc itself → task-spec. A single trivial task skips this — write one Sprint
  Contract directly.
version: 1.0.7
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

Input is either an approved `docs/design/{slug}.md` (the common case, produced by `task-spec`)
or a conversation that has already resolved enough scope to
decompose directly (skip `task-spec` for smaller multi-ticket work that doesn't warrant a full
spec doc). Automates `docs/workflows.md` `plan` workflow **step 3** ("Generate `backlog.md`
items from approved spec").

## Flow

1. **Read the source.** If given a spec path, read `docs/design/{slug}.md` in full — User
   Stories and Implementation Decisions drive the slice boundaries. If given a conversation,
   use the resolved scope directly. **Never ticket `## Not yet specified`** — those lines are
   fog, not slices: no ticket can be written from a question that is not yet sharp. Leave the
   section in the spec, and say in the Step 4 draft which ticket is expected to clear it. When
   a ticket lands and its answer sharpens a foggy line, that is a fresh `task-tickets` run on
   the same spec — delete the graduated line from `## Not yet specified` in the same commit so
   it lives only as its ticket.
2. **Slice vertically.** Each ticket must be sized for exactly one Sprint Contract
   (`docs/eval-criteria.md` template) — a self-contained, independently mergeable unit of
   behavior, not a horizontal layer (e.g. not "write all the models" then "write all the
   UI"). Prefer end-to-end slices even if narrow in surface area. Concrete cap: roughly 5
   files, confined to one subsystem — a slice that needs more is two tickets, not one (this
   caps files at authoring time; `task-next`'s Step 2 "large-group guard" separately caps
   open items at *execution* time — the two are independent checks, not restatements of each
   other). A title that needs "and" to describe it is a signal of the same problem — split it
   into two tickets rather than writing one ticket that does both.
2a. **Wide mechanical refactors are the exception to vertical slicing.** A *wide refactor* is
   one mechanical change — rename a skill, move a bundled script, retype a shared field —
   whose blast radius fans across the repo, so a single edit breaks every call site at once
   and no vertical slice lands green. Do not force it into a tracer bullet; sequence it
   **expand–contract**, one ticket per stage:
   1. **Expand** — add the new form beside the old, nothing breaks, nothing migrates.
   2. **Migrate** — call sites in batches sized by blast radius (per plugin, per skill
      directory), each batch its own ticket carrying `*(blocked by: <n>-expand-<slug>)*`.
      Each batch stays green on its own because the old form still exists.
   3. **Contract** — delete the old form once no caller remains, blocked by *every* migrate
      batch.

   The Step 2 five-file cap is judged **per batch**, not across the sequence, and a purely
   mechanical batch may exceed it where every edit is the same substitution — the cap exists
   to bound review surface, and identical edits do not accumulate review surface the way
   distinct ones do. Split by subsystem anyway when a batch stops being reviewable at a
   glance. If a migrate batch cannot stay green alone, the change is not expand–contract-able
   in this repo: say so and keep it as one ticket rather than inventing a shared integration
   branch — `task-next`/`task-review` merge each ticket through its own PR to `main`, and a
   long-lived integration branch has no slot in that cycle.

   **Version-bump note:** every stage ships under the same plugin, so each stage ticket bumps
   the plugin itself (`docs/conventions.md` → *Plugin Version Bump Rules*). A rename of an
   asset invoked **by name** is a major bump, and it lands on the **contract** ticket — the
   stage that actually removes the old name — not on expand.

3. **Order topologically.** Determine which tickets depend on others (e.g. a schema change
   before the feature that reads it). Sort the ticket list so a dependency's ticket always
   precedes its dependents.
4. **Draft numbered ticket titles + one-line scope each**, and **confirm with the user**
   before writing anything: granularity (is this too coarse/fine?) and blocking order (does
   the dependency chain look right?). Do not write to `backlog.md` until the user confirms.
5. **Write to `backlog.md`.** Give each confirmed ticket its **own** new `## ` heading — never
   append a task-tickets-generated ticket into an existing heading that already owns other open
   items, and never put two new tickets under one shared heading. `task-next` treats a
   heading as a single candidate whose *entire* open-item set becomes one Sprint Contract, so
   sharing a heading across tickets would silently merge their scope and break the "one ticket
   = one Sprint Contract" guarantee this skill promises. Each heading gets exactly one `- [ ]`
   item — the ticket itself — carrying the `[type]` tag per `docs/conventions.md` (e.g.
   `[FEAT]`, `[FIX]`).
6. **Mark blocked items.** Any ticket that must not start before another ticket in this same
   batch (or an existing unresolved backlog item) completes gets the marker appended to its
   item line, verbatim format:
   ```
   - [ ] [FEAT] <ticket description> *(blocked by: <n>-<slug>)*
   ```
   where `<n>` is the blocking ticket's position number in this batch (omit it when blocking on
   prior work outside this batch — write the slug alone) and `<slug>` is its kebab-case short
   name. **Never write a number without its slug:** the slug is the identifying half, so a
   number-only marker can never be resolved or cleared and the item stays invisible to candidate
   selection forever. `<n>` is frozen at authoring time and is never
   renumbered as items land or headings are deleted — nothing maintains it, so a marker whose
   number no longer matches any position is normal, not stale. Resolve a marker by its slug;
   never treat a number mismatch as evidence the blocker is gone.
   `backlog_candidates.py` already skips a heading whose every open item carries a
   `*(deferred: ...)*` or `*(blocked by: ...)*` marker — do not invent a new
   dependency-graph engine or a separate marker syntax.
7. **Hand off.** Report the written tickets and their order, and tell the user to run `task-next` themselves when they are ready (`/task-next` in Claude Code; the skill-picker entry in Codex) — it is user-invoked, so no skill may call it. Its Step 1 candidate-gathering picks the tickets up naturally in the order written; blocked items stay invisible to candidate selection until their `*(blocked by: ...)*` marker is removed (by hand, once the blocking ticket lands).

## Boundaries

- Do not write production code from this skill.
- Do not build a ticket-graph/map file — the `blocked by` marker on the item line is the only
  dependency mechanism.
- Do not write to `backlog.md` before the user confirms granularity and order.
