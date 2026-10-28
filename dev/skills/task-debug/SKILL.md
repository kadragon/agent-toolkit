---
name: task-debug
description: >-
  Diagnosis loop for a hard bug or performance regression — build a red-capable
  reproduction command before any theory, rank falsifiable hypotheses, instrument
  one variable at a time, land the regression test. Use for "debug this",
  "diagnose this", "why is it failing" — something throws, crashes, hangs,
  corrupts output, or got slow with an unknown cause. NOT when the cause is
  already identified — fix and test directly.
version: 1.1.1
---

# Debug

> Adapted from [mattpocock/skills](https://github.com/mattpocock/skills) `skills/engineering/diagnosing-bugs`
> (feedback-loop-first phase gates; no `CONTEXT.md`/ADR pipeline here). The premise check,
> benchmark minimums and refuted-change revert come from `cursor/plugins@9b93e81` pstack
> (`principle-attack-the-premise`, `benchmark-checklist`, `poteto-mode/playbooks/bug-fix.md`).

A discipline for bugs whose cause is not yet known. Skip a phase only when you can say why
in one line.

## Redact

**Redact every secret before showing a command, output, or artifact** — write `<REDACTED>`,
and build loops against env vars so credentials stay out of the transcript. From HAR files and
request dumps quote only the lines that carry the signal. If the redacted output is not
enough to diagnose, say so and ask the user.

## Phase 1 — Build a feedback loop

Everything after this phase consumes a tight pass/fail signal that goes **red** on *this* bug;
without one, reading code will not find the cause. Pick whatever seam reaches the bug — a
failing test, a script against a running process, a replayed trace, a throwaway harness, a
fuzz loop, `git bisect run`, a differential run of two versions — and tighten it: faster,
asserting on the specific symptom, deterministic (pinned time, seeded RNG, isolated
filesystem and network). For a non-deterministic bug, raise the reproduction rate (loop,
parallelize, add stress) until it is high enough to debug against.

### Completion criterion

Phase 1 is done when you can name **one command** that you have **already run at least once**
(show the invocation and its output, redacted), and that is:

- [ ] **Red-capable** — drives the actual bug code path and asserts the *user's exact
      symptom*, so it goes red now and green once fixed. Not "runs without erroring".
- [ ] **Deterministic** — same verdict every run (flaky bug: a pinned, high reproduction rate).
- [ ] **Fast** — seconds, not minutes.
- [ ] **Agent-runnable** — you can run it unattended.

No red-capable command, no Phase 2 — do not build a theory from code before it exists.

**When you genuinely cannot build one**, stop and say so. List what you tried, then ask the
user for one of: access to an environment that reproduces it, a redacted captured artifact
(HAR, log dump, screen recording with timestamps), or permission to add temporary
instrumentation to the failing environment.

## Phase 2 — Reproduce, then minimise

Run the loop and watch it go red. Confirm all three:

- [ ] The failure is the one the **user** described, not a different failure nearby.
- [ ] It reproduces across multiple runs (or at a high enough rate, for a flaky bug).
- [ ] The exact symptom is captured — error text, wrong value, measured timing.

Then shrink the repro to the **smallest scenario that still goes red**, cutting one element
at a time and re-running. Done when removing any remaining element turns the loop green.

## Phase 3 — Hypothesise

Generate **3–5 ranked hypotheses before testing any of them**. Each states its prediction:

```
If <cause> is it, then <change X> makes the bug disappear / <change Y> makes it worse.
```

Show the ranked list to the user before testing; if no user is reachable, proceed with your
own ranking and say so.

**Two failed fixes → test the premise.** When two fixes have failed the same check, write
down the one sentence both assumed, then run the observation that would come out differently
if that sentence were false. No third fix before that check runs: if it contradicts the
premise, re-rank from what the failures share; if it confirms it, ask the next "why".

## Phase 4 — Instrument

Every probe maps to one prediction from Phase 3, and **one variable changes at a time**.
Prefer a debugger or REPL, then targeted logs at the boundaries that distinguish the
hypotheses — never "log everything and grep".

Tag every debug log with a unique prefix — `[DEBUG-a4f2]` — so cleanup is one grep:

```sh
grep -rn "DEBUG-a4f2" .
```

**Performance regressions:** establish a baseline measurement first (timing harness,
profiler, query plan), then bisect against it. A before/after number counts only when:

- [ ] each side ran at least 5 times, interleaved (A, B, A, B), reported as median and range —
      a gap inside the run-to-run range is no measurable difference;
- [ ] failures and non-success results were counted on both sides (an error is often fast);
- [ ] the timed region did the work — the rows were written, the request reached the server,
      the result was used;
- [ ] the bound is named (CPU, a lock, I/O, the load generator) from a profile, not a guess.

Any box unchecked → report the result as inconclusive and name the gap.

## Phase 5 — Fix with a regression test

Write the regression test **before** the fix, at a **correct seam** — one where the test
exercises the real bug pattern as it occurs at the call site. If no such seam exists, **that
absence is the finding**: report it rather than shipping a test that cannot fail on the bug.

Where a correct seam exists:

1. Turn the minimised repro into a failing test there.
2. Watch it fail.
3. Apply the minimal fix.
4. Watch it pass. A second fix that also stays red → back to Phase 3's premise check before
   any third fix.
5. Re-run the Phase 1 loop against the original, un-minimised scenario.

Two repo rules own the rest where the repo states them — read them there rather than recalling
them, and fall back to the inline form when the file or section is absent:

- `docs/conventions.md` → *Regression Test Rules* — the test must fail against the bug it
  names. **No such file or section:** apply the rule directly — remove the guard the test
  targets, confirm `git diff -- <target file>` changed from its snapshot taken just before,
  re-run, confirm it goes red on the test's own assertion (not an import or syntax error),
  restore, and confirm the diff matches the snapshot again — the uncommitted fix stays in it.
- `../task-next/references/cycle.md` → *Sprint Contract* — a `[FIX]` contract must carry an
  acceptance criterion naming this test. **Outside a cycle:** name the test in the commit or
  PR body instead, so the reproduction stays gradable.

## Phase 6 — Cleanup

Required before declaring done:

- [ ] The Phase 1 loop no longer reproduces the bug.
- [ ] The regression test passes — or the absence of a correct seam is written down.
- [ ] All tagged instrumentation removed (grep the prefix).
- [ ] Every code change a refuted hypothesis motivated is reverted — only the change the
      surviving hypothesis justifies ships.
- [ ] Throwaway harnesses deleted, or moved under the session scratchpad directory.
- [ ] The hypothesis that turned out correct is stated in the commit or PR body.

## Hand back

End by returning three things to whoever called this loop: the Phase 1 repro command, the
regression test id (or the missing-seam finding), and the surviving hypothesis. Inside a
`task-next`/`task-new` cycle — `../task-next/scripts/cycle_state.py inspect`, run in the cycle's
checkout (its worktree under `--tree`), shows an archived contract — record all three there with
`cycle_state.py note`, so a fresh session resumes from them, and propose the regression test as
an acceptance criterion. Adding it is a contract revision the cycle owner approves
(`../task-next/references/cycle.md` → *Plan gate*), never a `save --replace` from this loop.
