# backlog.md Template

`backlog.md` is the queue of work **not yet in flight**. The maintenance routine section C
reconciles it against `tasks.md` every session.

## Required Schema

- All items are markdown list items with a checkbox: `- [ ]`, `- [>]`, or `- [x]`
- Items group under `##` headings by theme / priority (at least one heading)
- The three checkbox states have exact semantics:

| State | Meaning | Set by |
|-------|---------|--------|
| `[ ]` | Queued — nothing active | Human |
| `[>]` | Active — promoted into the current `tasks.md` sprint | Human on sprint start |
| `[x]` | Done — kept as history or pruned | `reconcile-harness.py` on sprint `status: done` |

Exactly **one** `[>]` at a time is normal. Zero `[>]` means the repo is idle.
Multiple `[>]` usually indicates a broken reconciliation — fix before starting
new work.

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

## What NOT to put in backlog.md

- Long task descriptions (keep to one line; expand in `tasks.md` when promoted)
- Assignees, dates, estimates (if you need those, use an issue tracker instead)
- Sub-task trees (flatten or promote the sub-tree into its own sprint)

## Related

- Schema enforced by `scripts/validate-harness.sh` (init) and `sync D-1`
- State transitions handled by `scripts/reconcile-harness.py` (sync C)
- Invariants: `references/harness-invariants.md` → "Reconciliation Contract"
