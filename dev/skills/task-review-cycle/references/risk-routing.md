# Review cycle — route by risk

Step 1's path decision, in two layers: a mechanical floor that no judgment call may lower, then a
judgment table that may only escalate above it. The reviewer count follows the path (*Panel*).

Evaluate on every run, including explicit path flags.

**Floor** — capture first, then read the captures:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
PREFLIGHT=$(bash "$SKILL_DIR/scripts/preflight.sh")
BASE_BRANCH=$(jq -r '.base_branch' <<<"$PREFLIGHT")
CHANGED_FILES=$(git diff "${BASE_BRANCH}...HEAD" --name-only)
SECURITY_HIT=$(echo "$CHANGED_FILES" | grep -Ei 'auth|crypto|secret|permission|network|\.env$|/env[./]|/env$|environment|\.github/workflows' | head -1 || true)
BINARY_HIT=$(git diff "${BASE_BRANCH}...HEAD" --numstat | cut -f1,2 | grep -m1 -e '-' || true)
MODE_OR_RENAME=$(git diff "${BASE_BRANCH}...HEAD" --summary | grep -E '^ (mode change|rename) ' | head -1 || true)
SCRIPT_HIT=$(echo "$CHANGED_FILES" | grep -E '^(dev|prod)/.*\.(sh|py|ps1|cjs)$' | head -1 || true)
```

| Capture non-empty | Floor |
|-------------------|-------|
| `SECURITY_HIT`, `BINARY_HIT`, or `MODE_OR_RENAME` | **hub** with required CI; `--lite` cannot bypass, and judgment cannot route it lite |
| `SECURITY_HIT` | also `EFFORT="high"` in Step 2 |
| `SCRIPT_HIT` | **hub** with required CI; `--lite` cannot bypass |

A shipped script is where the non-Claude engines earn their slot — quoting, shell expansion and
interpreter-shim defects a prose reviewer has no reason to look for (PR #267). Forcing hub keeps
the panel on for every such diff.

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

**Panel** — the agy + Codex sources run by default on every hub route and on `--no-hub`. A route
judged lite runs the single reviewer only. The reason is runway: `late-source-reclaim.md`'s
pre-merge reclaim waits out `ci-wait.sh`, which lite skips, so a lite panel run reaches the
reclaim with the codex source still `.pending` every time, and its findings land post-merge,
reported and never applied. An explicit `--panel` therefore forces hub, even on a diff whose
captures are all empty — except under `--no-hub`, which always wins and stays local. `--no-hub`
has no merge, so it runs the codex reclaim once at its stop point instead. An engine that
preflight reports unavailable is skipped, not waited for.
