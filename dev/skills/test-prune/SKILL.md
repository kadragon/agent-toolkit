---
name: test-prune
description: >-
  Prune low-value tests — tautological, mock-only, over-specified, duplicated,
  or chasing unreachable edge cases — and prove each removal with mutation
  evidence: the suite's kill set must not shrink. Use for "prune the tests",
  "test suite bloat", "meaningless tests", "too many edge-case tests",
  "테스트 정리", "의미 없는 테스트 삭제". Reports surviving mutants as gaps
  instead of writing new tests. NOT for a failing test or unknown bug →
  task-debug; NOT for reviewing a diff → code-review.
version: 1.1.0
---

# Test Prune

> Synthesized from: [computerphilosopher/agent-skills](https://github.com/computerphilosopher/agent-skills)
> `skills/false-green-detector` (break-it probe on a temporary copy; a crash is not a detection),
> [obra/superpowers](https://github.com/obra/superpowers) `skills/test-driven-development/writing-good-tests.md`
> (smell catalog; "which production change should fail this test"), Kent Beck's
> [Test Desiderata](https://testdesiderata.com/) (behavioral vs structure-sensitive), the Stryker,
> PIT and mutmut docs (equivalent mutants, timeouts, caches), and a user-supplied mutation-sampling
> methodology (count by checked items, sample ~4% per file, calibrate the tool, green baseline),
> and [cloudflare/security-audit-skill](https://github.com/cloudflare/security-audit-skill)
> `skills/security-audit` (run ledger outside the target, per-unit source comparison with prior runs).
> Rules are paraphrased; no upstream text is copied.

A test earns its place by **failing when production code breaks**. Test count is not value, and
reading is not evidence: reading yields *candidates*, only a **kill set** measurement yields a
*verdict*. The kill set is the set of mutants the suite detects, excluding decision and
unreachable mutants (Step 4); every removal in this skill must leave it unchanged.

## Ground rules

- **Clean tree, then copy.** Step 3 needs a clean working tree — the copy is made from `HEAD`,
  and measuring `HEAD` while Step 5 edits uncommitted code mixes two codebases. Dirty tree → ask
  the user to commit or stash first. Every mutation run happens in a disposable `git worktree`
  under the session scratchpad directory; the original tree receives only the Step 5 edits.
- **Delete, merge, or keep — never weaken.** A kept test keeps every assertion it had.
- **Audit-only requests stop after Step 4** with the report. Edits need a request to clean up.
- **Gaps are reported, not filled.** Writing new tests is a separate task.
- **Kept beats deleted when evidence is missing.** No recorded verdict, no removal.
- **Edit, never commit.** The skill leaves its edits uncommitted for the user or the calling
  workflow to review.

## Run ledger

Each run records what it read and measured, so the next run does not redo it. Before Step 1:

```sh
LEDGER="<skill dir>/scripts/prune_ledger.py"
START=$(python3 "$LEDGER" start --target "<repo root>") || exit 1   # refuses tracked changes
```

`$START` holds the new `run_dir` and every prior unit (one per test file) as `same_source` —
its test file, covered, dependency and killing tests' files all have the same blob at HEAD —
`changed_source`, or `removed`. Read `references/run-ledger.md` for the unit shape and reuse rules. In short:
a `same_source` unit's candidate lines and kill rows are carried, so Step 2 does not re-read it
and Step 3 does not re-run its mutants; its `open` items, every `changed_source` unit and every
unrecorded test file are current work. Step 4's joint re-run and Step 6 always run fresh.

Before the report — also when an audit-only run stops after Step 4 — write every unit this run
read, measured or carried, with the Step 3 seed:
`python3 "$LEDGER" record --run-dir <run_dir> --seed <seed> < <scratch>/units.json`.

## Step 1 — Map where the count comes from

Export per-file test counts in machine-readable form and sort descending:

| Runner | Command |
|---|---|
| vitest | `vitest run --reporter=json --outputFile=<scratch>/counts.json` |
| jest | `jest --json --outputFile=<scratch>/counts.json` |
| pytest | `pytest --collect-only -q` (group the node ids by file) |
| go | `go test -json ./...` — count `pass`/`fail` events per `Test`, including `t.Run` subtests (`-list` shows top-level functions only) |

Look for runner flags in the repo's own config before assuming these. For every parametrized
block (`it.each`, `test.each`, `@pytest.mark.parametrize`, table tests) record **generated cases**
and **distinct input classes** — a key × locale matrix that generates 400 cases may check two
behaviors. Data-driven volume is counted by what it checks, not by what it generates.

**Done:** a table of the heaviest files with raw count, and for each parametrized block, cases vs
distinct input classes.

## Step 2 — Read and flag candidates

Run the grep seeds in `references/smells.md` → *Grep seeds*, then **read every hit in full**,
except hits in a carried `same_source` unit — take its recorded lines instead. Report only tests
you read or carried. For each candidate, write one line:

```
<file>::<test> | <smell> | production change that should fail it: <change> | bug or decision: <bug|decision|none>
```

"Decision" means only an intentional edit (a constant, message wording, private structure) can
fail it; "none" means no realistic change fails it. Then apply *Keep rules* 2–6 in the same
reference: a test matching one leaves the list now, with the rule named. Rule 1 (sole killer)
needs the kill matrix and is decided in Step 4.

On a large suite, readers may split by test directory; each returns lines in this format and
nothing it did not read.

**Done:** every grep hit read, every candidate in the line format, nothing deleted.

## Step 3 — Measure the kill set

Read `references/mutation-proof.md` before the first run — it holds tool setup, sampling, and the
traps that produced false numbers in practice. In order:

1. **Calibrate.** In the copy, inject one mutant that must be killed and one that must survive
   (an equivalent mutant on covered code, or one in dead code — where the tool then reports its
   no-coverage status, e.g. Stryker `NoCoverage`, PIT `NO_COVERAGE`, count that as the survive
   outcome). Proceed only if the tool tells the two apart without a config change.
2. **Generate and sample.** Use the repo's mutation tool (Stryker, mutmut, PIT, cargo-mutants…).
   On a large suite, sample per file (about 4%, minimum 3, fixed random seed recorded). Add, for
   every candidate, at least 3 mutants in the code that candidate claims to cover.
3. **Run each mutant** against the related tests only, with a **green baseline** confirmed first:

   | Outcome | Meaning |
   |---|---|
   | KILLED | an assertion failed |
   | SURVIVED | all related tests passed |
   | INVALID | compile error, import error, crash before any assertion, or unreviewed timeout — excluded |

   A timeout is reviewed as KILLED only when the test asserts that the code does not block or
   hang; any other timeout stays INVALID.

4. **Record the kill matrix** — each mutant → the tests that killed it. Use the tool's per-test
   output only when it lists every killing test, not just the first; otherwise rerun with the
   candidate removed (leave-one-out).

**No mutation tool available:** write the candidate's mutants by hand — wrong constant or
boundary, flipped branch, dropped side effect, empty/default return, removed validation, an added
condition on an input the test varies — apply each in the copy, and run the candidate alone, then
the suite without it. Same table, same matrix.

**Candidates that kill the same mutants** look like duplicates until a mutant branches on the
input they differ in. Run that mutant before calling either one redundant.

Carried units skip 2–4 for their recorded mutants, which join the matrix as recorded; re-run
their INVALID ones. Calibration (1) runs every run.

**Done:** every candidate has a verdict line naming the mutants it kills and, for each, either
the kept tests that also kill it (per-test data) or `sole killer: yes/no` (leave-one-out).

## Step 4 — Classify

For each candidate T, let K(T) = the mutants T kills, **minus** two kinds that do not count as
bugs caught:

- **Decision mutants** — the mutation changes only an intentional choice the spec does not fix
  (exact message wording, a tunable constant, private structure). A change-detector test kills
  these and nothing else.
- **Unreachable mutants** — the mutation sits in a branch an upstream guard makes unreachable,
  cited by file and line (`references/smells.md` → *Unreachable inputs*). Report the dead branch
  itself under *Gaps* as removable code.

Apply the first matching row:

| Verdict | Condition | Action |
|---|---|---|
| **KEEP** | T is the **sole killer** of any mutant in K(T), or *Keep rules* 2–6 apply | leave T; note why; if K(T) is empty, log its behavior under *Gaps* |
| **MERGE** | T and siblings differ only in input values of one class, and no collapsed case is a sole killer | collapse to one case per distinct input class |
| **DELETE + GAP** | T killed no mutant at all (a false green), and its smell is not *Text grep* or *Framework test* | remove T; log the behavior its title claims as a gap |
| **DELETE** | K(T) is empty but T is a text-grep or framework test, or every mutant it killed was a decision or unreachable mutant; or K(T) is non-empty and every mutant in it is also killed by a kept test | remove T; if a mutant of the guard its title names survived, log that guard under *Gaps* |

Decide removals **as a set**, not one at a time: two tests can each look redundant because the
other exists. Let U = the union of K(T) over every DELETE and every collapsed MERGE case. Re-run
U with the whole set removed. For each mutant that turns SURVIVED, return at least one removed
test that killed it to KEEP, then re-run U again; repeat until no mutant in U survives.

Classify every SURVIVED mutant from Step 3:

| Survivor | Handling |
|---|---|
| Real gap | goes to the report's *Gaps* list with file, line and mutation |
| Equivalent (behavior unchanged) | record the reason; no action |
| Cosmetic (color, style, icon shape) | out of scope; count only |
| Exposes a production bug | report under *Production bugs*; never pin it with a test |

**Done:** every candidate has a verdict, every survivor a class, and the joint re-run shows no
mutant lost.

## Step 5 — Apply

Edit the original tree: delete DELETE verdicts, collapse MERGE groups. A merged test keeps every
distinct input class and a title that says what it checks. Kept tests stay byte-identical except
for shared fixtures a deletion orphaned — remove one only when nothing references it by import
or by name (pytest fixtures are injected by parameter name, with no import). Delete a test file
left with no tests; some runners fail on an empty suite.

**Done:** every DELETE and MERGE verdict applied, no orphaned fixture left, the suite green once.

## Step 6 — Verify independently

1. **Re-inject each mutant in U, one at a time,** in a fresh worktree carrying the Step 5 edits
   (`git diff HEAD --binary | git -C <new-copy> apply`) — never in the original tree. Every one
   must be KILLED.
2. **Run the full suite at least 3 times** (5 when tests use real timers, concurrency, or
   network) — all green.
3. **Before/after numbers** — test count, distinct checks, runtime.
4. When another agent did Steps 4–5, a reviewer that took no part checks: no assertion weakened,
   every title matches its body, no new flakiness from real timers.

**Done:** every mutant in U re-killed, every repeated full run green, numbers recorded.

## Report

```
Removed: <n> tests (<m> merged into <k>) — sampled kill set (decision/unreachable mutants
excluded) unchanged: <x>/<x> mutants in U
re-killed (sample: <n> of <total> mutants, seed <s>; unsampled mutants were not checked)
Runtime: <before> → <after>; count: <before> → <after>
| Test | Verdict | Smell | Mutants it killed | Also killed by (or sole killer: no) | Carried from (run-<N> or —) |
Gaps: <file:line — mutation — behavior unprotected>
Production bugs: <file:line — what the mutant revealed>
Equivalent mutants: <id — reason>
Not measured: <files outside the sample, INVALID count, tool limits>
Carried: <n> units from <run dirs> (same_source); ledger: <run_dir>/ledger.json
```

State which checks ran and which did not. A claim with no run behind it goes under *Not measured*.
