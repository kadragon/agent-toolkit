# tasks.md Template

`tasks.md` holds Sprint Contract blocks and **nothing else**. It is optional: `dev:task-next`
writes it only when a `## Covers` deletion list is needed (a ≥2-item backlog group, or `--tree`),
and it is absent when idle. Persistent content — queued work, review and security findings,
follow-ups — goes to `backlog.md` (`backlog-template.md`). `task_nodes.py prune-tasks` refuses a
`tasks.md` carrying a `## Review Backlog` / `## Security Fixes` section; move it to `backlog.md`
verbatim.

## Required Schema

1. A top-level heading `# <Sprint Title>` — reconcile's display name and CHANGELOG title.
2. A `status:` line, lowercase: `open` (queued; `task-next` flips it to `active` at the plan
   gate) · `active` · `done` · `failed`. What reconcile does with each:
   `harness-invariants.md` → *Reconciliation Contract*.
3. The Sprint Contract fields: `dev:task-next` → `references/cycle.md` → *Sprint Contract*.
4. Optional `## Covers` — each covered `backlog.md` line verbatim, `- [ ] ` prefix included;
   `prune-backlog` deletes exactly those lines at cleanup and refuses on ambiguity.

```markdown
# {Sprint Title}

status: active

{Sprint Contract fields}

## Covers
- [ ] [FIX] mktemp guard in codex-review.sh
- [ ] [FIX] trap cleanup on exit in codex-review.sh
```
