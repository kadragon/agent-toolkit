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
