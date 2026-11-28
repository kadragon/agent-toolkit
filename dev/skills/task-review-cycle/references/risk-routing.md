# Review cycle — route by risk

Step 1's path decision, in two layers: a mechanical floor that no judgment call may lower, then a
judgment table that may only escalate above it. The reviewer count follows the path (*Panel*).

Evaluate on every run, including explicit path flags.

**Floor** — capture first, then read the captures:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
LOCAL_FLAG="<from authorization route: --no-hub or empty>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh" "$LOCAL_FLAG")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)
SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment|\.github/workflows|(^|/)(dev|prod|guard|mods)/hooks|(^|/)\.claude/hooks/|(^|/)\.githooks/' | head -1 || true)
BINARY_HIT=$(git diff "${BASE_BRANCH}...HEAD" --numstat | cut -f1,2 | grep -m1 -e '-' || true)
MODE_OR_RENAME=$(git diff "${BASE_BRANCH}...HEAD" --summary | grep -E '^ (mode change|rename) ' | head -1 || true)
SCRIPT_HIT=$(echo "$CHANGED_FILES" | grep -E '^(dev|prod|guard|mods)/.*\.(sh|py|ps1|cjs|ts|tsx)$' | head -1 || true)
# a linked worktree (`../../task-next/references/cycle.md` → *Worktree cycle*): the lite merge's `git checkout <base>` cannot run here
WORKTREE_HIT=$([[ "$(git rev-parse --path-format=absolute --git-dir)" != "$(git rev-parse --path-format=absolute --git-common-dir)" ]] && echo linked-worktree || true)
DISPATCH_RUN="<run.json beside the assigned result.json, or empty for a non-dispatched run>"
DISPATCH_REVIEW_HIT=""
if [[ -n "$DISPATCH_RUN" ]]; then
  if [[ -f "$DISPATCH_RUN" ]]; then
    DISPATCH_REVIEW_HIT=$(jq -er '
      (if has("review_policy") then .review_policy != "head-bound" else (.require_review_sources // false) != false end)
      | if . then "three-source-review" else "" end
    ' "$DISPATCH_RUN") || exit 1
  else
    DISPATCH_REVIEW_HIT="three-source-review"
  fi
fi
FLOOR_HIT="${SECURITY_HIT}${BINARY_HIT}${MODE_OR_RENAME}${SCRIPT_HIT}${WORKTREE_HIT}${DISPATCH_REVIEW_HIT}"
```

`FLOOR_HIT` non-empty means some row below forces hub. A lite route re-runs this block after
Step 5 commits a Step 4 fix (SKILL.md Step 6): a review fix can add the script the first pass never saw.

| Capture non-empty | Floor |
|-------------------|-------|
| `SECURITY_HIT`, `BINARY_HIT`, or `MODE_OR_RENAME` | **hub** with required CI; `--lite` cannot bypass, and judgment cannot route it lite |
| `SECURITY_HIT` | also `EFFORT="high"` in Step 2 |
| `SCRIPT_HIT` | **hub** with required CI; `--lite` cannot bypass |
| `WORKTREE_HIT` | **hub**; `--lite` cannot bypass — the lite merge checks out the base, which the main worktree holds |
| `DISPATCH_REVIEW_HIT` | **hub** with required CI when Git authority permits it, including a resumed lite review |

An assigned result without a receipt keeps the three-source default. Local-only authority
still stops before merge.

A shipped script forces hub so the panel reviews it: quoting, shell-expansion and interpreter-shim
defects are where the non-Claude engines earn their slot.

**Judgment** — escalate above the floor, never below it. Inspect the diff for execution rules,
deletion, permissions, deployment, state transitions, security, and how well the changed behavior
can be checked. Markdown can change executable agent behavior. Line count is a secondary signal;
it chooses neither a route nor a reviewer count alone.

| Condition | Path/review |
|-----------|-------------|
| Required remote checks, or uncertain risk | **hub** with required CI |
| Low-risk, readily verified change, every floor capture empty, no panel source running, and repo policy permits bypassing remote CI | **lite** eligible, regardless of prose length |
| Execution/deletion rules or scripts with material behavioral risk | **hub** |
| Large but mechanical/documentary diff | Judge review surface; size alone picks no route |

`--no-hub` remains local-only and stops before merge; report required remote checks as pending.
Unknown risk defaults to hub. Dispatched Codex task cycles use the hub panel unless `--no-hub`
keeps the cycle local.

**Panel** — the agy + Codex sources run by default on every hub route and on `--no-hub` (PR #277);
announce panel on/off with the route. A route judged lite runs one reviewer only (*Lite
reviewer* below): lite skips `ci-wait.sh`, so a panel there would still be `.pending` at the
pre-merge reclaim. An explicit `--panel` therefore forces hub, even on a diff whose captures are
all empty — except under `--no-hub`, which always wins, stays local, and runs the reclaim once at
its stop point. An engine preflight reports unavailable is skipped, not waited for.

**Lite reviewer** — lite runs one reviewer: the engine that did **not** drive this cycle, so the
diff is never graded by the model that wrote it (model inversion: each model family misses
different defect classes, and a same-model review shares the author's blind spots).

| Orchestrator | Lite reviewer | Fallback when it fails |
|---|---|---|
| Claude Code | Codex — the codex block from `review-sources.md`; a low-risk diff spends no Claude tokens on review (user-approved trade, 2026-10-05) | SKILL.md Step 2's Claude reviewer block |
| Codex | SKILL.md Step 2's Claude reviewer block (user-approved, 2026-11-12) | the codex block, disclosed as a same-engine review |

Run it in the **foreground** with Bash `timeout: 600000`: lite has no `ci-wait.sh` runway, so
the findings must land before Step 3, and a background task would hang the cycle on a lost
completion notification (SKILL.md Step 2). The codex block always exits 0, so read its outcome
from the output, not the exit status: a `{"codex_review":"failed"}`, `"locked"`, or
`"unavailable"` marker, no review text, or the 600s timeout is a failure; so is the Claude
reviewer's sentinel or timeout. Record `Reviewers Skipped: <reason>` and run the fallback; both
failed → review inline (SKILL.md Step 2). A timeout kills the foreground run, leaving no sidecar
result, so lite has no pre-merge reclaim.

The Claude reviewer grades the Sprint Contract itself. Codex reviews the diff only and takes no
contract, so when Codex is the lite reviewer the orchestrator grades each acceptance criterion
inline against the recorded evidence and reports each unmet one as a `contract` finding.
Leave execution-only criteria pending until their own checks run. Use the same inline re-grade
for focused contract confirmation and disclose it as self-grading
(SKILL.md Step 2).
