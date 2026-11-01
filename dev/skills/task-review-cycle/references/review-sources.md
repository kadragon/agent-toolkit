# Panel Review Sources

The non-Claude engines (agy, Codex), and the optional pane that shows every reviewer's progress.

## Review pane

Inside herdr-core (`$HC_TERMINAL_ID` set, `herdr-app` on PATH) Step 2 opens a read-only split
beside the agent's own pane that tails a per-run progress log, so the person can watch the review.
It is a view only: reviewers run, time out, and are reclaimed exactly as without it. Open it
first in Step 2, before the panel launch or the reviewer call:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
bash "$SKILL_DIR/scripts/review-pane.sh" open
```

Output is `{"pane":"…","log":"…"}` or nothing. Paste `log` as `PROGRESS_LOG` into every Step 2
reviewer block (Claude, lite Codex, panel agy/Codex); nothing printed → `PROGRESS_LOG` empty and
no pane. The pane is a results board: the Claude reviewer streams its tool calls and subagent
start/finish lines, then writes each finding (severity, place, problem, how it fails); agy and
Codex run in print mode, so their blocks write a started line, then their review text once done.

Keep it open through Step 3, so the person can read the findings while they are consolidated and
confirmed; close it when Step 3 ends, or wherever the cycle stops before it — reviewer sentinel,
600s timeout and inline fallback included — so no exit path leaves a stale pane. A panel source
that finishes later still writes to the log; its result comes through the sidecar reclaim:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
bash "$SKILL_DIR/scripts/review-pane.sh" close "<pane from the open, or empty>"
```

## Panel source launch

Lite reuses the codex block below as its one reviewer, run in the foreground (`risk-routing.md` → *Lite
reviewer*); the rest of this section is the panel. Launch the panel sources (when
`risk-routing.md` → *Panel* runs it) in the turn **before** the reviewer call, `run_in_background:
true`, so they run while the reviewer holds the foreground for up to its 600s.

**The cycle never waits on them.** When the reviewer's array is in hand, whichever sources have
reported are consolidated and each one that has not is recorded as
`Reviewers Skipped: still running`; Step 3 begins there. A source that failed or exited 75 is
recorded with that reason instead. Nothing here is ever stopped — see SKILL.md Step 2 and
`late-source-reclaim.md`, which is what makes not waiting safe for codex and agy.

Launch agy and codex as **two separate background tasks**, one block each. A single task id
cannot serve both: stopping it to close a breached agy would kill the codex child mid-run, and
`late-source-reclaim.md` then finds a `.pending` whose pid is dead — the late findings the reclaim
exists to recover are gone. Neither is stopped by the cycle (SKILL.md Step 2); the split is what
keeps that safe.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
AGY_AVAILABLE=$(jq -r '.agy_available' <<<"$PREFLIGHT")
PROGRESS_LOG="<log from the Review pane open, or empty>"
agy_outcome=ok
if [[ "$AGY_AVAILABLE" == "true" ]]; then
  [[ -z "$PROGRESS_LOG" ]] || { printf '%s\n' "== agy review started"; } 2>/dev/null >>"$PROGRESS_LOG" || true
  AGY_OUT=$(bash "$SKILL_DIR/scripts/agy-review.sh" "${BASE_BRANCH}") || { agy_outcome=failed; echo '{"agy_review":"failed"}' >&2; }
  printf '%s\n' "$AGY_OUT"
else
  agy_outcome=unavailable
  echo '{"agy_review":"unavailable"}' >&2   # not run — distinct from a run that returned no findings
fi
[[ -z "$PROGRESS_LOG" ]] || { printf '%s\n' "== agy review finished: $agy_outcome" "${AGY_OUT:-}"; } 2>/dev/null >>"$PROGRESS_LOG" || true
```

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
CODEX_AVAILABLE=$(jq -r '.codex_available' <<<"$PREFLIGHT")
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")
CODEX_COMPANION_PATH=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")
PROGRESS_LOG="<log from the Review pane open, or empty>"
codex_status=0
codex_outcome=ok
if [[ "$CODEX_AVAILABLE" == "true" ]]; then
  [[ -z "$PROGRESS_LOG" ]] || { printf '%s\n' "== codex review started"; } 2>/dev/null >>"$PROGRESS_LOG" || true
  CODEX_OUT=$(bash "$SKILL_DIR/scripts/codex-review.sh" "${CODEX_MODE}" "${BASE_BRANCH}" "${CODEX_COMPANION_PATH}") || codex_status=$?
  printf '%s\n' "$CODEX_OUT"
else
  codex_outcome=unavailable
  echo '{"codex_review":"unavailable"}' >&2   # not run — distinct from a run that returned no findings
fi
if [ "$codex_status" -eq 75 ]; then
  codex_outcome=locked
  echo '{"codex_review":"locked"}' >&2      # another cycle holds the workspace slot — skipped, not failed
elif [ "$codex_status" -ne 0 ]; then
  codex_outcome="failed (exit $codex_status)"
  echo '{"codex_review":"failed"}' >&2
fi
[[ -z "$PROGRESS_LOG" ]] || { printf '%s\n' "== codex review finished: $codex_outcome" "${CODEX_OUT:-}"; } 2>/dev/null >>"$PROGRESS_LOG" || true
```

`codex_status` 75 is the workspace lock held by another cycle: skipped, not failed.
`unavailable` (either source) means preflight found no such CLI: the block never ran a review.
`codex-review.sh` and `agy-review.sh` both persist a result; a run still going when the cycle
moves on is reclaimed before merge per `late-source-reclaim.md`.
