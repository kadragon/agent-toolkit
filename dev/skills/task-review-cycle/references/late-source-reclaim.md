# Late Review-Source Reclaim

A panel source that has not reported by the time the reviewer returns is recorded as skipped and
the cycle proceeds — but the process does not stop, and its findings can still be real. This is
the step that collects them before the merge closes the window.

**Both panel sources persist a result: `codex-review.sh` and `agy-review.sh`.** The reviewer slot
(`claude-review.sh`) writes no sidecar, and a codex run that exits 75 (another cycle holds the
workspace lock) never started one either. For those, a source that never reported leaves nothing
on disk to come back for — the inline fallback stands.

## Late returns are expected

- A late return is the normal shape: the cycle stops listening when the reviewer returns, never
  the run. Never kill a run at a deadline — that discards the findings this step recovers.
- `codex-review.sh` has no internal deadline; `agy-review.sh` caps itself at `--print-timeout 15m`.
  Keep that cap; lower it only if your `timings.log` shows runs ending near 900s as `empty`/`failed`.

## Where a late result lands

Each source persists every finished run in its own directory inside the git dir — per-worktree,
never tracked:

| Source | Directory (override) |
|--------|----------------------|
| codex | `$(git rev-parse --absolute-git-dir)/codex-review` (`CODEX_REVIEW_RESULT_DIR`) |
| agy | `$(git rev-parse --absolute-git-dir)/agy-review` (`AGY_REVIEW_RESULT_DIR`) |

Key is the branch name with non-`[A-Za-z0-9._-]` runs collapsed to `-`, then leading and
trailing `-` stripped. Both sources use the same three files:

| File | Meaning |
|------|---------|
| `<key>.pending` | the run has not finished; carries `pid=` (this bash process — probe with `kill -0`, never `tasklist`) |
| `<key>.review.txt` | the full, untruncated review text (stdout may have been head/tail truncated) |
| `<key>.meta` | written last, so its presence means the review file beside it is complete |

`.meta` carries `branch`, `started_at`, `head_sha`, `status` (`ok` · `failed` · `empty`) and
`review_file`.

The key is lossy — `feat/x-2` and `feat-x-2` sanitize to the same name — and a file can also be
left from an earlier cycle on this branch. So before using a result, check that its `branch`
matches the current branch and that `started_at` is later than this cycle's launch. A `.meta`
that fails either check belongs to a different run: leave it alone.

`timings.log` in each result directory gets one line per finished run (elapsed, status, diff
size); argue about runway from it, not from one cycle's impression.

## Pre-merge reclaim

Run this **immediately before the merge command**, for each panel source (codex, agy) recorded as
`Reviewers Skipped` this cycle — still running, or failed. On the hub path that means *after*
`ci-wait.sh` returns green — the CI wait is free runway for a slow source, so reclaiming
earlier throws it away.

The key derivation must match `sanitize_key` exactly, trailing-hyphen strip included, or a branch
like `fix-` looks up `fix-.meta` while the script wrote `fix.meta`:

```bash
GIT_DIR_ABS=$(git rev-parse --absolute-git-dir)
KEY=$(git rev-parse --abbrev-ref HEAD \
  | sed -e 's/[^a-zA-Z0-9._-][^a-zA-Z0-9._-]*/-/g' -e 's/^-*//' -e 's/-*$//')
for RESULT_DIR in "${CODEX_REVIEW_RESULT_DIR:-$GIT_DIR_ABS/codex-review}" \
                  "${AGY_REVIEW_RESULT_DIR:-$GIT_DIR_ABS/agy-review}"; do
  echo "== $RESULT_DIR"
  cat "$RESULT_DIR/$KEY.meta" 2>/dev/null || cat "$RESULT_DIR/$KEY.pending" 2>/dev/null || echo "no result"
done
```

| State | Action |
|-------|--------|
| `.meta` with `status=ok` and a non-empty `review_file` | Read the review file. Put its findings through `consolidation-guide.md` and Step 4 apply, exactly as an in-time source. A resulting change commits via `commit-and-push.sh`; on the hub path that re-enters CI — wait for it green again, and say in the report that the reclaim cost an extra CI round. |
| `.pending` only, `pid` alive under `kill -0` | The source is still running. Merge, and report the `.meta` path the user can read when it lands. |
| `.pending` only, `pid` dead | The run died without a result. Nothing to reclaim; the `Reviewers Skipped` line stands. |
| `.meta` with `status=failed` or `empty`, or no files at all | Nothing to reclaim; the `Reviewers Skipped` line stands. |
| `.review.txt` and `.pending` but no `.meta` | The meta write failed after the review landed. Read the review file directly and treat it as `status=ok`. |

`head_sha` in the meta is the commit the late review actually read. When it does not match the
branch's current HEAD — a fix round landed after the source was launched — the findings may
already be closed; re-read the diff before applying, per the consolidation guide's step 2.

## Post-merge arrival

A result that surfaces after the merge is **reported, never auto-filed**. Name the `.meta` and
`.review.txt` paths and the branch they reviewed, and let the user route it.

Do not append it to `## Review Backlog` automatically: the branch is merged, so the findings are
unverified against current `main` and often already closed by the fix round.
