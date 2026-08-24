---
name: task-debug
description: >-
  Diagnosis loop for a hard bug or a performance regression — build a tight, red-capable
  reproduction command before forming any theory, then rank falsifiable hypotheses,
  instrument one variable at a time, and land the regression test. Use when something
  throws, crashes, hangs, corrupts output, or got slow and the cause is unknown — "debug
  this", "diagnose this", "why is it failing". NOT for a defect whose cause is already
  identified — write the fix and its test directly.
version: 1.0.0
---

# Debug

> Adapted from [mattpocock/skills](https://github.com/mattpocock/skills) `skills/engineering/diagnosing-bugs`
> — the feedback-loop-first discipline and its phase gates. Deviations: no `CONTEXT.md`/ADR
> pipeline (this repo has none), and Phase 5 defers to this repo's own `[FIX]` contract and
> *Regression Test Rules* instead of restating them.

A discipline for bugs whose cause is not yet known. Skip a phase only when you can say why
in one line.

## Redact

The phases below have you show commands, outputs, and captured artifacts. **Redact every
secret before showing it** — write `<REDACTED>` in its place, and build loops against env
vars so the credential stays in the environment rather than in the transcript. Captured
artifacts (HAR files, request dumps) carry auth headers: quote only the lines that carry the
signal. If the redacted output is not enough to diagnose the bug, say so and ask the user.

## Phase 1 — Build a feedback loop

**This is the skill.** Everything after it is mechanical. With a **tight** pass/fail signal
that goes **red** on *this* bug, bisection, hypothesis-testing, and instrumentation all just
consume it. Without one, no amount of reading code will find the cause.

Spend disproportionate effort here. Be aggressive, be creative, refuse to give up.

Ways to construct one, in roughly this order:

1. **Failing test** at whatever seam reaches the bug — unit, integration, end-to-end.
2. **Script against a running process** — `curl` against a dev server, a CLI invocation with a
   fixture input diffed against known-good output.
3. **Headless browser script** driving the UI and asserting on DOM, console, or network.
4. **Replay a captured trace** — save a real payload or event log to disk, replay it through
   the code path in isolation.
5. **Throwaway harness** — a minimal subset of the system that reaches the bug's code path in
   one function call.
6. **Property or fuzz loop** — for "sometimes wrong output", run many random inputs and watch
   for the failure mode.
7. **Bisection harness** — if the bug appeared between two known states (commit, dataset,
   version), automate "boot at state, check, repeat" so `git bisect run` can drive it.
8. **Differential loop** — same input through two versions or two configs, diff the outputs.
9. **Human-in-the-loop script** — last resort. If a person must click, drive *them* with a
   script that prompts, waits, and captures, so the loop stays structured.

### Tighten it

Treat the loop as a product. Once you have *a* loop, tighten it:

- **Faster** — cache setup, skip unrelated init, narrow the test scope.
- **Sharper** — assert on the specific symptom, not "did not crash".
- **More deterministic** — pin time, seed RNG, isolate the filesystem, freeze the network.

A 30-second flaky loop is barely better than none; a 2-second deterministic one is a
superpower. For a non-deterministic bug the goal is not a clean repro but a **higher
reproduction rate** — loop the trigger, parallelize, add stress, inject sleeps until the rate
is high enough to debug against.

### Completion criterion

Phase 1 is done when you can name **one command** that you have **already run at least once**
(show the invocation and its output, redacted), and that is:

- [ ] **Red-capable** — drives the actual bug code path and asserts the *user's exact
      symptom*, so it goes red now and green once fixed. Not "runs without erroring".
- [ ] **Deterministic** — same verdict every run (flaky bug: a pinned, high reproduction rate).
- [ ] **Fast** — seconds, not minutes.
- [ ] **Agent-runnable** — you can run it unattended.

If you catch yourself reading code to build a theory before that command exists, **stop**:
jumping to a hypothesis is the exact failure this skill prevents. No red-capable command, no
Phase 2.

**When you genuinely cannot build one**, stop and say so. List what you tried, then ask the
user for one of: access to an environment that reproduces it, a redacted captured artifact
(HAR, log dump, screen recording with timestamps), or permission to add temporary
instrumentation to the failing environment. Do not proceed to hypothesize without a loop.

## Phase 2 — Reproduce, then minimise

Run the loop and watch it go red. Confirm all three:

- [ ] The failure is the one the **user** described, not a different failure nearby. Wrong
      bug, wrong fix.
- [ ] It reproduces across multiple runs (or at a high enough rate, for a flaky bug).
- [ ] The exact symptom is captured — error text, wrong value, measured timing — so later
      phases can verify the fix addresses *it*.

Then shrink the repro to the **smallest scenario that still goes red**: cut inputs, callers,
config, data, and steps one at a time, re-running after each cut. Done when every remaining
element is load-bearing — removing any one of them turns the loop green.

Minimising is not tidying: it shrinks the hypothesis space for Phase 3 and becomes the clean
regression test in Phase 5.

## Phase 3 — Hypothesise

Generate **3–5 ranked hypotheses before testing any of them**. Generating one at a time
anchors you on the first plausible idea.

Each must be falsifiable — state the prediction it makes:

```
If <cause> is it, then <change X> makes the bug disappear / <change Y> makes it worse.
```

A hypothesis with no stated prediction is a vibe: sharpen it or drop it.

Show the ranked list to the user before testing. They often re-rank it instantly ("we
deployed a change to #3 yesterday") or have already ruled one out. Do not block on the reply —
if no user is reachable, proceed with your own ranking and say so.

## Phase 4 — Instrument

Every probe maps to one prediction from Phase 3, and **one variable changes at a time**.

Tool order:

1. **Debugger or REPL inspection** where the environment supports it — one breakpoint beats
   ten log lines.
2. **Targeted logs** at the boundaries that distinguish the hypotheses.
3. Never "log everything and grep".

Tag every debug log with a unique prefix — `[DEBUG-a4f2]` — so cleanup is one grep:

```sh
grep -rn "DEBUG-a4f2" .
```

Untagged logs survive the cleanup; tagged ones die.

**Performance regressions take the other branch.** Logs are usually the wrong instrument:
establish a baseline measurement first (timing harness, profiler, query plan), then bisect
against it. Measure first, fix second.

## Phase 5 — Fix with a regression test

Write the regression test **before** the fix, at a **correct seam** — one where the test
exercises the real bug pattern as it occurs at the call site. A seam too shallow to replicate
the chain that triggered the bug gives false confidence, and **its absence is itself the
finding**: report that the architecture is preventing the bug from being locked down rather
than shipping a test that cannot fail on it.

Where a correct seam exists:

1. Turn the minimised repro into a failing test there.
2. Watch it fail.
3. Apply the minimal fix.
4. Watch it pass.
5. Re-run the Phase 1 loop against the original, un-minimised scenario.

Two repo rules own the rest and are not restated here — read them:

- `docs/conventions.md` → *Regression Test Rules* — the test must fail against the bug it
  names; verify by removing the guard and watching it go red.
- `docs/eval-criteria.md` → *Sprint Contract* — a `[FIX]` contract must carry an acceptance
  criterion naming this test.

## Phase 6 — Cleanup

Required before declaring done:

- [ ] The Phase 1 loop no longer reproduces the bug.
- [ ] The regression test passes — or the absence of a correct seam is written down.
- [ ] All tagged instrumentation removed (grep the prefix).
- [ ] Throwaway harnesses deleted, or moved under the session scratchpad directory.
- [ ] The hypothesis that turned out correct is stated in the commit or PR body, so the next
      person debugging this area inherits it.
