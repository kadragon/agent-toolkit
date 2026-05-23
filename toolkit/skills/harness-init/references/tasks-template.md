# tasks.md Template

`tasks.md` is the **active sprint** — exactly one work item currently in
flight. It exists only between sprint start and sprint close; the rest of the
time the file is absent (that's the idle state).

The maintenance routine section C reads `status:` every session to decide whether to archive,
revert, or leave the sprint intact.

## Required Schema

The file MUST contain:

1. A top-level heading `# <Sprint Title>` — used by reconcile to match the `[>]`
   line in `backlog.md`
2. A `status:` field on its own line, lowercase, one of:
   - `active` — work in progress
   - `evaluating` — implementation done, awaiting evaluator verdict
   - `done` — sprint accepted; reconcile will archive it
   - `failed` — sprint rejected; reconcile will return it to the backlog
3. Sections `Scope`, `Acceptance Criteria`, `Evaluator Feedback` (can be empty
   initially but the headings must be present so later tooling can append)

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
