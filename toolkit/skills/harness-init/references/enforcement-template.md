# Enforcement Chain Template

Documentation alone does not prevent violations. Build a multi-layer enforcement chain so golden principles are mechanically guaranteed, not just documented.

## Defense in Depth

```
Agent edits a file
  -> PostToolUse hook warns immediately        (Layer 1: Real-time)
  -> Pre-commit blocks the commit if unfixed   (Layer 2: Pre-commit)
  -> CI blocks the merge                       (Layer 3: CI gate)
  -> PR reviewer confirms via checklist        (Layer 4: PR template)
```

Not every project needs all 4 layers. Match enforcement depth to team size and risk tolerance.

## Layer 1: Real-time Hooks (`.claude/settings.json`)

Create `.claude/settings.json` with hooks that fire during agent editing:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": "bash .claude/hooks/pre-edit-guard.sh"}]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": "bash .claude/hooks/post-edit-lint.sh"}]
      }
    ]
  }
}
```

Design hooks that catch golden principle violations **at edit time**, before commit. The hook's error message should tell the agent exactly what is wrong and how to fix it.

### Hook Script Pattern

```bash
#!/bin/bash
# .claude/hooks/post-edit-lint.sh
# Runs lint on the file that was just edited

FILE="$CLAUDE_TOOL_ARG_FILE_PATH"
[[ -z "$FILE" ]] && exit 0

# ADAPT: Replace with project's lint command targeting the specific file
# npm run lint -- "$FILE"
# ruff check "$FILE"
# cargo clippy -- "$FILE"

# On failure, output includes:
#   1. What rule was violated
#   2. How to fix it
#   3. Which doc explains the rule
```

### Bash Output Truncation (optional, token-economy)

Not a golden-principle hook — a token-economy hook. Large Bash outputs (full test suites, verbose builds, `git log` with hundreds of commits) flood the agent's context with low-signal text. The agent rarely needs more than the first/last N lines.

Add this PostToolUse hook on `Bash` to auto-truncate oversized outputs before they enter the context:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [{"type": "command", "command": "bash .claude/hooks/bash-output-cap.sh"}]
      }
    ]
  }
}
```

```bash
#!/usr/bin/env bash
# .claude/hooks/bash-output-cap.sh
# Read PostToolUse payload from stdin, cap tool_response output past a line threshold.
# Emits the (possibly truncated) payload back on stdout for the agent to consume.

set -euo pipefail

MAX_LINES="${BASH_OUTPUT_MAX_LINES:-200}"
HEAD_KEEP=50
TAIL_KEEP=100

payload=$(cat)
output=$(jq -r '.tool_response // empty' <<<"$payload")
[[ -z "$output" ]] && { printf '%s' "$payload"; exit 0; }

line_count=$(printf '%s' "$output" | wc -l | tr -d ' ')
[[ "$line_count" -le "$MAX_LINES" ]] && { printf '%s' "$payload"; exit 0; }

head_part=$(printf '%s' "$output" | head -n "$HEAD_KEEP")
tail_part=$(printf '%s' "$output" | tail -n "$TAIL_KEEP")
omitted=$((line_count - HEAD_KEEP - TAIL_KEEP))

truncated="${head_part}
… [truncated ${omitted} lines — re-run with a narrower command if the middle matters] …
${tail_part}"

jq --arg t "$truncated" '.tool_response = $t' <<<"$payload"
```

**Tune per repo.** The defaults (200-line trigger, keep first 50 + last 100) fit most test/build output — passing tests summarize at the end, failing tests scream early. If you often need middle-of-output context, raise `BASH_OUTPUT_MAX_LINES` via env or skip this hook entirely.

**When to skip this hook:**
- Repos where Bash outputs are already small (pure library with `cargo test` returning <50 lines)
- Diagnostic-heavy work where the agent genuinely needs full logs — keep it off and rely on manual `| tail` / `| head` discipline

### Read Deduplication (optional, advisory)

A 2026 analysis of 132 sessions across 20 projects found **71% of all file reads were files the agent had already opened in the same session** — some files re-read 3-4 times unchanged. One documented case dropped a project's usage from 2.5M to 425K tokens after installing six dedup-oriented hooks.

**Design choice: advisory, not blocking.** A hard-block dedup hook creates more problems than it solves (legitimate re-reads after Edit, test failures that warrant re-inspection, etc.). Instead, log re-reads with a one-line stderr warning the agent sees in the tool result. The agent usually course-corrects without the interruption of a hard block.

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [{"type": "command", "command": "bash .claude/hooks/read-dedup.sh"}]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{"type": "command", "command": "bash .claude/hooks/read-dedup-invalidate.sh"}]
      }
    ]
  }
}
```

```bash
#!/usr/bin/env bash
# .claude/hooks/read-dedup.sh
# Warn (do not block) when agent re-reads a file already read in this session.

set -euo pipefail

