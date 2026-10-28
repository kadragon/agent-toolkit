# backlog.md Template

`backlog.md` is the **only** persistent queue: work not yet in flight, plus every finding that
outlives the cycle that produced it — review findings, security findings, deferred follow-ups.
Who writes which transition: `harness-invariants.md` → *Reconciliation Contract*.

## Required Schema

- All items are markdown list items with a checkbox: `- [ ]`, `- [>]`, or `- [x]` — except
  under `## Rejected — do not re-file`, whose entries are plain bullets (see that section)
- Items group under `##` headings by theme / priority (at least one heading)
- The three checkbox states have exact semantics:

| State | Meaning |
|-------|---------|
| `[ ]` | Queued. The cycle leaves selected items `[ ]` and deletes the line at cleanup; the `CHANGELOG.md` entry is the closure record |
| `[>]` | Legacy active marker — the current cycle never writes it; reconcile reverts a leftover to `[ ]` |
| `[x]` | Legacy done marker — never written; delete one by hand once `CHANGELOG.md` or git history records the closure |

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

## Rejected — do not re-file

When the user discards a queued item, move it here instead of deleting it. A deleted item leaves
no trace, so the next review or reference scan proposes it again.

```markdown
## Rejected — do not re-file

- **<item, one phrase>** — <why it was rejected>. Re-file only with <the evidence that would change the call>.
```

- Plain bullets, never `- [ ]`: an entry here is a decision, not a `task-next` candidate.
- The re-file bar names a concrete observation (a recorded failure, a reproduction), not
  "if it becomes important".
- Reviews and reference scans check this section before filing a new item.

Pattern adapted from mattpocock/skills@5beb35b `SCOPE.md` + `.out-of-scope/`.

## What NOT to put in backlog.md

- Long task descriptions (keep to one line; expand in `tasks.md` when promoted)
- Assignees, dates, estimates (if you need those, use an issue tracker instead)
- Sub-task trees (flatten or promote the sub-tree into its own sprint)
