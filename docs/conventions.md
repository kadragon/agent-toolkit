# Conventions

## Naming

| Element | Pattern | Example |
|---------|---------|---------|
| Skill directories | `kebab-case` | `harness-init`, `task-review` |
| Shell scripts | `kebab-case.sh` | `bump-version.sh`, `sweep.sh` |
| Python scripts | `snake_case.py` | `scan_transcripts.py` |
| Agent role files | `kebab-case.md` | `qa-verifier.md`, `skill-evaluator.md` |
| Shell variables | `SCREAMING_SNAKE` | `SKILL_DIR`, `MAX_LINES` |

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

### CHANGELOG Entries

`CHANGELOG.md` is an index, not a record. One line per completed cycle, inserted as the first
entry under `## Unreleased` (newest first):

```
- [done] <title> (<plugin> v<X.Y.Z>) (<date>)
- [done] <title> (<plugin> v<X.Y.Z>) (<date>) → <path/to/owning-doc>.md
```

**≤160 characters, at most one `docs/` link, no explanatory clauses** — no `—`/`;`-chained
descriptions, no file lists, no failure-mode narration. Reusable knowledge goes to the owning
`docs/*.md` (linked from the entry); the story of what changed already lives in `git log` and the
PR body. If the line alone doesn't identify the change, fix the title rather than append prose.

Canonical rule and rationale: *CHANGELOG Entry Contract* in the `dev:harness-init` skill's
`references/harness-invariants.md`.

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
- `find` feeding a `while read` loop needs `-type f`. A directory whose name matches the glob
  (`.claude/agents/bogus.md/`) makes the inner `read` fail; under `set -u` the loop variable is
  then unbound and the whole script aborts mid-run — before its summary ever prints.
- Shell and Python scripts shipped in plugins must use LF line endings. `.gitattributes` enforces this, and CI rejects CRLF in `*.sh`, `*.bash`, and `*.py`.
- Tracked `*.json` must be UTF-8 **without** BOM — strict parsers reject the leading `EF BB BF`, which silently breaks manifest loading. Windows PowerShell 5.1 `Out-File`/`Set-Content -Encoding utf8` writes one; edit JSON through the file tools or git bash instead. CI rejects any BOM-carrying JSON.

### Piping Large Variables (`pipefail` + SIGPIPE)

Under `set -euo pipefail`, never split a captured variable with an early-exiting reader:
`printf '%s' "$VAR" | head -n 1` works until `$VAR` passes the pipe buffer (~64 KB), then
`head` exits, `printf` dies of SIGPIPE, `pipefail` propagates 141, and `set -e` kills the
script — silently, and only on the large inputs the code was written to handle. Use
parameter expansion (`${VAR%%$'\n'*}`, `${VAR#*$'\n'}`) for string surgery; reserve pipes for
readers that consume all input (`tail`, `wc`, `jq`) or read from a file rather than a pipe.

### Plugin Hook Root Variables

- In `hooks.json` command fields, use `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}` for shared Claude/Codex hooks. This guarantee is limited to the plugin hook command environment.
- Hook script bodies derive adjacent assets from `BASH_SOURCE[0]` (shell) or `__file__` (Python), so they remain runnable outside the hook launcher.
- Shared skills resolve bundled files from the absolute location of the `SKILL.md` loaded for that turn. Skill-executed shells must not assume plugin hook root variables are present.

## Python Lint Rules

- `ruff.toml` at the repo root pins the ruleset the local `.git/hooks/pre-commit` gate enforces on staged `*/scripts/*.py`. Without a config, ruff activates its full rule set and the gate reports ~149 pre-existing violations, which forces `--no-verify`. Keep the repo at 0 violations so the gate stays usable.
- `target-version` is load-bearing, not cosmetic: ruff's parser is version-aware, so it also gates `E9` invalid-syntax. Setting it below the repo's real floor makes every commit fail.
- The pre-commit hook is untracked and per-machine, so CI carries the real gate: the `ruff` job in `.github/workflows/harness-check.yml` runs `ruff check --no-cache .` **repo-wide** with ruff pinned to `0.16.0`. Repo-wide is deliberate — it is what fails a `target-version` downgrade, which the hook's staged-files-only scope can miss. Bump the pin and the hook together.
- The Python floor is recorded twice and nothing in the toolchain reconciles the two: `ruff.toml`'s `target-version` drives ruff's parser, while `.python-version` (`3.12`) only selects the interpreter `setup-python` hands the new CI jobs — **ruff never reads `.python-version`**. So the `ruff` job carries an explicit step asserting the two agree. Bump them together; the E9 failure on a `target-version` downgrade and that assert are what actually defend the floor.
- **Never infer the Python floor by grepping for version-gated constructs.** Tokenizer-level changes do not look like keywords and will be missed — `prod/skills/hwpx/scripts/table.py` needs 3.12 only because of PEP 701 f-strings (backslash and reused outer quote inside the braces), which a grep for `match`/`tomllib`/`except*` does not see. Derive it mechanically instead:

