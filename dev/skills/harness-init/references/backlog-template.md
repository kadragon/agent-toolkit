# backlog.md Template

`backlog.md` is the **only** persistent queue: work not yet in flight, plus every finding that
outlives the cycle that produced it — review findings, security findings, deferred follow-ups. The
maintenance routine section C reports its state every session; line transitions are written by
`task_nodes.py prune-backlog` at `task-next` pre-merge cleanup, not by reconcile.

Nothing persistent belongs in `tasks.md`; that file is the current Sprint Contract and is deleted
whole at sprint close (`references/tasks-template.md` → *Invariant*).

## Required Schema

- All items are markdown list items with a checkbox: `- [ ]`, `- [>]`, or `- [x]`
- Items group under `##` headings by theme / priority (at least one heading)
- The three checkbox states have exact semantics:

| State | Meaning | Set by |
|-------|---------|--------|
| `[ ]` | Queued — nothing active | Human |
| `[>]` | Active — promoted into the current `tasks.md` sprint | Human on sprint start (no automated writer — `task-next` leaves items `[ ]` and deletes them at pre-merge cleanup). `reconcile-harness.py` reverts a leftover `[>]` back to `[ ]` — on `status: failed`, and on any orphan sweep (`tasks.md` absent) — it never deletes the line |
| `[x]` | Done — kept as history or pruned | Human (no automated writer — `reconcile-harness.py` only closes the `tasks.md` sprint block; backlog line deletion is owned by `task_nodes.py prune-backlog`) |

Exactly **one** `[>]` at a time is normal for single-item sprints. Zero `[>]`
means the repo is idle. Multiple `[>]` is valid when `tasks.md` has a `## Covers`
section listing each covered item — that is a **bundle sprint**. Without a
`## Covers` section, multiple `[>]` indicates broken reconciliation — fix before
starting new work.

## Minimal Template to Copy

```markdown
# Backlog

## Now

- [ ] {task that will ship next}

## Next

- [ ] {task after that}
- [ ] {another candidate}

## Someday

- [ ] {speculative idea — may never ship}
```

Empty sections are fine at init time — `reconcile-harness.py` prunes headings
that end up empty.

## Findings Sections (appended by tooling, not at init)

Skills that produce persistent findings append their own `##` section. Two are shipped:

```markdown
## Review Backlog

### PR #101 — <PR title> (2026-08-05)

- [ ] [debt] <suggestion summary> (source: <skill-id>) — <file:line>

## Security Fixes

- [ ] [P1] <alert summary> — <file:line>
```

Rules for any such section:

- Items use the same `- [ ]` syntax as the rest of the file, so `task-next` picks them up as
  ordinary candidate groups — a findings heading is not a special case to the reader.
- Append; never overwrite a sibling group. A rescan replaces only its **own** section.
- Tags: `[debt]` code quality/refactor · `[doc]` documentation gaps · `[constraint]` missing tests
  or architectural rules · `[harness]` tooling/CI.

## What NOT to put in backlog.md

- Long task descriptions (keep to one line; expand in `tasks.md` when promoted)
- Assignees, dates, estimates (if you need those, use an issue tracker instead)
- Sub-task trees (flatten or promote the sub-tree into its own sprint)

## Related

- Schema enforced by `scripts/validate-harness.sh` (init) and `sync D-1`
- State transitions handled by `task_nodes.py prune-backlog` (`task-next` pre-merge cleanup);
  `scripts/reconcile-harness.py` (sync C) reverts `[>]` → `[ ]` on `status: failed` and on any
  orphan sweep (`tasks.md` absent) — it never removes a backlog line; line deletion is
  `prune-backlog`'s exclusive job
- Invariants: `references/harness-invariants.md` → "Reconciliation Contract"