payload=$(cat)
file=$(jq -r '.tool_input.file_path // empty' <<<"$payload")
session=$(jq -r '.session_id // "default"' <<<"$payload")
[[ -z "$file" ]] && exit 0

cache="/tmp/claude-reads-${session}.txt"
touch "$cache"

if grep -Fxq -- "$file" "$cache"; then
  echo "read-dedup: $file was already read in this session — consider Grep/Edit directly instead of re-reading." >&2
fi
printf '%s\n' "$file" >> "$cache"
exit 0
```

```bash
#!/usr/bin/env bash
# .claude/hooks/read-dedup-invalidate.sh
# Clear the dedup cache entry after Edit/Write so the next Read returns fresh.

set -euo pipefail

payload=$(cat)
file=$(jq -r '.tool_input.file_path // empty' <<<"$payload")
session=$(jq -r '.session_id // "default"' <<<"$payload")
[[ -z "$file" ]] && exit 0

cache="/tmp/claude-reads-${session}.txt"
[[ -f "$cache" ]] || exit 0

grep -Fxv -- "$file" "$cache" > "${cache}.tmp" || true
mv "${cache}.tmp" "$cache"
exit 0
```

**Tradeoffs**:
- Advisory-only means ~50% of the benefit of a hard-block version — the agent still sometimes re-reads despite the warning
- Session-scoped cache lives under `/tmp`; may need cron cleanup
- Multi-session parallel work (e.g., two terminals in same repo) can share cache file — use `$CLAUDE_SESSION_ID` if available

**Skip this hook if**: repo's agents rarely re-read (small codebase), or work pattern involves frequent legitimate re-reads (iterative debugging with the same file).

**LSP-first navigation** is a related pattern — enforce `LSP` tool use over `Grep` for symbol search via a similar advisory hook. Reports of ~80% Grep-token savings on large codebases. See [`nesaminua/claude-code-lsp-enforcement-kit`](https://github.com/nesaminua/claude-code-lsp-enforcement-kit) for a reference implementation; only worthwhile on projects with a mature LSP server.

### Performance: Use `[[ =~ ]]` Instead of `grep` in Hooks

Hooks fire on every edit. If a hook reads a file line-by-line and calls `echo "$line" | grep` per line, it forks a subprocess per check. At scale (e.g., 35 Java files × 15 checks/line), this means thousands of forks and becomes the dominant bottleneck.

**`[[ =~ ]]` is a bash builtin (since bash 3.0) — no fork, no subprocess.** Replace all `echo | grep` patterns with `[[ =~ ]]` in hook scripts.

```bash
# BAD: forks a subprocess per line — O(lines × checks) forks
while IFS= read -r line; do
    if echo "$line" | grep -qP 'TODO|FIXME|HACK'; then
        violations+=("$line")
    fi
done < "$FILE"

# GOOD: bash builtin, zero forks — same O(lines × checks) comparisons but in-process
while IFS= read -r line; do
    if [[ "$line" =~ TODO|FIXME|HACK ]]; then
        violations+=("$line")
    fi
done < "$FILE"
```

**Pattern migration reference:**

| grep pattern | `[[ =~ ]]` equivalent | Notes |
|---|---|---|
| `echo "$x" \| grep -q 'pat'` | `[[ "$x" =~ pat ]]` | No quoting the regex |
| `grep -qP '^\d+\.'` | `[[ "$x" =~ ^[0-9]+\. ]]` | ERE, not PCRE — use `[0-9]` for `\d` |
| `grep -oP '(pat)' \| ...` | `[[ "$x" =~ (pat) ]]; echo "${BASH_REMATCH[1]}"` | Captures via `BASH_REMATCH` |
| `grep -c 'pat' file` | Loop + counter: `[[ "$line" =~ pat ]] && ((count++))` | Single pass through file |
| `cmd \| grep -v '^$'` | `[[ -n "$line" ]]` in a while-read loop | Filter empty lines |

**When grep is still fine:** Single invocations on whole files (`grep -q 'pattern' file.txt`) fork once — no performance concern. The problem is grep *inside loops*.

## Agent Teams Quality Gates (Layer 1 extension)

If Agent Teams is enabled (see `references/agent-teams-onboarding.md`), three team-lifecycle hooks give the harness mechanical control points that do not exist for single-session work. Non-zero exit with code `2` sends feedback back to the agent and blocks the event.

```json
{
  "hooks": {
    "TaskCreated": [
      {"hooks": [{"type": "command", "command": "bash .claude/hooks/task-created-contract.sh"}]}
    ],
    "TaskCompleted": [
      {"hooks": [{"type": "command", "command": "bash .claude/hooks/task-completed-criteria.sh"}]}
    ],
    "TeammateIdle": [
      {"hooks": [{"type": "command", "command": "bash .claude/hooks/teammate-idle-nudge.sh"}]}
    ]
  }
}
```

### `task-created-contract.sh` — enforce Spawn Prompt Contract

Reject any task whose prompt is missing any of the 4 contract fields (Objective, Output format, Tools to use, Boundaries). This turns `references/delegation-template.md` → "Spawn Prompt Contract" into a mechanical check.

```bash
#!/usr/bin/env bash
set -euo pipefail
payload=$(cat)
prompt=$(jq -r '.task.prompt // empty' <<<"$payload")

