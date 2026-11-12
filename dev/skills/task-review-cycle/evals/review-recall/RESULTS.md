# 2026-11-12 run: Claude slot vs Codex built-in review

**Question.** Does Codex review shallowly? It uses few tokens (about 43k per run) and finishes
in under a minute. That matters most on the lite path, where Codex is the only reviewer.

**Answer.** No. On this set, Codex's recall matched Claude's, and the two caught different
defects.

## Method

Each reviewer ran once per fixture (12 plants in 10 introducing diffs, from +47 to +1,249
lines). The run used `run.sh`, with a worktree at the introducing commit and its parent as the
base.

- **Claude:** `claude-review.sh <base> "" ""`, at default effort, with no contract. The
  `claude` CLI was version 2.1.322.
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
- **Finding volume:** Claude reported 8–10 findings per diff, about 92 in total. Codex reported
  1–3 per diff, 16 in total.
- **Time per diff:** Claude took 109–273 s, with a median of about 150 s. Codex took 38–61 s.

## Decision (change only on evidence)

- **Hub path:** keep both reviewers. They are complementary: together they caught 10 of 12,
  against 7 for either one alone.
- **Lite path:** keep Codex as the only reviewer. Claude alone scored the same 7 of 12 here, so
  this run shows no recall cost to that choice.
- **Codex effort and prompt:** no change on this evidence. In each of Codex's misses (f02, f11,
  f12), it reported one or two other issues and stopped. Running the same set at reasoning
  effort `high` would test whether depth closes that gap.

## Limits

- One run per arm, on unpinned models.
- n = 12. A difference of one or two fixtures can be noise.
- One grader, the orchestrator.
- Only the gold plants were graded. Claude's other findings were not, so precision is not
  compared.
- The plants escaped the reviewers of their own time, so the set leans toward defects that are
  hard to see.
