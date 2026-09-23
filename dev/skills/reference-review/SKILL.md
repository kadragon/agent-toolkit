---
name: reference-review
description: "Benchmark a repo's skills, agents, or task cycle against an external skills/harness repo (mattpocock/skills, revfactory/harness, a named GitHub URL) or current agentic-coding practice — what to adopt and what here is over-built. Use when asked to review, compare, or improve our harness from an outside reference, or to check for too much harness. NOT for mining our own transcripts → dev:harness-curate."
version: 1.0.0
---

# Reference review — adopt and cut, against an outside reference

A recurring request: "we borrowed from repo X; X has moved on — what should we take, and where
did we over-build?" This skill fixes the shape of that answer so each run is
comparable and every borrowed idea stays traceable to its source.

## Step 1 — Pin the reference

Resolve each named reference to a commit, not a branch: `gh api repos/{owner}/{repo}/commits/HEAD
--jq .sha` (or the file URL's `blob/{sha}`). A web trend survey with no repo pins each source's URL
and date instead. Every later citation uses `{repo}@{short-sha}:{path}` — `main` drifts, and the
next run diffs against this pin.

Done when: every reference has a pinned sha or dated URL.

## Step 2 — Map counterparts

For each asset in the reference that falls in scope (the user named a skill or area → that area
only), name its counterpart here or `absent`. Read both files — a counterpart judged by name alone
is a guess, and a guessed counterpart makes every later row wrong.

Done when: every in-scope reference asset has a row `{their path | our path or absent | read both: yes}`.

## Step 3 — Two lenses, one table

- **Adopt** — something the reference does that ours lacks or does worse, with the failure it
  would prevent here. No failure this repo has hit or can name → it is taste, drop it.
- **Cut** — something ours carries that the reference achieves without, or a gate/step/prose
  block whose removal would cause no mistake. Cuts count as findings,
  not an afterthought; a leaner harness outranks feature parity.

One ranked table: `| # | Lens | Our asset | Reference evidence | Change | Why (failure prevented or load removed) |`.
Number the rows — the user answers by number.

Done when: every row cites a pinned reference path, and every Adopt row names a failure.

## Step 4 — Stop for selection

Present the table and stop. Implement only the numbers the user picks, through the repo's normal task
cycle (`/dev:task-new`, or a backlog item) — this skill never edits assets itself.

When a picked change lands, name the reference (`{repo}@{sha}:{path}`) in the changed artifact and
in the commit body — borrowed design is attributed even when nobody asks.
