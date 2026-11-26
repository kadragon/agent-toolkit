# Panel Review Sources

The non-Claude engines (agy, Codex).

## Data-sharing policy

Before selecting a primary, panel, or fallback reviewer, check the repository policy and user
authorization for sharing source, diffs, contracts and any root `REVIEW.md` the engine can read.
Codex and agy receive guidance from the committed root file; Claude's local skill can read its
working copy. If that working copy is outside the approved scope, exclude that Claude run. Set each block's
`*_ALLOWED` only from that decision. Record exclusions without probing prohibited engines.
Select an allowed independent reviewer for any gate that requires one. If none can satisfy
the gate, stop before merge. Keep all required CI and validation checks. A rejected transfer
must not be retried through another tool.

## Advisory comments pass

After the primary review returns, run `claude-review.sh <base> --comments` as a separate read-only
pass using the same data-sharing policy as Step 2 and a foreground timeout at most 600 seconds.
If Claude is excluded, unavailable, times out or returns a sentinel, record the reason and apply
`comment-rules.md` inline when possible. Tag both forms `comments`. The pass cannot request changes
or trigger a blocking re-review. Cleanup decisions follow `comment-rules.md` → *Applying*.
Measure their dispositions before changing where the pass runs. The separate pass follows
https://claude.dev/blog/solving-code-review-at-anthropic/ (2026-10-15).

## Panel source launch

Lite reuses the codex block below, run in the foreground, whenever `risk-routing.md` → *Lite reviewer* selects it — as the reviewer or as the fallback (`risk-routing.md` → *Lite
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
AGY_ALLOWED="<true only when the policy permits agy>"
[[ "$AGY_ALLOWED" == true ]] || { echo '{"agy_review":"policy-excluded"}' >&2; exit 0; }
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
AGY_AVAILABLE=$(jq -r '.agy_available' <<<"$PREFLIGHT")
if [[ "$AGY_AVAILABLE" == "true" ]]; then
  bash "$SKILL_DIR/scripts/agy-review.sh" "${BASE_BRANCH}" || echo '{"agy_review":"failed"}' >&2
else
  echo '{"agy_review":"unavailable"}' >&2   # not run — distinct from a run that returned no findings
fi
```

```bash
CODEX_ALLOWED="<true only when the policy permits Codex>"
[[ "$CODEX_ALLOWED" == true ]] || { echo '{"codex_review":"policy-excluded"}' >&2; exit 0; }
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
CODEX_AVAILABLE=$(jq -r '.codex_available' <<<"$PREFLIGHT")
CODEX_MODE=$(jq -r '.codex_mode' <<<"$PREFLIGHT")
CODEX_COMPANION_PATH=$(jq -r '.codex_companion_path' <<<"$PREFLIGHT")
codex_status=0
if [[ "$CODEX_AVAILABLE" == "true" ]]; then
  bash "$SKILL_DIR/scripts/codex-review.sh" "${CODEX_MODE}" "${BASE_BRANCH}" "${CODEX_COMPANION_PATH}" || codex_status=$?
else
  echo '{"codex_review":"unavailable"}' >&2   # not run — distinct from a run that returned no findings
fi
if [ "$codex_status" -eq 75 ]; then
  echo '{"codex_review":"locked"}' >&2      # another cycle holds the workspace slot — skipped, not failed
elif [ "$codex_status" -ne 0 ]; then
  echo '{"codex_review":"failed"}' >&2
fi
```

`codex_status` 75 is the workspace lock held by another cycle: skipped, not failed.
`unavailable` (either source) means preflight found no such CLI: the block never ran a review.
`codex-review.sh` and `agy-review.sh` both persist a result; a run still going when the cycle
moves on is reclaimed before merge per `late-source-reclaim.md`.
