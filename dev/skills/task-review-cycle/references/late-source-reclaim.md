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

Codex uses a branch key with non-`[A-Za-z0-9._-]` runs collapsed to `-` and leading and
trailing `-` stripped. Each agy invocation prints its private `<full head SHA>/run.XXXXXX/`
directory on stderr before running. Save that path with the launch checkpoint.

| Codex | agy (inside the invocation directory) | Meaning |
|-------|--------------------------------------|---------|
| `<key>.pending` | `review.pending` | the run has not finished; carries `pid=` (the bash process, checked with `kill -0`) |
| `<key>.review.txt` | `review.txt` | the full review text |
| `<key>.meta` | `review.meta` | written after the review text |

`.meta` carries `branch`, `started_at`, `head_sha`, `status` (`ok` · `failed` · `empty`) and
`review_file`.

Before using a result, verify `branch` and `started_at` against the intended launch. Codex branch
keys can collide. For agy, use the recorded invocation directory and verify its full `head_sha`
and `base_sha` against the review request. If the directory was lost, list invocations for the
expected head and use launch evidence to identify the exact run. If multiple invocations match
and the intended run cannot be identified, treat the result as unavailable. Legacy branch-keyed
agy files do not establish review provenance for a refreshed head.

`timings.log` in each result directory gets one line per finished run (elapsed, status, diff
size); argue about runway from it, not from one cycle's impression.

## Pre-merge reclaim

Run this during *Final verification*, for each panel source (codex, agy) recorded as
`Reviewers Skipped` this cycle — still running, failed, or agy quota-exhausted. On the hub path that means *after*
`ci-wait.sh` returns green — the CI wait is free runway for a slow source, so reclaiming
earlier throws it away.

The key derivation must match `sanitize_key` exactly, trailing-hyphen strip included, or a branch
like `fix-` looks up `fix-.meta` while the script wrote `fix.meta`:

```bash
GIT_DIR_ABS=$(git rev-parse --absolute-git-dir)
HEAD_SHA=$(git rev-parse --verify HEAD)
KEY=$(git rev-parse --abbrev-ref HEAD \
  | sed -e 's/[^a-zA-Z0-9._-][^a-zA-Z0-9._-]*/-/g' -e 's/^-*//' -e 's/-*$//')
CODEX_DIR=${CODEX_REVIEW_RESULT_DIR:-$GIT_DIR_ABS/codex-review}
cat "$CODEX_DIR/$KEY.meta" 2>/dev/null || cat "$CODEX_DIR/$KEY.pending" 2>/dev/null || echo "no Codex result"
AGY_DIR=${AGY_REVIEW_RESULT_DIR:-$GIT_DIR_ABS/agy-review}
for RUN_DIR in "$AGY_DIR/$HEAD_SHA"/run.*; do
  [ -d "$RUN_DIR" ] || continue
  echo "== $RUN_DIR"
  cat "$RUN_DIR/review.meta" 2>/dev/null || cat "$RUN_DIR/review.pending" 2>/dev/null || echo "no agy result"
done
```

| State | Action |
|-------|--------|
| `.meta` with `status=ok` and a non-empty `review_file` | Read the review file and apply the existing review gate and cap in `consolidation-guide.md`. A resulting repair gets targeted checks and a commit via `commit-and-push.sh`. On hub, wait for CI on that head and report the extra CI round. |
| `.pending` only, `pid` alive under `kill -0` | The source is still running. Continue final verification and report the `.meta` path. |
| `.pending` only, `pid` dead | The run died without a result. Nothing to reclaim; the `Reviewers Skipped` line stands. |
| `.meta` with `status=failed` or `empty`, or no files at all | Nothing to reclaim; the `Reviewers Skipped` line stands. |
| agy `.meta` with `status=quota-exhausted` for the matching invocation and head | Record the skip and any reset. Reclaim a successful result already available for this head. Otherwise do not relaunch or wait solely for the quota reset. |
| `.review.txt` and `.pending` but no `.meta` | The meta write failed after the review landed. Read the review file directly and treat it as `status=ok`. |

`head_sha` in the meta is the commit the late review actually read. When it does not match the
branch's current HEAD — a fix round landed after the source was launched — the findings may
already be closed; re-read the diff before applying, per the consolidation guide's step 2.

## Post-merge arrival

A result that surfaces after the merge is **reported, never auto-filed**. Name the `.meta` and
`.review.txt` paths and the branch they reviewed, and let the user route it.

Automatic queue filing ends at merge. Late findings need verification against current `main`
because the fix round may already have closed them.
