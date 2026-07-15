# Conventions

## Naming

| Element | Pattern | Example |
|---------|---------|---------|
| Skill directories | `kebab-case` | `harness-init`, `dev-review-cycle` |
| Shell scripts | `kebab-case.sh` | `trigger-router.sh`, `sweep.sh` |
| Python scripts | `snake_case.py` | `scan_transcripts.py` |
| Agent role files | `kebab-case.md` | `qa-verifier.md`, `skill-evaluator.md` |
| Shell variables | `SCREAMING_SNAKE` | `ROUTES_FILE`, `MAX_LINES` |

## Git Conventions

Commit types (mandatory prefix):

| Type | When |
|------|------|
| `[FEAT]` | New behavior / skill / agent |
| `[FIX]` | Bug fix — requires reproduction step before fix |
| `[REFACTOR]` | Structure only, no behavior change |
| `[DOCS]` | docs/ or README only |
| `[CONSTRAINT]` | No production code changed; structural guards only (lint rule, CI check, schema) |
| `[HARNESS]` | Skill/hook/agent instruction changes; no production code |
| `[TEST]` | Test-only (new coverage, test refactor) |
| `[PLAN]` | backlog.md / tasks.md changes |

Never commit directly to `main` — branch first (`git checkout -b <type>/<slug>`).

## Shell Script Conventions

### Capture-Before-Use (mandatory)

Always capture command output into a variable before referencing it. Show all three steps adjacently:

```bash
# CORRECT — capture → validate → use
result=$(some_command)
[[ -z "$result" ]] && exit 0
echo "$result"

# WRONG — use before capture (agents skip steps when separated)
echo "$result"
result=$(some_command)
```

Every shell pattern in skill docs that references `$var` MUST show the `var=$(cmd)` capture step first. Failure mode: agents read the pattern, skip capture, reference unset variable.

### Hook Script Exit Policy

- Hooks (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`): always `exit 0` — never block on unexpected input
- Validation scripts (`validate-harness.sh`, CI checks): `exit 1` on failure, `0` on success
- Use `set -u` (unbound var error); avoid `set -e` in hook scripts (one bad regex should not kill the hook)
- Shell and Python scripts shipped in plugins must use LF line endings. `.gitattributes` enforces this, and CI rejects CRLF in `*.sh`, `*.bash`, and `*.py`.

### Plugin Hook Root Variables

- In `hooks.json` command fields, use `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}` for shared Claude/Codex hooks. This guarantee is limited to the plugin hook command environment.
- Hook script bodies derive adjacent assets from `BASH_SOURCE[0]` (shell) or `__file__` (Python), so they remain runnable outside the hook launcher.
- Shared skills resolve bundled files from the absolute location of the `SKILL.md` loaded for that turn. Skill-executed shells must not assume plugin hook root variables are present.

## Plugin Version Bump Rules

`dev-tools/.claude-plugin/plugin.json`, `productivity/.claude-plugin/plugin.json`, and `team-standards/.claude-plugin/plugin.json` are independent semver manifests. Bump only the plugin that changed.

| Change type | Bump |
|-------------|------|
| Skill or agent added | minor: `x.Y.z → x.(Y+1).0` |
| Skill or agent modified | patch: `x.y.Z → x.y.(Z+1)` |
| Skill or agent removed or renamed | major: `X.y.z → (X+1).0.0` |

Rule: if any file under `dev-tools/` changed in the diff → `dev-tools/plugin.json` version must differ from `main`. CI enforces this (`harness-check.yml`).

Use `scripts/bump-version.sh` to update all version fields atomically (both platform manifests + optional skill):

```bash
# patch bump for dev-tools
bash scripts/bump-version.sh dev-tools patch

# minor bump + skill version
bash scripts/bump-version.sh dev-tools minor --skill harness-curator patch

# bump both plugins
bash scripts/bump-version.sh all patch
```

Files updated per plugin: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, and optionally `skills/{name}/SKILL.md`.

## Skill Doc Rules

When writing shell patterns in `SKILL.md` that use variables, always show:

1. Capture: `var=$(cmd)`
2. Check: `[[ -n "$var" ]] || handle_empty`
3. Use: `echo "$var"` or `some_tool "$var"`

Never show step 3 without steps 1–2 visible in the same code block.
