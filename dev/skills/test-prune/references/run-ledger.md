# Run ledger — what a run records and what the next run may reuse

Reference for `test-prune` *Run ledger*. Adapted from the coverage-ledger and prior-run rules of
[cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill)
`skills/security-audit` (runs stored outside the target, per-unit source comparison, carried
records re-verified by the current run); paraphrased, not copied.

## Where it lives

`~/.test-prune/<repo-name>/run-<N>/`, outside the target, so the target tree stays clean for
Step 3. `<repo-name>` is the `origin` remote's last path segment, else the top-level directory
name. Each run gets the next unused `N`; earlier runs are never rewritten.

- `run-metadata.json` — target, `source_ref` (HEAD), sample seed, prior runs read, prior runs
  found without a ledger.
- `ledger.json` — one unit per test file the run read or measured, written by `record`.

## Unit

```json
{"test_path": "src/a.test.ts",
 "covered": ["src/a.ts"],
 "candidates": ["src/a.test.ts::rejects zero | <smell> | production change ... | bug"],
 "mutants": [{"id": "src/a.ts:12:> to >=", "outcome": "KILLED",
              "killed_by": ["src/a.test.ts::rejects zero", "src/b.test.ts::bounds"],
              "survivor": null}],
 "verdicts": [{"test": "src/a.test.ts::rejects zero", "verdict": "KEEP", "reason": "sole killer of m3"}],
 "open": ["src/a.ts:40 — not measured: outside sample"]}
```

- `covered` — the production files the unit's mutants were placed in.
- `killed_by` — every killing test as `<file>::<test>`, the Step 2 line's identity. A list cut at
  the first killer is not a kill matrix (`mutation-proof.md` → *Tools*).
- `survivor` — for SURVIVED: `gap`, `equivalent`, `cosmetic` or `bug` (Step 4); else `null`.
- `open` — what this run left unresolved for the unit: gaps, INVALID mutants, *Not measured*.

`record` stamps `blobs`: the HEAD blob of the test file, every `covered` file, and every file
named in a `killed_by` entry. A change to another killing test can make "also killed by" stale,
so that file is part of the unit's source.

## Reuse rules

`start` reports the newest prior record of each test file as one of:

| Status | Condition | This run |
|---|---|---|
| `same_source` | every recorded blob matches HEAD | carry its candidate lines and kill rows; skip re-reading and re-running them |
| `changed_source` | any blob differs, or a recorded file is gone | current work: read and measure as if new |

- A matching `source_ref` alone is not evidence: only the per-file blobs decide.
- A carried unit's `open` items are current work, not settled results — re-run its INVALID
  mutants and re-check its gaps.
- Carried rows feed Step 4 like fresh ones, but Step 4's joint re-run and Step 6 always run in
  this run. A removal never rests on a carried row alone.
- A prior run with no `ledger.json` stopped early; `start` lists it as incomplete. Its coverage
  is unknown, never empty.
- A test file no prior run recorded is new work.
