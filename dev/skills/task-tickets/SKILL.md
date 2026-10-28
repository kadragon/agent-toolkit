---
name: task-tickets
description: >-
  Break an approved `docs/design/{slug}.md` spec into vertical-slice
  `backlog.md` items, each sized for exactly one Sprint Contract, in dependency
  order. Reuses approved granularity; confirms new slicing decisions. NOT for authoring the design
  doc itself → task-spec. A single trivial task skips this — write one Sprint
  Contract directly.
version: 1.3.1
---

# To Tickets

> Inspired by mattpocock/skills (https://github.com/mattpocock/skills) — adapted for this repo's markdown-only backlog (no issue tracker, no CONTEXT.md/ADR pipeline).

Breaks a spec (or a resolved conversation) into `backlog.md` items sized for individual Sprint
Contracts, ordered so dependencies land before dependents.

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
   the same spec — delete the graduated line from `## Not yet specified` in the same edit that
   writes its ticket, so it lives only as the ticket. Never commit here: the edit rides into
   the caller's next cycle commit.
2. **Slice vertically.** Each ticket must be sized for exactly one Sprint Contract
   (`../task-next/references/cycle.md` → *Sprint Contract*) — a self-contained,
   independently mergeable unit of behavior, not a horizontal layer (e.g. not "write all the models" then "write all the
   UI"). Prefer an independently verifiable and mergeable result. File count is a review-cost
   signal, not a cap. Split when outcomes can land independently or the review surface no longer
   fits one contract; retain coupled mechanical changes when splitting would break validation.
   **Wide mechanical refactors** (one mechanical change whose blast radius breaks every call
   site at once) sequence **expand–contract**, one ticket per stage: Expand (new form beside the
   old), Migrate (call-site batches, each `*(blocked by: <n>-expand-<slug>)*` and green alone),
   Contract (delete the old form, blocked by every migrate batch). A batch that cannot stay
   green alone stays one ticket — no shared integration branch. **Renaming a skill, agent or
   command is one ticket**: rename and update every caller in one commit.

3. **Order topologically.** Determine which tickets depend on others (e.g. a schema change
   before the feature that reads it). Sort the ticket list so a dependency's ticket always
   precedes its dependents.
4. **Draft numbered ticket titles + scope, acceptance criteria, approach, and dependencies.**
   A skill-authoring source with Skill slots carries them per
   `../task-grill/references/skill-extraction.md` → *Carrying the slots*.
   Cite the approved source in each ticket. Apply `../task-next/references/cycle.md` → *Plan gate*:
   reuse approved granularity/order; ask only about new slicing decisions or changed scope before
   writing. Create `backlog.md` if this authorized ticket-writing path needs it.
5. **Write to `backlog.md`.** Give each confirmed ticket its **own** new `## <n> — <short name>`
   heading — never
   append a task-tickets-generated ticket into an existing heading that already owns other open
   items, and never put two new tickets under one shared heading. `task-next` treats a
   heading as a single candidate whose *entire* open-item set becomes one Sprint Contract, so
   sharing a heading across tickets would silently merge their scope and break the "one ticket
   = one Sprint Contract" guarantee this skill promises. Each heading gets exactly one `- [ ]`
   item — the ticket itself — carrying the `[type]` tag per `docs/conventions.md` (e.g.
   `[FEAT]`, `[FIX]`). Its source citation, acceptance criteria and approach go on indented
   plain lines under it, no bullet marker, so candidate selection folds them into the item and
   `prune-backlog` deletes them with it:
   ```
   - [ ] [FEAT] <ticket description>
     Source: docs/design/<slug>.md → <section>
     Done when: <criterion → check>
     Approach: <one line>
   ```
6. **Mark blocked items.** Any ticket that must not start before another ticket in this same
   batch (or an existing unresolved backlog item) completes gets the marker appended to its
   item line, verbatim format:
   ```
   - [ ] [FEAT] <ticket description> *(blocked by: <n>-<slug>)*
   ```
   where `<n>-<slug>` is the blocking ticket's heading words in order, lowercased and
   hyphen-joined (`## 3 — expand foo` → `3-expand-foo`); for prior work outside this batch,
   use its heading's words the same way. `prune-backlog` matches a marker against the headings
   it deletes this way. **Never write a number without its slug:** the slug is the identifying half, so a
   number-only marker can never be resolved or cleared and the item stays invisible to candidate
   selection forever. `<n>` is frozen at authoring time and is never
   renumbered as items land or headings are deleted — nothing maintains it, so a marker whose
   number no longer matches any position is normal, not stale. Resolve a marker by its slug;
   never treat a number mismatch as evidence the blocker is gone.
   **More than one blocker:** repeat the marker, one per blocker, on the same item line —
   `- [ ] [FEAT] <desc> *(blocked by: 2-expand-foo)* *(blocked by: 3-migrate-foo)*`. The item
   stays invisible to candidate selection until the **last** marker is removed, so clear them
   one at a time as each blocker lands. This is the existing syntax repeated, not a new one.
   `backlog_candidates.py` already skips a heading whose every open item carries a
   `*(deferred: ...)*` or `*(blocked by: ...)*` marker.
7. **Hand off.** Report the written tickets and their order, and tell the user to run `task-next` themselves when they are ready (`/dev:task-next` in Claude Code; the skill-picker entry in Codex) — it is user-invoked, so no skill may call it. Its Step 1 candidate-gathering picks the tickets up naturally in the order written; blocked items stay invisible to candidate selection until their `*(blocked by: ...)*` marker is removed — by the blocking ticket's own cycle at cleanup (`../task-next/references/cycle.md` → *Cleanup*), where `prune-backlog` warns on it, not by hand.

## Boundaries

- Do not write production code from this skill.
- Do not build a Wayfinder-style ticket-graph/map file or a new marker syntax — the
  `blocked by` marker on the item line is the only dependency mechanism.
- Write only within approved scope and slicing decisions; approval rules live in the shared cycle.
