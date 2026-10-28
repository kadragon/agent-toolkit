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
SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment|\.github/workflows|(^|/)(dev|prod|mods)/hooks|(^|/)\.claude/hooks/|(^|/)\.githooks/' | head -1 || true)
BINARY_HIT=$(git diff "${BASE_BRANCH}...HEAD" --numstat | cut -f1,2 | grep -m1 -e '-' || true)
MODE_OR_RENAME=$(git diff "${BASE_BRANCH}...HEAD" --summary | grep -E '^ (mode change|rename) ' | head -1 || true)
SCRIPT_HIT=$(echo "$CHANGED_FILES" | grep -E '^(dev|prod|mods)/.*\.(sh|py|ps1|cjs|ts|tsx)$' | head -1 || true)
FLOOR_HIT="${SECURITY_HIT}${BINARY_HIT}${MODE_OR_RENAME}${SCRIPT_HIT}"
```

`FLOOR_HIT` non-empty means some row below forces hub. A lite route re-runs this block after
Step 5 commits a Step 4 fix (SKILL.md Step 6): a review fix can add the script the first pass never saw.

| Capture non-empty | Floor |
|-------------------|-------|
| `SECURITY_HIT`, `BINARY_HIT`, or `MODE_OR_RENAME` | **hub** with required CI; `--lite` cannot bypass, and judgment cannot route it lite |
| `SECURITY_HIT` | also `EFFORT="high"` in Step 2 |
| `SCRIPT_HIT` | **hub** with required CI; `--lite` cannot bypass |

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
Unknown risk defaults to hub.

**Panel** — the agy + Codex sources run by default on every hub route and on `--no-hub` (PR #277);
announce panel on/off with the route. A route judged lite runs one reviewer only, Codex (*Lite
reviewer* below): lite skips `ci-wait.sh`, so a panel there would still be `.pending` at the
pre-merge reclaim. An explicit `--panel` therefore forces hub, even on a diff whose captures are
all empty — except under `--no-hub`, which always wins, stays local, and runs the reclaim once at
its stop point. An engine preflight reports unavailable is skipped, not waited for.

**Lite reviewer** — lite runs Codex as its one reviewer instead of the Claude reviewer, so a
low-risk diff spends no Claude tokens on review (user-approved trade, 2026-10-05). Run the codex
block from `review-sources.md` in the **foreground** with Bash `timeout: 600000`, the same shape as
the Claude reviewer: lite has no `ci-wait.sh` runway, so the findings must land before Step 3, and
a background task would hang the cycle on a lost completion notification (SKILL.md Step 2).
That block always exits 0,
so read its outcome from the output, not the exit status: a `{"codex_review":"failed"}`,
`"locked"`, or `"unavailable"` marker, no review text, or the 600s timeout → record `Reviewers
Skipped: <reason>` and run SKILL.md Step 2's Claude reviewer block instead. A timeout kills the
foreground run, leaving no sidecar result, so lite has no pre-merge reclaim.

Codex reviews the diff only and takes no Sprint Contract, so on lite the orchestrator grades each
acceptance criterion inline against the recorded evidence and reports each unmet one as a
`contract` finding. Step 4's "re-run the reviewer once" after a fixed `contract` finding is the
same inline re-grade; disclose it as self-grading (SKILL.md Step 2).