```sh
# ladder the ruff target-version until E9 clears — lowest clean value is the floor
for v in py39 py310 py311 py312 py313; do
  printf "%-6s " "$v"
  git ls-files -z | grep -zE '\.py$' | xargs -0 ruff check --no-cache --target-version "$v" 2>/dev/null | tail -1
done

# confirm against a real interpreter before asserting a floor
uv python install 3.11 && "$(uv python find 3.11)" -c "import ast; ast.parse(open('path/to/file.py').read())"
```

`ast.parse(..., feature_version=(3, N))` is **not** a valid check here — it does not re-enforce PEP 701's tokenizer restrictions and silently accepts 3.12-only f-strings.

## Plugin Version Bump Rules

`dev/.claude-plugin/plugin.json` and `prod/.claude-plugin/plugin.json` are independent semver manifests. Bump only the plugin that changed.

| Change type | Bump |
|-------------|------|
| Skill or agent added | minor: `x.Y.z → x.(Y+1).0` |
| Skill or agent modified | patch: `x.y.Z → x.y.(Z+1)` |
| Skill or agent removed or renamed | major: `X.y.z → (X+1).0.0` |

Rule: if any file under `dev/` changed in the diff → `dev/plugin.json` version must differ from `main`. CI enforces this (`harness-check.yml`).

Use `scripts/bump-version.sh` to update all version fields atomically (both platform manifests + optional skill):

```bash
# patch bump for dev
bash scripts/bump-version.sh dev patch

# minor bump + skill version
bash scripts/bump-version.sh dev minor --skill harness-curate patch

# bump both plugins
bash scripts/bump-version.sh all patch
```

Files updated per plugin: `.claude-plugin/plugin.json`, `.codex-plugin/plugin.json`, and optionally `skills/{name}/SKILL.md`.

**Stale local bump on sync**: if uncommitted local changes already bumped a plugin version (e.g. `3.7.34 → 3.7.35`) and `git pull` brings in a merged PR that bumped the same manifest further (e.g. `3.7.34 → 3.8.0`), the two edits conflict on the version line. Resolve by re-deriving the bump from the new base, not by keeping either literal value — e.g. local was a patch-level change, so the correct resolution is `3.8.0 → 3.8.1`, not `3.7.35`.

## Regression Test Rules

A regression test must **fail against the bug it names**. Before claiming coverage, remove the
guard the test targets, re-run, and confirm the test goes red — then restore. A green suite is
not evidence; an assertion can hold for both the fixed and the broken behavior and read as
coverage while providing none.

Typical trap: anchoring an ordering assertion on the wrong landmark. `lines.index("```", 1)`
finds the *opening* fence, so "inserted after the fence" is satisfied by an insertion *inside*
the fenced block — the exact defect under test. Anchor on the real target instead.

### Validator Discovery (enumerate by path, fail closed)

A CI validator must decide *what it covers* from the path layout, never from the content it is
about to judge. Content-gated discovery ("check every file that starts with `---`") skips the
loudest forms of the very defect it exists to catch — a file missing that marker entirely, or
one where a UTF-8 BOM makes the marker unrecognizable — and reports green.

Two consequences, both mandatory:

1. Enumerate the target set by path (`*/skills/*/SKILL.md`, `*/agents/*.md`, …) and require
   every member to be valid. Content may add files to the set, never remove them from it.
2. An empty target set is a **failure**, not a pass. A gate that silently covers zero files is
   indistinguishable from a passing one in the CI summary.

Reference implementation: `scripts/ci/check_skill_frontmatter.py`.

### Adjudicated Exceptions Need a Marker, Not a Standing Warning

A new check must not ship a warning the repo has *already decided* is correct-by-design. That
warning never goes away, so it teaches the operator to skim past the whole section — costing the
real drift the check exists to catch. When a legitimate exception exists, give it a mechanical
opt-out (a frontmatter key, a marker comment) and document the class that may use it; deferring
the decision to `tasks.md` leaves the noisy state as the shipped default.

Reference implementation: `spine-exempt: true` in `validate-harness.sh` §11.

## Skill Doc Rules

When writing shell patterns in `SKILL.md` that use variables, always show:

1. Capture: `var=$(cmd)`
2. Check: `[[ -n "$var" ]] || handle_empty`
3. Use: `echo "$var"` or `some_tool "$var"`

Never show step 3 without steps 1–2 visible in the same code block.
