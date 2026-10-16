# Run ledger — what a run records and what the next run may reuse

Reference for `test-prune` *Run ledger*. Adapted from the coverage-ledger and prior-run rules of
[cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill)
`skills/security-audit` (runs stored outside the target, per-unit source comparison, carried
records re-verified by the current run); paraphrased, not copied.

## Where it lives

`~/.test-prune/<repo-name>/run-<N>/`, outside the target, so the target tree stays clean for
Step 3. `<repo-name>` is the `origin` remote's last path segment, else the top-level directory
name. Each run gets the next unused `N`; earlier runs are never rewritten.

- `run-metadata.json` — target, `source_ref` (HEAD at `start`), sample seed (written by
  `record --seed`), prior runs read, prior runs whose ledger is missing or unreadable.
- `ledger.json` — one unit per test file the run read, measured or carried, written by `record`.
  `start` refuses tracked changes; untracked files do not block it.

## Unit

```json
{"test_path": "src/a.test.ts",
 "covered": ["src/a.ts"],
 "depends": ["vitest.config.ts", "test/setup.ts", "test/fixtures/users.ts"],
 "candidates": ["src/a.test.ts::rejects zero | <smell> | production change ... | bug"],
 "mutants": [{"id": "src/a.ts:12:> to >=", "outcome": "KILLED",
              "killed_by": ["src/a.test.ts::rejects zero", "src/b.test.ts::bounds"],
              "survivor": null}],
 "verdicts": [{"test": "src/a.test.ts::rejects zero", "verdict": "KEEP", "reason": "sole killer of m3"}],
 "open": ["src/a.ts:40 — not measured: outside sample"]}
```

Paths are repo-relative, as `git ls-tree` prints them (`src/a.ts`, not `./src/a.ts`).

- `covered` — the production files the unit's mutants were placed in.
- `depends` — files outside the test and `covered` that can change its kill outcomes: runner
  config, setup files, shared fixtures and mocks it imports (`conftest.py` up its path).
  Leave one out and a change there is invisible to the reuse check.
- `killed_by` — every killing test as `<file>::<test>`, the Step 2 line's identity. A list cut at
  the first killer is not a kill matrix (`mutation-proof.md` → *Tools*).
- `survivor` — for SURVIVED: `gap`, `equivalent`, `cosmetic` or `bug` (Step 4); else `null`.
- `open` — what this run left unresolved for the unit: gaps, INVALID mutants, *Not measured*.

`record` stamps `blobs` at the run's `source_ref` — the commit actually measured, even if HEAD
moved since — for the test file and every `covered`, `depends` and `killed_by` file. A change to
another killing test can make "also killed by" stale, so that file is part of the unit's source.
A path that commit does not have is stored as `null` and never matches. A carried unit keeps
`carried_from`: the run that measured it.

## Reuse rules

`start` reports the newest prior record of each test file as one of:

| Status | Condition | This run |
|---|---|---|
| `same_source` | every recorded blob matches HEAD | carry its candidate lines and kill rows; skip re-reading and re-running them |
| `changed_source` | any blob differs, or a recorded file is missing now or was then | current work: read and measure as if new |
| `removed` | the test file is gone from HEAD | nothing to read; drop it from the run |

- A matching `source_ref` alone is not evidence: only the per-file blobs decide.
- A carried unit's `open` items are current work, not settled results — re-run its INVALID
  mutants and re-check its gaps.
- A test file added since the carried unit was measured can kill its mutants without changing
  any recorded blob. When Step 1 shows test files no prior run recorded, re-run every carried
  KILLED mutant whose verdict rests on `sole killer: yes` before keeping on that ground.
- Carried rows feed Step 4 like fresh ones, but Step 4's joint re-run and Step 6 always run in
  this run. A removal never rests on a carried row alone.
- A prior run whose `ledger.json` is missing (it stopped early) or unreadable is listed as
  incomplete. Its coverage is unknown, never empty.
- A test file no prior run recorded is new work.
