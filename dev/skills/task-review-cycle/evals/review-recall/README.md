# Review-recall fixtures

This fixture set measures recall on real escaped defects. Each fixture is a bug that a merged
PR shipped and a later `[FIX]` PR repaired. The reviewer sees the bug inside its original
full-size introducing diff, which is mostly benign code. That is the regime
`../security-effort/RESULTS.md` names as untested: a planted bug inside a large diff.

Compare the Claude code reviewer, Codex and agy. The separate Claude comments pass is also
run so a change to its prompt or rules is exercised. Its findings are advisory and don't count
toward bug recall. On the lite path, the blocking reviewer is the engine that did not drive the
cycle (`../../references/risk-routing.md` → *Lite reviewer*). That is Codex when Claude Code
drives and Claude when Codex drives. The full re-scoring gate follows
https://claude.dev/blog/solving-code-review-at-anthropic/ (2026-10-15).

## Fixtures

`fixtures.tsv` lists each fixture's introducing commit and fix commit. A finding counts as a hit
only when it states the defect's mechanism at the gold location or names the same symbol. A
finding at that location that describes a different mechanism is a miss. Line numbers refer to
the introducing commit.

| id | Introduced by | Fixed by | Gold location | Mechanism a hit must name |
|----|---------------|----------|---------------|---------------------------|
| f01 | e7379fc #260 | 8acaa9f #261 | `skill_run_health.py` `judge` L172–174 | The boundary is inclusive, but a float comparison reads a drop of exactly the threshold as `ok` |
| f02 | 4d9fd18 #37 | 22808c9 #180 | `bump-version.sh` `bump_skill` L81 (L61–62) | The `version: X$` regex fails to match on CRLF, unescaped dots, or different spacing. Nothing changes, but the script still reports success |
| f03a | ae0ce1c #192 | f83c293 #348 | `task_nodes.py` L466 `read_text` / L457 `write_text` | Universal-newline read turns CRLF into LF before the CRLF-preserving split/join runs |
| f03b | ae0ce1c #192 | 971f6ba | `task_nodes.py` `_split` L156 | `splitlines` also breaks on U+2028 and U+0085, but `rstrip("\r\n")` keeps them, so untouched lines change |
| f05 | 6a46d82 #364 | dbd4e20 #366 | `hub.sh` `ci-status` L228–230 | Head SHA and checks come from two separate reads, so a lagging read pairs the new head with stale checks |
| f06 | bdf1b73 #256 | eead118 #258 | `record_skill_run.py` `_trim` L81–115, `record` L140–141 | Trim reads, then replaces, with no lock, so a concurrent append is lost |
| f07 | fef4297 #121 | fbaa549 #124 | `scan_transcripts.py` `resolve_project_dir` L114–125 | The exact match starts at count 0, so a fuzzy sibling with more files wins |
| f08a | d1376c0 | fcba11a #151 | `commit-and-push.sh` L68 `git push -u` | Push writes its tracking line to stdout and breaks the pure-JSON stdout contract |
| f08b | d1376c0 | a390abf #153 | `commit-and-push.sh` L58 `git commit` | Commit writes its summary to stdout and breaks the same contract |
| f10 | 15291a3 #335 | 390d21a #337 | `prune_ledger.py` `unit_paths` L75–78 | For an explicit JSON `null`, `.get(k, [])` returns `None`, and `*None` raises a TypeError |
| f11 | 419b332 #144 | b60c9b0 #145 | `quiz_state.py` `_fsrs_review` L287 | With the default `fsrs.Scheduler()` learning steps, a correct card is due again the same day |
| f12 | 8ad14b3 #198 | c890389 #288 | `scan_transcripts.py` `HOOK_DENY_RE` L137–139, L604 | The regex is unanchored and runs over the whole tool_result, so ordinary output counts as a hook deny |

f03 and f08 each carry two plants in one diff. The plant ids (f03a, f03b, f08a, f08b) are for
scoring only; `run.sh` takes the fixture ids from `fixtures.tsv` (f03, f08).

These fixtures were selected with `git blame -w -M -C <fix>^` on the line each fix changed.
Near-misses that were rejected, and why:

- 948b015: the introducer is muddled.
- 1a28781: the behavior predates the claimed introducer.
- e218e8e: a design gap, not a defect in a diff.
- 3610e73: the folding arrived later.
- 9ce16c3: Windows curl codepage only.

### Add an escaped defect

When a fix lands for a bug the original review cycle missed, verify the failure at the
introducing commit and the repair at the fix commit. Use `git blame -w -M -C <fix>^` on
the changed lines and inspect the candidate introducer and its parent. Confirm the failure
was introduced by that diff, and check the original review record when available. If the
introducer or the miss cannot be established, record that gap and leave the fixture out.
After both commits are reachable from the evaluation repo, add a new ID, introducing SHA
and fix SHA to `fixtures.tsv`, plus the gold location and mechanism in the table above.
Reuse the fixture ID when several independently scored bugs share one introducing diff.
Re-run the entire set, then add the new scores to `RESULTS.md`.

## Re-run

```bash
OUT_DIR=$(mktemp -d -t review-recall-out.XXXXXX)
echo "$OUT_DIR"
bash dev/skills/task-review-cycle/evals/review-recall/run.sh "$OUT_DIR"           # all fixtures
bash dev/skills/task-review-cycle/evals/review-recall/run.sh "$OUT_DIR" f01 f07   # a subset
```

Run it from a checkout of this repo, with `claude`, `codex`, `agy` and `jq` set up as they are for a
review cycle. Each fixture runs in its own throwaway clone, fetched at depth 2 by commit sha, so
the reviewer cannot reach the fix commit or this table, and the source repo's refs are not
touched. Fixtures run in parallel. The Claude arm's effort is pinned by
`REVIEW_RECALL_EFFORT` (default `medium`) and recorded in each `<id>-meta.txt`.
One `run.sh` runs per out-dir at a time (`.run.lock` holds its pid); a second run on the same
out-dir exits 1, and a lock left by a run killed without a catchable signal (`SIGKILL`) is removed by hand;
`INT` and `TERM` stop the background fixtures and release it. Codex's stdout is cut to head and tail past 40,000 bytes, so a truncated arm is
replaced by the full review from `<id>-codex-result/`, and the arm fails when that sidecar is
incomplete. `check-results.sh` fails when a `scripts/*-review.sh` launcher is not in its input list.
`run.sh` exits 1 on a missing, failed or unreadable review. A full successful run writes
`fingerprint.txt`. Score each code reviewer by hand against the gold table, tally comment
findings separately, and record the date, reviewer versions/mode, effort and results in
`RESULTS.md`. Copy the full-run fingerprint beside those scores and retain the raw evidence.
Raw outputs from earlier runs are kept in `runs/`; replace throwaway paths with `<worktree>/`
when checking in output.

Changes to a launcher, shared review guidance, `comment-rules.md`, `fixtures.tsv` or `run.sh`
invalidate the scorecard. CI's `check-results.sh` checks the latest fingerprint and requires a
scorecard update when the inputs differ from the PR base. CI does not
run the authenticated engines or grade findings. On routing, model or tool changes outside
those files, run the full set and update the scorecard even if the fingerprint stays the same.
