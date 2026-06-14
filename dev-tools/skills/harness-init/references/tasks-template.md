# tasks.md Template

`tasks.md` is the **active sprint** — exactly one work item currently in
flight. It exists only between sprint start and sprint close; the rest of the
time the file is absent (that's the idle state).

The maintenance routine section C reads `status:` every session to decide whether to archive,
revert, or leave the sprint intact.

## Required Schema

The file MUST contain:

1. A top-level heading `# <Sprint Title>` — used by reconcile as the display name and
   fallback anchor when no `## Covers` section is present.
2. A `status:` field on its own line, lowercase, one of:
   - `active` — work in progress
   - `evaluating` — implementation done, awaiting evaluator verdict
   - `done` — sprint accepted; reconcile will archive it
   - `failed` — sprint rejected; reconcile will return it to the backlog
3. Sections `Scope`, `Acceptance Criteria`, `Evaluator Feedback` (can be empty
   initially but the headings must be present so later tooling can append)

## Optional: ## Covers (bundle sprints only)

When a sprint covers **multiple backlog items** bundled together, add a `## Covers`
section listing each bundled backlog line's exact text as a bullet:

```markdown
## Covers
- [FIX] mktemp guard in codex-review.sh
- [FIX] trap cleanup on exit in codex-review.sh
```

`reconcile-harness.py` reads this section to determine which `[>]` lines to
archive/revert in `backlog.md` on sprint close. Without `## Covers`, reconcile
matches only `[>]` lines containing the `# Sprint Title` text (single-item behaviour).
Each bullet must be the **verbatim** text of the matching backlog `[>]` line so the
case-insensitive substring match is precise.

## Minimal Template to Copy

```markdown
# {Sprint Title — must match the backlog line}

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
   │  (human promotes)
   ▼
backlog [>]  +  tasks.md (status: active)
   │
   │  (implementation)
   ▼
tasks.md (status: evaluating)
   │
   ├── pass ──► status: done  ──► reconcile archives; [>] disappears
   └── fail ──► status: failed ──► reconcile reverts; [>] → [ ]
```

All of this is automatic once `status:` is set correctly — the human only
touches `status`, never `backlog.md` directly during a sprint.

## Related

- State machine enforced by `scripts/reconcile-harness.py` (sync C)
- Schema validated by `scripts/validate-harness.sh` and `sync D-1`
- Invariants: `references/harness-invariants.md` → "Reconciliation Contract"
