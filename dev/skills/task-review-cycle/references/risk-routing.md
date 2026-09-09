# Review cycle — route by risk

Step 1's path and reviewer-count decision, in two layers: a mechanical floor that no judgment
call may lower, then a judgment table that may only escalate above it.

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
| `SCRIPT_HIT` | **hub** with required CI, and `--panel` is on; `--lite` cannot bypass either |

The floor forces hub for the same reason it turns the panel on. `late-source-reclaim.md`'s
pre-merge reclaim needs runway, and the only free runway is `ci-wait.sh`, which lite skips: a
lite panel run reaches the reclaim with the codex source still `.pending` every time, so its
findings land strictly post-merge, where they are reported and never applied. The argument is about
the panel, not the extension: an explicit `--panel` on a diff whose captures are all empty routes
hub for the same reason.

A shipped script is where the non-Claude engines earn their slot — quoting, shell expansion and
interpreter-shim defects a prose reviewer has no reason to look for (PR #267). Matching on
extension means a `.md`/`.json`/`.yaml` edit cannot pull the panel in on its own.

**Judgment** — escalate above the floor, never below it. Inspect the diff for execution rules,
deletion, permissions, deployment, state transitions, security, and how well the changed behavior
can be checked. Markdown can change executable agent behavior. Line count is a secondary signal;
it chooses neither a route nor a reviewer count alone.

| Condition | Path/review |
|-----------|-------------|
| Required remote checks, or uncertain risk | **hub** with required CI |
| Low-risk, readily verified change, every floor capture empty, no panel source running, and repo policy permits bypassing remote CI | **lite** eligible, regardless of prose length |
| Execution/deletion rules or scripts with material behavioral risk | **hub**; add panel when distinct engines can investigate that risk |
| Large but mechanical/documentary diff | Judge review surface; size alone adds no panel |

`--no-hub` remains local-only and stops before merge; report required remote checks as pending.
An explicit `--panel` requests extra sources. Otherwise state the specific risk each added source
will investigate; if there is none, use the single reviewer. Unknown risk defaults to hub.
