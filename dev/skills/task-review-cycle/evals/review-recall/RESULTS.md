# 2026-11-12 run: Claude slot vs Codex built-in review

**Question.** Does Codex review shallowly? It uses few tokens (about 43k per run) and finishes
in under a minute. That matters most on the lite path, where Codex is the only reviewer
whenever Claude Code drives the cycle.

**Answer.** No. On this set, Codex's recall matched Claude's, and the two caught different
defects.

## Method

Each reviewer ran once per fixture (12 plants in 10 introducing diffs, from +47 to +1,249
lines). The run used an earlier version of `run.sh`, with a worktree of the source repo at the
introducing commit and its parent as the base.

- **Claude:** `claude-review.sh <base> "" ""`, with no contract. The `claude` CLI was version
  2.1.322. The empty effort argument makes code-review reuse the caller's last typed level, so
  this run's effective effort is not recorded. It may have been `high`. `run.sh` now pins the
  effort.
- **Codex:** `codex-review.sh plugin <base>`, using the built-in reviewer with model
  `gpt-6-astra` at reasoning effort `medium`.

The raw outputs are in `runs/`. Codex's own logs (`~/.codex/logs_2.sqlite`) show a normal
finish: `needs_follow_up=false`, `token_limit_reached=false`, and about 4 `exec` calls. Low token
use reflects targeted reading. The runs did not stop early.

## Results

| id | Introducing diff | Claude | Codex |
|----|-----------|--------|-------|
| f01 float boundary | +453 | miss (L172, different issue) | hit (reproduced −0.1999…) |
| f02 bump-version CRLF/spacing | +172 | hit (L61, L74) | miss |
| f03a CRLF via read_text | +1,073 | miss | hit |
| f03b U+2028 splitlines | +1,073 | miss | miss |
| f05 hub.sh two-read race | +157 | hit (L228, conf 50) | hit |
| f06 unlocked trim race | +414 | miss (L97 is about performance) | hit |
| f07 exact match starts at count 0 | +47 | hit | hit |
| f08a push -u stdout | +169 | hit (L58) | hit |
| f08b commit stdout | +169 | hit (L58) | hit |
| f10 JSON null → `*None` | +453 | miss | miss |
| f11 FSRS default steps | +1,249 | hit (L287) | miss |
| f12 unanchored HOOK_DENY_RE | +363 | hit (L604, conf 55) | miss |

- **Recall:** Claude caught 7 of 12 and Codex caught 7 of 12. Both caught the same 4. Together
  they caught 10 of 12.
- **Finding volume:** Claude reported 8–10 findings per diff, 93 in total. Codex reported 1–3
  per diff, 15 in total.
- **Time per diff:** run one at a time (f01–f03), Claude took 136–196 s and Codex 38–54 s. Run
  seven at once (f05–f12), Claude took 109–273 s and Codex 40–61 s.

## Decision (change only on evidence)

- **Hub path:** keep both reviewers. They are complementary: together they caught 10 of 12,
  against 7 for either one alone.
- **Lite path:** keep the non-driving engine as the only reviewer. Claude alone and Codex alone
  each scored 7 of 12 here, so this run shows no recall cost whichever engine drives.
- **Codex effort and prompt:** no change on this evidence. In each of Codex's misses (f02, f11,
  f12), it reported one or two other issues and stopped. Running the same set at reasoning
  effort `high` would test whether depth closes that gap.

## Limits

- One run per arm, on unpinned models.
- n = 12. A difference of one or two fixtures can be noise.
- One grader, the orchestrator.
- This run used worktrees of the source repo, so a reviewer could in principle have reached
  later commits with `git log --all`. `run.sh` now uses isolated depth-2 clones, which removes
  that path.
- Only the gold plants were graded. Claude's other findings were not, so precision is not
  compared.
- The plants escaped the reviewers of their own time, so the set leans toward defects that are
  hard to see.

# 2026-11-26 run for the review-cycle changes

