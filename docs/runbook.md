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
claude plugin install ./dev
claude plugin install ./prod
```

### Codex Plugin Install

```bash
codex plugin add dev@kadragon
codex plugin add prod@kadragon
```

## Validate

| Command | Purpose |
|---------|---------|
| `bash dev/skills/harness-init/scripts/validate-harness.sh` | Full harness structural validation + maturity level |
| `bash tools/sweep.sh` | Garbage collection: lint scan, doc drift, principle violations |

## Release Workflow

1. Make changes to skill/agent files
2. Bump versions: `bash scripts/bump-version.sh <plugin> <major|minor|patch>` (see `docs/conventions.md` — semver rules)
3. Run harness validate
4. Commit + push + PR via `dev:task-review`
5. Merge triggers marketplace update

### Version bump check

```bash
# Check which plugin.json versions are on this branch vs main
git diff main -- dev/.claude-plugin/plugin.json prod/.claude-plugin/plugin.json
```

## Common Failures

### CI fails: "plugin.json version unchanged"

**Symptom:** `harness-check.yml` exits 1 with "version not bumped"
**Cause:** Modified files in `dev/` or `prod/` but didn't bump `plugin.json`
**Fix:** `bash scripts/bump-version.sh <plugin> patch` (or minor/major per semver table in `docs/conventions.md`)

### plugin.json version conflict after pulling remote changes

**Symptom:** `git stash pop` (or rebase) conflicts on the `"version"` line in `plugin.json` — local had an uncommitted bump, remote advanced the same file further.
**Fix:** resolve to remote's version, then re-run `bash scripts/bump-version.sh <plugin> <patch|minor|major>` from that new base — don't hand-pick a version number.

### Skill not auto-invoking

**Symptom:** Skill not auto-invoked on a matching prompt
**Cause:** Auto-invocation is description-driven (no router in this repo) — the `description:` triggers are too vague, collide with a neighbor skill, or lack the user's phrasing
**Fix:** Sharpen the skill's `description:` — add the concrete trigger phrases and explicit `NOT for …` exclusions that distinguish it from neighbors. See `docs/eval-criteria.md` Trigger Accuracy.

### `validate-harness.sh` reports FAIL

**Symptom:** `FAIL AGENTS.md missing` or `FAIL CLAUDE.md is not @AGENTS.md`
**Cause:** File missing or CLAUDE.md has content other than `@AGENTS.md`
**Fix:** Create missing file or restore `CLAUDE.md` to single line `@AGENTS.md`

### `.agents/skills` symlink broken

**Symptom:** Skill lookup fails; `validate-harness.sh` reports symlink warning
**Fix:**
```bash
bash dev/skills/harness-init/scripts/symlink-guard.sh
```

## Harness Scripts

| Script | Purpose |
|--------|---------|
| `scripts/bump-version.sh` | Bump plugin + skill versions atomically across both platforms |
| `tools/sweep.sh` | Garbage collection sweep |
| Validate: see above | Structural validation |

## Scratchpad Convention

Intermediate artifacts live in the session scratchpad directory (path given in the system prompt).
Naming: `{phase:02d}_{agent}_{artifact}.{ext}`

Ephemeral — gone at session end, no cross-session resume.

Separate mechanism: delegation-gate evidence files live in `.claude/tmp/` (gitignored, session_id-stamped — see `references/enforcement-template.md`). Do not conflate the two.

## Sweep Trigger Policy

**Manual** (default): run `bash tools/sweep.sh` between features or before releases.
No SessionStart hook — sweep is too heavy for every session on this repo.
