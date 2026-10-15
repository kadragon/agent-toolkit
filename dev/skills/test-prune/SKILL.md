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
version: 1.0.0
---

# Test Prune

> Synthesized from: [computerphilosopher/agent-skills](https://github.com/computerphilosopher/agent-skills)
> `skills/false-green-detector` (break-it probe on a temporary copy; a crash is not a detection),
> [obra/superpowers](https://github.com/obra/superpowers) `skills/test-driven-development/writing-good-tests.md`
> (smell catalog; "which production change should fail this test"), Kent Beck's
> [Test Desiderata](https://testdesiderata.com/) (behavioral vs structure-sensitive), the Stryker,
> PIT and mutmut docs (equivalent mutants, timeouts, caches), and a user-supplied mutation-sampling
> methodology (count by checked items, sample ~4% per file, calibrate the tool, green baseline).
> Rules are paraphrased; no upstream text is copied.

A test earns its place by **failing when production code breaks**. Test count is not value, and
reading is not evidence: reading yields *candidates*, only a **kill set** measurement yields a
*verdict*. The kill set is the set of mutants the suite detects; every removal in this skill must
leave it unchanged.

## Ground rules

- **Copy first.** Every mutation run happens in a disposable copy — a `git worktree` under the
  session scratchpad directory. The original tree receives only the final Step 5 edits.
- **Delete, merge, or keep — never weaken.** A kept test keeps every assertion it had.
- **Audit-only requests stop after Step 4** with the report. Edits need a request to clean up.
- **Gaps are reported, not filled.** Writing new tests is a separate task.
- **Kept beats deleted when evidence is missing.** No recorded verdict, no removal.

## Step 1 — Map where the count comes from

Export per-file test counts in machine-readable form and sort descending:

| Runner | Command |
|---|---|
| vitest | `vitest run --reporter=json --outputFile=<scratch>/counts.json` |
| jest | `jest --json --outputFile=<scratch>/counts.json` |
| pytest | `pytest --collect-only -q` (group the node ids by file) |
| go | `go test -list '.*' ./...` |

Look for runner flags in the repo's own config before assuming these. For every parametrized
block (`it.each`, `test.each`, `@pytest.mark.parametrize`, table tests) record **generated cases**
and **distinct input classes** — a key × locale matrix that generates 400 cases may check two
behaviors. Data-driven volume is counted by what it checks, not by what it generates.

**Done:** a table of the heaviest files with raw count, and for each parametrized block, cases vs
distinct input classes.

## Step 2 — Read and flag candidates

Run the grep seeds in `references/smells.md` → *Grep seeds*, then **read every hit in full**.
Report only tests you read. For each candidate, write one line:

```
<file>::<test> | <smell> | production change that should fail it: <change> | bug or decision: <bug|decision|none>
```

"Decision" means only an intentional edit (a constant, message wording, private structure) can
fail it; "none" means no realistic change fails it. Then apply the *Keep rules* in the same
reference: a test matching one leaves the list now, with the rule named.

On a large suite, readers may split by test directory; each returns lines in this format and
nothing it did not read.

**Done:** every grep hit read, every candidate in the line format, nothing deleted.

## Step 3 — Measure the kill set

Read `references/mutation-proof.md` before the first run — it holds tool setup, sampling, and the
traps that produced false numbers in practice. In order:

1. **Calibrate.** In the copy, inject one mutant that must be killed and one that must survive
   (a change in dead code or a comment-equivalent). Proceed only if the tool reports exactly
   KILLED and SURVIVED for them.
2. **Generate and sample.** Use the repo's mutation tool (Stryker, mutmut, PIT, cargo-mutants…).
   On a large suite, sample per file (about 4%, minimum 3, fixed random seed recorded). Add, for
   every candidate, at least 3 mutants in the code that candidate claims to cover.
3. **Run each mutant** against the related tests only, with a **green baseline** confirmed first:

   | Outcome | Meaning |
   |---|---|
   | KILLED | an assertion failed |
   | SURVIVED | all related tests passed |
   | INVALID | compile error, import error, crash before any assertion, or unreviewed timeout — excluded |

4. **Record the kill matrix** — each mutant → the tests that killed it. Use the tool's per-test
   output only when it lists every killing test, not just the first; otherwise rerun with the
   candidate removed (leave-one-out).

**No mutation tool available:** write the candidate's mutants by hand — wrong constant or
boundary, flipped branch, dropped side effect, empty/default return, removed validation — apply
each in the copy, and run the candidate alone, then the suite without it. Same table, same
matrix.

**Done:** every candidate has a verdict line naming the mutants it kills and which kept tests
also kill them.

## Step 4 — Classify

For each candidate T, with K(T) = the mutants T kills:

| Verdict | Condition | Action |
|---|---|---|
| **DELETE** | every mutant in K(T) is also killed by a kept test | remove T |
| **MERGE** | T and siblings differ only in input values of one class | collapse to one case per distinct input class |
| **DELETE + GAP** | K(T) is empty after the targeted mutants | remove T; log the behavior its title claims as a gap |
| **KEEP** | T is the **sole killer** of any mutant, or a *Keep rule* applies | leave T; note why |

Decide removals **as a set**, not one at a time: two tests can each look redundant because the
other exists. Re-run every mutant in the union of the removal set's K(T) with the whole set
removed; any mutant that turns SURVIVED returns its sole killer to KEEP.

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
for shared fixtures a deletion orphaned — remove those only when nothing else imports them.

## Step 6 — Verify independently

1. **Re-inject every mutant** in the removal set's union K(T) against the edited tree in one
   pass. Every one must be KILLED.
2. **Run the full suite at least 3 times** (5 when tests use real timers, concurrency, or
   network) — all green.
3. **Before/after numbers** — test count, distinct checks, runtime.
4. When another agent did Steps 4–5, a reviewer that took no part checks: no assertion weakened,
   every title matches its body, no new flakiness from real timers.

## Report

```
Removed: <n> tests (<m> merged into <k>) — kill set unchanged: <x>/<x> mutants re-killed
Runtime: <before> → <after>; count: <before> → <after>
| Test | Verdict | Smell | Mutants it killed | Also killed by |
Gaps: <file:line — mutation — behavior unprotected>
Production bugs: <file:line — what the mutant revealed>
Equivalent mutants: <id — reason>
Not measured: <files outside the sample, INVALID count, tool limits>
```

State which checks ran and which did not. A claim with no run behind it goes under *Not measured*.
