---
name: repo-architecture
description: >-
  Scan this repo for deepening opportunities — shallow modules whose complexity should
  collapse behind a smaller interface — and queue the ones you pick as backlog items.
disable-model-invocation: true
version: 1.0.0
---

# Repo Architecture

> Adapted from [mattpocock/skills](https://github.com/mattpocock/skills)
> `skills/engineering/improve-codebase-architecture` and its `codebase-design` vocabulary.
> Deviations: the candidates are presented as markdown in the conversation rather than as a
> Tailwind/Mermaid HTML report (this repo ships nothing that renders one), and accepted
> candidates land as `backlog.md` items instead of being explored inline — the queue is where
> this repo's work already lives.

Surface architectural friction and propose **deepening opportunities**: changes that turn
shallow modules into deep ones. The aim is testability and agent-navigability, not tidiness.

Read `references/deep-module-vocabulary.md` before scanning, and use its terms exactly —
**module**, **interface**, **depth**, **seam**, **adapter**, **leverage**, **locality**, the
**deletion test**. A proposal written in generic nouns ("refactor the service layer") cannot be
compared against another one.

## Step 1 — Scope, then scan

**Scope before you scan.** Deepening pays off in future changes to the module, so weight the
parts of the codebase that keep changing.

- If the user named a direction — a module, a subsystem, a pain point — take it and skip the
  inference below.
- Otherwise derive the hot spots from history:

```sh
HOT=$(git log -n 200 --name-only --pretty=format: | grep -v '^$' | sort | uniq -c | sort -rn | head -20)
[ -n "$HOT" ] || echo "shallow history — scan the tree by size instead"
printf '%s\n' "$HOT"
```

If the changes are scattered with no clear hot spot, widen the net.

Read this repo's own map first — `AGENTS.md` and the `docs/` index rows it points at — so a
candidate does not contradict a decision already recorded there.

Then walk the code looking for friction. Do not follow a rigid checklist; note where you feel it:

- Understanding one concept requires bouncing between many small modules.
- A module's interface is nearly as complex as its implementation.
- Pure functions were extracted for testability, but the real bugs live in how they are called
  — no **locality**.
- Tightly-coupled modules leak across their seams.
- A part of the codebase is untested, or hard to test through its current interface.

Apply the **deletion test** to anything that looks shallow: would deleting it concentrate
complexity, or merely move it? "Concentrates" is the signal.

## Step 2 — Present the candidates

Write the candidate list into the conversation as markdown — one block per candidate, in
recommendation order. Nothing is written to disk in this step.

```markdown
### <candidate name in the repo's own vocabulary>

**Strength:** Strong | Worth exploring | Speculative
**Files:** <modules involved>
**Friction:** <what the current shape costs, concretely>
**Deepening:** <what changes — which interface shrinks, where the seam moves>
**Payoff:** <in terms of leverage, locality, and which tests become possible>
**Deletion test:** <concentrates | merely moves — and why>
```

Close with a **Top recommendation** line: which one you would take first, and why.

Do not design interfaces yet. Ask the user which candidate to explore.

## Step 3 — Grill the chosen candidate

Once the user picks one, call the Skill tool with "dev:task-grill" to resolve what is still
open: the constraints, the dependencies, the shape of the deepened module, what sits behind the
seam, which tests survive the move.

Two things to settle before queuing, because they decide the ticket's size:

- **Does the seam already vary?** One adapter is a hypothetical seam. If nothing varies across
  it yet, the honest candidate is smaller than it looked.
- **Is any existing behavior changing?** A pure restructure is `[REFACTOR]`; anything that
  changes behavior needs its own test and a different tag.

## Step 4 — Queue it

Append the accepted candidate to `backlog.md` as a normal item — scope, the acceptance
criterion in one line, and the vocabulary term for what gets deepened. Do **not** implement it
here; this skill produces queued work, not commits.

**No `backlog.md` in this repo:** do not create one. The queue is scaffolding, not a side
effect of this scan — report the candidate in the conversation and send the user to
`dev:harness-init`, which owns the file.

If the candidate is large enough to span several sessions, call the Skill tool twice, for
"dev:task-spec" and "dev:task-tickets", instead of writing one oversized item by hand.

When a candidate is **rejected for a load-bearing reason** — a constraint that would make a
future scan re-propose it — record that reason where the next reader will meet it: a cut
section in `backlog.md` if the repo keeps one, otherwise a note in the owning `docs/` page.
Skip ephemeral reasons ("not worth it right now") and self-evident ones.

Then tell the user to run `task-next` themselves when they want the queued item built
(`/task-next` in Claude Code; the skill-picker entry in Codex) — it is user-invoked, so no
skill may call it.
