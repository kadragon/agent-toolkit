# tasks.md Template

`tasks.md` holds Sprint Contract blocks and **nothing else**. It is optional: `dev:task-next`
writes it only when a `## Covers` list is needed (a ≥2-item backlog group, `--tree`, or the
issues backend), and it is absent when idle. Persistent content — queued work, review and security findings,
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
   On the issues backend (GitHub issues as the queue) it is always written and holds refs
   instead: one `- <ref> <title>` line per covered issue, ref first — no verbatim line and no
   `prune-backlog`. The refs claim the issues for other runs and become the review cycle's
   `Closes #N` lines (`dev:task-next` → `references/cycle.md` → *Covered refs*).

```markdown
# {Sprint Title}

status: active

{Sprint Contract fields}

## Covers
- [ ] [FIX] mktemp guard in codex-review.sh
- [ ] [FIX] trap cleanup on exit in codex-review.sh
```

Issues backend:

```markdown
## Covers
- #41 [FIX] mktemp guard in codex-review.sh
- #42 [FIX] trap cleanup on exit in codex-review.sh
- #40 Harden codex-review.sh
```