All 10 fixtures have completed output from all four arms. The first attempt with the current
inputs hit HTTP 429. The resumed evaluation ran the eight missing Claude code reviews once at
the suite default of medium. It reused two completed Claude code reviews, all ten Codex reviews,
and three agy reviews from that attempt. Seven agy and ten comments outputs came from the earlier
run. At resume, its agy launcher was unchanged and the shared helper differed only in a shell comment. The
saved comments prompts matched the current prompt after normalizing line endings. The fixture
commit, parent, and CLI versions agreed across reused runs.

Claude Code 2.1.332, Codex CLI 0.172.0 (companion 1.0.6 in branch-scoped adversarial mode), and
agy 1.5.17 reviewed the 12 gold defects. Claude's comments pass ran separately.

| Gold defect | Claude | Codex | agy |
|-------------|--------|-------|-----|
| f01 Float boundary | hit | hit | hit |
| f02 Version rewrite | hit | hit | hit |
| f03a CRLF via `read_text` | hit | hit | hit |
| f03b Unicode line separators | miss | miss | miss |
| f05 Two-read CI status | hit | hit | hit |
| f06 Unlocked trim | miss | hit | hit |
| f07 Exact match starts at zero | hit | hit | hit |
| f08a Push stdout | miss | miss | hit |
| f08b Commit stdout | miss | hit | hit |
| f10 Explicit JSON null | hit | miss | hit |
| f11 Same-day FSRS learning step | hit | miss | hit |
| f12 Unanchored hook-deny pattern | miss | miss | hit |

For f02, Claude and Codex caught the whitespace mismatch in the manifest substitutions at the
alternate gold location (lines 61–62); agy caught the CRLF mismatch in `bump_skill`.

| Source | Gold defects detected | Reported findings | Tagged `pre_existing` |
|--------|----------------------|-------------------|-----------------------|
| Claude code review | 7 / 12 | 56 | 3 |
| Codex | 7 / 12 | 46 | 13 |
| agy | 11 / 12 | 60 | 7 |
| Comments | outside recall scoring | 161 | outside scope |

Together the code reviewers detected 11 of 12 gold defects. Finding counts are unadjudicated.
The historical run used different reviewer modes and unpinned models, and this run combines
completed arms with equivalent inputs across attempts. It does not isolate the impact of a
single change or measure precision.

The PR review follow-up restricted automatically inlined repository guidance to committed files
and bounded its size. For every isolated fixture, the old and new helpers returned the same
empty output because the fixture has no root `REVIEW.md`. The launchers, comments rules and
fixture commits were unchanged, and the runner changed only in a shell comment. The same 40
outputs therefore cover the final fixture inputs without another reviewer call.

Follow-up from the PR #444 backlog: `run.sh` now holds a per-out-dir lock and grades a truncated
Codex stdout from the full sidecar, and `agy-review.sh` exits 1 on an unknown comparison ref
instead of reporting an empty diff. Reviewer invocations, prompts, comments rules and fixtures are
unchanged, and every fixture passes a valid `base` ref, so no reviewer call was repeated. The Codex
arms above were graded from stdout and were not re-collected; a review over the 40,000-byte limit
would have been graded from its head and tail.

Follow-up from the PR #452 backlog: `run.sh` names its lock and sidecar-key code and stops its fixtures' process groups and releases the lock on `INT`/`TERM`, `agy-review.sh` exits 1 when its fallback `git diff` fails instead of skipping as an empty diff, and the fingerprint now also covers `preflight.sh`. Reviewer invocations, prompts, comments rules and fixtures are unchanged, and every fixture has a computable diff, so no reviewer call was repeated.

Follow-up from the PR #453 backlog: `preflight.sh` falls back to lexical sorting when version
sorting fails. Under GNU sort, uncached preflight returned the same Codex mode and companion
path before and after the fix. These are the only preflight values the runner forwards, and the
reviewer commands and fixtures are unchanged. The existing scores are carried forward without
a new reviewer run.

Review recall fingerprint: 3e8057e8b0ee759ee0b743c550b8977e8843bdf7

The re-scoring and disposition protocol follows [How the Claude Code team does code review](https://claude.dev/blog/solving-code-review-at-anthropic/)
(2026-10-15).
