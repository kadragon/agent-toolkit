# Runbook

## Quick Start

### Prerequisites

- Claude Code CLI (`claude --version`)
- `gh` GitHub CLI (`gh auth login`)
- Python 3.x (for harness scripts)
- `jq` (for hook scripts)

### Plugin Install (local dev)

```bash
# Install plugins from local path
claude plugin install ./dev-tools
claude plugin install ./productivity
```

### Codex Plugin Install

```bash
codex plugin add dev-tools@kadragon
codex plugin add productivity@kadragon
```

## Validate

| Command | Purpose |
|---------|---------|
| `bash /Users/kadragon/.claude/plugins/cache/kadragon/dev-tools/3.0.6/skills/harness-init/scripts/validate-harness.sh` | Full harness structural validation + maturity level |
| `bash tools/sweep.sh` | Garbage collection: lint scan, doc drift, principle violations |
| `bash .claude/hooks/trigger-router.sh` | Test trigger routing (pipe JSON prompt) |

### Test trigger routing

```bash
# Capture prompt JSON, then test routing
PROMPT='{"prompt": "implement backlog item", "session_id": "test"}'
echo "$PROMPT" | bash .claude/hooks/trigger-router.sh
# Expected: "INSTRUCTION (auto-delegation router): Use Skill(...) ..."
```

## Release Workflow

1. Make changes to skill/agent files
2. Bump `plugin.json` version (see `docs/conventions.md` — semver rules)
3. Run harness validate
4. Commit + push + PR via `dev-tools:dev-review-cycle`
5. Merge triggers marketplace update

### Version bump check

```bash
# Check which plugin.json versions are on this branch vs main
git diff main -- dev-tools/.claude-plugin/plugin.json productivity/.claude-plugin/plugin.json
```

## Common Failures

### CI fails: "plugin.json version unchanged"

**Symptom:** `harness-check.yml` exits 1 with "version not bumped"
**Cause:** Modified files in `dev-tools/` or `productivity/` but didn't bump `plugin.json`
**Fix:** Run `docs/conventions.md` semver table to choose correct bump; edit `plugin.json` `version` field

### Trigger router not firing

**Symptom:** Skill not auto-invoked on matching prompt
**Cause:** Route missing from `.claude/trigger-routes.json` or pattern mismatch
**Fix:**
```bash
# Test each route
PROMPT='{"prompt": "your test phrase here", "session_id": "test"}'
echo "$PROMPT" | bash .claude/hooks/trigger-router.sh
```
Add/fix route in `.claude/trigger-routes.json`

### `validate-harness.sh` reports FAIL

**Symptom:** `FAIL AGENTS.md missing` or `FAIL CLAUDE.md is not @AGENTS.md`
**Cause:** File missing or CLAUDE.md has content other than `@AGENTS.md`
**Fix:** Create missing file or restore `CLAUDE.md` to single line `@AGENTS.md`

### `.agents/skills` symlink broken

**Symptom:** Skill lookup fails; `validate-harness.sh` reports symlink warning
**Fix:**
```bash
bash /Users/kadragon/.claude/plugins/cache/kadragon/dev-tools/3.0.6/skills/harness-init/scripts/symlink-guard.sh
```

## Harness Scripts

| Script | Purpose |
|--------|---------|
| `tools/sweep.sh` | Garbage collection sweep |
| Validate: see above | Structural validation |

## _workspace/ Convention

Intermediate artifacts live under `_workspace/` at repo root.
Naming: `{phase:02d}_{agent}_{artifact}.{ext}`

Preserve across sessions — enables partial re-run without full restart.
Remove only on explicit "reset" request.

## Sweep Trigger Policy

**Manual** (default): run `bash tools/sweep.sh` between features or before releases.
No SessionStart hook — sweep is too heavy for every session on this repo.
