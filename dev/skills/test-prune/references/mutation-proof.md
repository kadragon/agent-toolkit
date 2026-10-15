# Mutation proof — setup, sampling, traps

Reference for `test-prune` Step 3. The goal is a kill matrix you can trust: mutant → tests that
killed it. Every trap below produced a wrong number in a real run before it was written down.

## Work on a copy

```sh
SCRATCH="<session scratchpad directory>"
git worktree add "$SCRATCH/prune-copy" HEAD
```

Make the copy from a clean working tree (SKILL.md *Ground rules*). Run every mutant there. Install dependencies in the copy itself; a symlinked `node_modules` or
virtualenv shared with the original can let a mutation run write into the original tree. Remove
the worktree (`git worktree remove "$SCRATCH/prune-copy"`) after the report.

## Tools

| Ecosystem | Tool | Per-test kill data |
|---|---|---|
| JS/TS | Stryker (`@stryker-mutator/core` + runner plugin) | JSON report `killedBy` — **only with `disableBail: true`**; by default it holds the first failing test alone |
| Python | mutmut | none documented — use leave-one-out |
| JVM | PIT | `fullMutationMatrix=true` with XML output (upstream calls it partially supported) |
| Rust | cargo-mutants | none — use leave-one-out |
| Any | hand-written mutants | build the matrix yourself |

A kill list that stops at the first failing test makes every killed mutant look like it has a
sole killer, so every candidate turns KEEP. Confirm the tool reports *all* killing tests — some
mutant should list more than one — before reading sole-killer verdicts from it; otherwise use
leave-one-out. Read the tool's docs for the installed version before relying on a flag. A runner major-version upgrade can break the tool's integration
silently — see *Trap 1*.

## Sampling

A full run is often thousands of mutants. Sample instead:

- **Per file**, about 4% of its mutants, minimum 3, so small files are not skipped.
- **Fixed seed**, recorded in the report, so the sample can be re-drawn.
- **Plus targeted mutants** — at least 3 per Step 2 candidate, in the code that candidate names.
  A random sample may never touch the lines a candidate covers, and an empty K(T) from a sample
  that missed its code proves nothing.

## Running one mutant

```
1. restore only the production file the previous mutant changed
   (git -C <copy> checkout -- <mutated file>) — a blanket `checkout -- .` would also undo the
   test removals leave-one-out and the Step 4 joint re-run depend on
2. run the related tests unmutated → must pass (green baseline)
3. apply the mutant; print 3 lines of context around the changed span and check it is the
   intended token
4. run the related tests (vitest related <file>, jest --findRelatedTests <file>,
   pytest on the tests that import the module)
5. record KILLED / SURVIVED / INVALID with the failing tests' ids
```

Related-test selection must include every test that can reach the file. When unsure, run the
whole suite for that mutant; a too-narrow selection reports false SURVIVED.

## Leave-one-out

Without per-test kill data: for each candidate T, rerun **every** KILLED mutant with T removed (or
`.skip`ped in the copy). Still KILLED → another test covers it. Turned SURVIVED → T is its sole
killer. Do not narrow the rerun to T's own code region: a test kills mutants anywhere its
execution reaches, including callees and shared helpers in other files. To cut cost, first
rerun only T itself against all KILLED mutants; the ones T fails on are K(T), and only those need
the without-T rerun.

## Traps

1. **0% killed with a green suite is a tool fault, not a test fault.** A runner/tool version
   mismatch can make every mutant "survive". Stop and fix the integration.
2. **A score that looks too good gets its locations checked.** One off-by-one in column numbers
   (1-based read as 0-based) shifts every mutation by a character, turns them into syntax errors,
   and counts the syntax errors as kills — inflating 75% to 97% in one observed run. Print the
   mutated span for a handful of mutants before trusting any rate.
3. **A crash is not a kill.** Compile errors, import errors, and setup failures are INVALID; a
   kill is an assertion failing on changed behavior.
4. **KILLED counts only over a green baseline.** A test file half-edited by a parallel agent, or a
   flaky test, fails regardless of the mutant. Check the baseline before every mutant, not once.
5. **Calibrate the tool before use.** One mutant that must be killed, one that must survive; the
   tool must tell them apart. Re-calibrate after changing tool config.
6. **Timeouts flip between runs.** A mutant that times out (often counted as detected) may be
   killed or survive on a calmer machine. Re-run timeouts before they decide a verdict; an
   unresolved one is INVALID.
7. **Caches go stale.** Incremental tools re-test only changed functions; a change outside source
   (fixtures, config) leaves old results. Clear the cache when inputs outside the mutated code
   change.
8. **Equivalent mutants exist and cannot be detected automatically.** A survivor is a candidate
   gap until someone shows the behavior differs; write the reason when it does not.
9. **Code with no test coverage counts every mutant as survived.** That is a coverage fact, not a
   verdict on any existing test.
