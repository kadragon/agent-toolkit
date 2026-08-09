# tasks.md Template

`tasks.md` is the **active sprint** — exactly one work item currently in
flight. It exists only between sprint start and sprint close; the rest of the
time the file is absent (that's the idle state).

The maintenance routine section C reads `status:` every session to decide whether to close the
sprint block (done/failed) or leave it intact (active/evaluating).

## Invariant: nothing persistent lives here

`tasks.md` holds the Sprint Contract and **nothing else**. The file is removed whole at sprint
close, so any content that must outlive the sprint would be destroyed by that removal.

| Content | File |
|---|---|
| Sprint Contract for the sprint in flight | `tasks.md` — deleted at close |
| Queued work, review findings, security findings, follow-ups | `backlog.md` — persistent |

Do **not** add `## Review Backlog`, `## Security Fixes`, or any other findings section to
`tasks.md`. Those go to `backlog.md` (see `references/backlog-template.md`). This is enforced:
`task_nodes.py prune-tasks` refuses to run against a `tasks.md` carrying a persistent findings
section, and tells you to move it.

*Migrating an older repo:* move the whole `## Review Backlog` / `## Security Fixes` section into
`backlog.md` verbatim — the item syntax is identical, and `backlog.md` already groups items under
`##`/`###` headings.

## Required Schema

The file MUST contain:

1. A top-level heading `# <Sprint Title>` — used by reconcile as the display name (in
   print messages and the CHANGELOG entry).
2. A `status:` field on its own line, lowercase, one of:
   - `active` — work in progress
   - `evaluating` — implementation done, awaiting evaluator verdict
   - `done` — sprint accepted; reconcile closes the `tasks.md` block and appends a CHANGELOG entry
   - `failed` — sprint rejected; reconcile closes the `tasks.md` block, backlog items are reverted to `[ ]`
3. Sections `Scope`, `Acceptance Criteria`, `Evaluator Feedback` (can be empty
   initially but the headings must be present so later tooling can append)

## Optional: ## Covers (bundle sprints only)

When a sprint covers **multiple backlog items** bundled together, add a `## Covers`
section listing each bundled backlog line's exact text as a bullet:

```markdown
## Covers
- [ ] [FIX] mktemp guard in codex-review.sh
- [ ] [FIX] trap cleanup on exit in codex-review.sh
```

`reconcile-harness.py` does not read this section — it only closes the `tasks.md`
sprint block. `task_nodes.py prune-backlog` is the consumer: `task-next` feeds it
the bundled `- [ ]` line texts from `## Covers` and it deletes them from `backlog.md`
at pre-merge cleanup. That match is **verbatim**, not a case-insensitive substring,
and it refuses on ambiguity — so each bullet here must be the exact text of the
matching backlog line, full `- [ ] ` prefix included.

## Minimal Template to Copy

```markdown
# {Sprint Title}

status: active

## Scope

- {what IS in scope}
- {what is explicitly OUT of scope}

## Acceptance Criteria

- [ ] {concrete, testable criterion 1}
- [ ] {concrete, testable criterion 2}
- [ ] {concrete, testable criterion 3}

## Evaluator Feedback

_filled in by the evaluator after implementation_
```

## Lifecycle

```
backlog [ ]
   │  (task-next selects; backlog line stays [ ])
   ▼
tasks.md (status: active)
   │
   │  (implementation)
   ▼
tasks.md (status: evaluating)
   │
   ├── pass ──► status: done  ──► reconcile closes tasks.md, appends CHANGELOG entry;
   │                              task-next pre-merge cleanup deletes the covered
   │                              backlog line(s) via task_nodes.py prune-backlog
   └── fail ──► status: failed ──► reconcile closes tasks.md, reverts [>] backlog line(s) to [ ]
```

`status:` drives reconcile's handling of `tasks.md` itself; deleting the covered
backlog line(s) on success is a separate step owned by `task-next`'s pre-merge
cleanup, not by reconcile. On failure reconcile reverts the `[>]` marker on the
covered backlog line(s) back to `[ ]` itself — it never deletes a line.

## Related

- State machine enforced by `scripts/reconcile-harness.py` (sync C)
- Schema validated by `scripts/validate-harness.sh` and `sync D-1`
- Invariants: `references/harness-invariants.md` → "Reconciliation Contract"