missing=()
for field in "Objective:" "Output format:" "Tools to use:" "Boundaries:"; do
    [[ "$prompt" =~ $field ]] || missing+=("$field")
done

if (( ${#missing[@]} > 0 )); then
    echo "Spawn Prompt Contract violated. Missing fields: ${missing[*]}" >&2
    echo "See references/delegation-template.md → Spawn Prompt Contract. Re-spawn with all 4 fields." >&2
    exit 2
fi
exit 0
```

### `task-completed-criteria.sh` — enforce eval-criteria

Reject TaskCompleted if the task belongs to a Sprint Contract and acceptance criteria are not all checked off in `tasks.md`. Cheap mechanical gate against the "declared done, actually partial" failure mode.

```bash
#!/usr/bin/env bash
set -euo pipefail
payload=$(cat)
task_id=$(jq -r '.task.id // empty' <<<"$payload")
[[ -z "$task_id" ]] && exit 0
[[ -f "tasks.md" ]] || exit 0

# ADAPT: match tasks.md schema for this project.
# Fail if any "- [ ]" remains under the matching task section.
if awk -v id="$task_id" '
    $0 ~ "^# " && $0 ~ id { in_section=1; next }
    in_section && /^# / { in_section=0 }
    in_section && /^- \[ \]/ { found=1 }
    END { exit !found }
' tasks.md; then
    echo "TaskCompleted blocked: tasks.md still has unchecked acceptance criteria for $task_id" >&2
    exit 2
fi
exit 0
```

### `teammate-idle-nudge.sh` — prevent premature stop

When a teammate goes idle with open tasks in its assigned scope, send a nudge instead of letting it stop. Targets the "context anxiety" pattern (see `references/workflows-template.md`).

```bash
#!/usr/bin/env bash
set -euo pipefail
payload=$(cat)
teammate=$(jq -r '.teammate.name // empty' <<<"$payload")
open_count=$(jq -r '[.tasks[] | select(.owner == "'"$teammate"'" and .status != "completed")] | length' <<<"$payload")

if (( open_count > 0 )); then
    echo "$teammate going idle with $open_count open task(s). Continue or explicitly handoff via SendMessage." >&2
    exit 2
fi
exit 0
```

**Skip these hooks if Agent Teams is not enabled** — the events never fire and the scripts are inert, but keep the `.claude/settings.json` clean.

## Layer 2: Pre-commit Checks

Wire golden principle checks into git pre-commit hooks or the project's existing pre-commit framework.

### Using pre-commit framework (Python ecosystem)

```yaml
# .pre-commit-config.yaml
repos:
  - repo: local
    hooks:
      - id: golden-principles
        name: Golden Principle Check
        entry: bash tools/check-principles.sh
        language: system
        pass_filenames: true
```

### Using Husky (Node ecosystem)

```bash
# .husky/pre-commit
npx lint-staged
```

```json
// package.json
{
  "lint-staged": {
    "*.{ts,tsx}": ["eslint --fix", "prettier --write"],
    "*.sql": ["bash tools/check-sql-safety.sh"]
  }
}
```

### Plain git hook

```bash
# .git/hooks/pre-commit
#!/bin/bash
bash tools/check-principles.sh $(git diff --cached --name-only)
```

## Layer 3: CI Gate

Add golden principle enforcement to the CI pipeline.

### GitHub Actions example

```yaml
# .github/workflows/principles.yml
name: Golden Principles
on: [pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: bash tools/check-principles.sh
```

### GitLab CI example

```yaml
golden-principles:
  stage: test
  script:
    - bash tools/check-principles.sh
  rules:
    - if: $CI_MERGE_REQUEST_ID
```

## Layer 4: PR Template (optional)

Create a PR template with a checklist derived from golden principles:

```markdown
<!-- .github/PULL_REQUEST_TEMPLATE.md -->
## Checklist

- [ ] Golden principle 1: {description}
- [ ] Golden principle 2: {description}
- [ ] Golden principle 3: {description}
- [ ] Tests pass locally
- [ ] Lint passes
- [ ] Docs updated if applicable
```

## Choosing Layers

| Team size | Recommended layers |
|-----------|-------------------|
| Solo dev | Layer 1 (hooks) + Layer 2 (pre-commit) |
| Small team (2-5) | Layer 1 + Layer 2 + Layer 3 (CI) |
| Large team (5+) | All 4 layers |

| Risk level | Recommended layers |
|------------|-------------------|
| Low (docs site, internal tool) | Layer 1 + Layer 2 |
| Medium (SaaS, API service) | Layer 1 + Layer 2 + Layer 3 |
| High (fintech, healthcare, auth) | All 4 layers |
