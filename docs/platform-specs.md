# Platform Specs: Claude Code vs Codex CLI

This repo ships plugins for **both** platforms. Any skill, hook, or agent added here must be evaluated against both specs.

## Quick Comparison

| Aspect | Claude Code | Codex CLI |
|--------|-------------|-----------|
| Manifest path | `.claude-plugin/plugin.json` | `.codex-plugin/plugin.json` |
| Skills | `skills/{name}/SKILL.md` | `skills/{name}/SKILL.md` (same) |
| Agents | `agents/*.md` (plugin.json `agents` field) | NOT in plugin.json — use `AGENTS.md` |
| Hooks | `hooks.json` (plugin.json `hooks` field) | `hooks.json` (same field, fewer events) |
| Commands | `commands/*.md` | NOT supported |
| MCP | `.mcp.json` via `mcpServers` field | Same |
| Plugin hook root env | `$CLAUDE_PLUGIN_ROOT` | `$PLUGIN_ROOT` (canonical), `$CLAUDE_PLUGIN_ROOT` compatibility fallback |
| Instruction file | `CLAUDE.md` (Anthropic-specific) | `AGENTS.md` (cross-tool standard) |

---

## Claude Code Plugin Spec

### plugin.json key fields

```json
{
  "name": "dev",
  "version": "X.Y.Z",
  "skills": "./skills/",
  "hooks": "./hooks.json",
  "agents": "./agents/",
  "commands": "./commands/",
  "mcpServers": "./.mcp.json"
}
```

- `skills`: adds to default `skills/`; all subdirs with `SKILL.md` are loaded
- `hooks`: path to hooks.json OR inline object
- `agents`: path to agent `.md` files
- `commands`: flat `.md` files → slash commands (legacy; prefer `skills/`)

### SKILL.md frontmatter (Claude Code)

```yaml
---
name: skill-name
description: |            # 1536-char limit; first line drives auto-invocation
  Use when...
when_to_use: "extra triggers"
allowed-tools: "Bash(git *) Edit"
disallowed-tools: "AskUserQuestion"
model: inherit
effort: high
context: fork             # isolated subagent
agent: Explore
disable-model-invocation: false
---
```

Key: the `description` field drives auto-invocation (description-driven; no router hook in this repo).

When to set `disable-model-invocation`, and what it obliges on the Codex side, is policy — see `docs/invocation.md`.

### hooks.json (Claude Code)

```json
{
  "hooks": {
    "EventName": [
      {
        "matcher": "pattern|or|regex",
        "hooks": [
          {
            "type": "command",
            "command": "bash ${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}/hooks/foo/run.sh",
            "commandWindows": "bash \"$env:PLUGIN_ROOT/hooks/foo/run.sh\"",
            "timeout": 15,
            "statusMessage": "Running..."
          }
        ]
      }
    ]
  }
}
```

**Supported hook events (Claude Code — 31 total):**

| Category | Events |
|----------|--------|
| Session | `SessionStart`, `Setup`, `SessionEnd`, `InstructionsLoaded` |
| Per-turn | `UserPromptSubmit`, `UserPromptExpansion`, `Stop`, `StopFailure` |
| Tool | `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PostToolBatch`, `PermissionRequest`, `PermissionDenied` |
| Subagent | `SubagentStart`, `SubagentStop`, `TaskCreated`, `TaskCompleted`, `TeammateIdle` |
| File/env | `CwdChanged`, `FileChanged`, `ConfigChange`, `WorktreeCreate`, `WorktreeRemove` |
| Compaction | `PreCompact`, `PostCompact` |
| MCP | `Elicitation`, `ElicitationResult` |
| Display | `Notification`, `MessageDisplay` |

**Hook types:** `command` · `http` · `mcp_tool` · `prompt` · `agent`

Hook exit codes: `0` = continue, `2` = block, other = non-blocking error.

### Agent format (Claude Code)

```yaml
---
name: qa-verifier
description: Verify code changes after any source edit
model: sonnet
effort: medium
maxTurns: 20
tools: [Read, Grep, Bash]
disallowedTools: [Write, Edit]
skills: [harness-init]
---
```

Plugin-shipped agents **cannot** declare `hooks`, `mcpServers`, or `permissionMode`.

---

## Codex CLI Plugin Spec

### plugin.json key fields

```json
{
  "name": "dev",
  "version": "X.Y.Z",
  "skills": "./skills/",
  "hooks": "./hooks.json",
  "mcpServers": "./.mcp.json"
}
```

**Critical difference:** NO `agents` field. NO `commands` field. Agents → `AGENTS.md`.

### SKILL.md frontmatter (Codex)

Same file as Claude Code, but Codex reads an additional sidecar:

```yaml
# skills/{name}/agents/openai.yaml
interface:
  display_name: "UI Name Override"
  short_description: "One line for the skill picker"
  icon_large: "./assets/preview.png"   # optional; real sidecars use a repo-relative ./assets/... path
  default_prompt: "The prompt the picker entry fires"
policy:
  allow_implicit_invocation: true
```

Shape verified against the sidecars shipped with `codex-cli 0.147.0` (20+ installed skills under
`~/.codex/skills/*/agents/openai.yaml` and `~/.codex/plugins/cache/**`), not inferred: the UI keys
live **nested under `interface:`**, and `policy:` is a sibling block.

Beyond the keys above, real sidecars also use `interface.icon_small`, `interface.brand_color`, and a
`dependencies.tools[]` block (`type` — only `mcp` today — `value`, `description`, `transport`, `url`)
for MCP dependencies. The authoring contract is Codex's own
`~/.codex/skills/.system/skill-creator/references/openai_yaml.md`; read it rather than extending this
example from memory. Two rules from it bite immediately: `short_description` is a 25–64 char blurb, and
`default_prompt` **must name the skill as `$skill-name`** (that reference's wording). The same file
says a skill with `allow_implicit_invocation: false` "is not injected into the model context by
default, but can still be invoked explicitly via `$skill`" — so the handle is what makes the picker
prompt reach a locked skill. Codex's own locked `review-agent` sidecar follows both rules; note the
bundled `openai-templates` skills are locked *without* the handle, so the corpus is not unanimous.

Implicit invocation = Codex auto-selects skill from description match (same as Claude Code).

`policy.allow_implicit_invocation: false` is the Codex half of a user-invoked skill and must agree with the Claude Code field above — see `docs/invocation.md`.

**Known conflict — Codex's bundled validator rejects the Claude field.**
`~/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py` errors unless
`disable-model-invocation` is absent or `false`; measured on `codex-cli 0.147.0`, running it against
this repo's `dev/` plugin reports one error per locked skill ("must be false"), plus a pre-existing
``plugin.json field `hooks` is not accepted`` error that predates the invocation axis. Codex expects the lock
to ride on `policy.allow_implicit_invocation: false` **alone**. **Decided 2026-08-17 by the repo owner: keep both halves.** Claude Code has no other way to express
the axis, and `dev/` already failed this validator on `hooks` before the axis existed, so nothing
regressed from green. Revisit only if publishing moves to a pipeline that runs the validator.

### hooks.json (Codex)

Same format as Claude Code but **8 events only**:

`SessionStart` · `PreToolUse` · `PostToolUse` · `PermissionRequest` · `UserPromptSubmit` · `SubagentStart` · `SubagentStop` · `Stop`

Hook I/O same as Claude Code (JSON on stdin, JSON on stdout, exit codes).

### Agents (Codex)

NOT a plugin-level concept. Use `AGENTS.md`:

```
{repo-root}/AGENTS.md          → project-level instructions
{repo-root}/.agents/AGENTS.md  → standard location
~/.codex/AGENTS.md             → user-global
```

Files concatenate hierarchically. 32 KiB limit. This is why `AGENTS.md` exists at repo root.

### Marketplace (Codex)

`.agents/plugins/marketplace.json`:

```json
{
  "name": "kadragon",
  "plugins": [
    {
      "name": "dev",
      "source": { "source": "local", "path": "./dev" },
      "policy": { "installation": "AVAILABLE", "authentication": "ON_INSTALL" },
      "category": "Developer Tools"
    }
  ]
}
```

---

## Cross-Platform Rules

### When adding a skill

1. Write `SKILL.md` — same file works for both platforms
2. `skills/{name}/agents/openai.yaml` — **required** for a user-invoked skill: it carries
   `policy.allow_implicit_invocation: false`, which must agree with the `disable-model-invocation: true`
   in the same skill's frontmatter (`docs/invocation.md` → *Per-platform fields*: both harnesses or
   neither). Optional for a model-invoked skill, and then only for Codex UI metadata — never write
   the permissive `allow_implicit_invocation: true`, which says nothing the default does not
3. No `commands/` analog in Codex — do not rely on slash-command invocation for cross-platform skills

### When adding a hook

1. Add to `{plugin}/hooks.json` (both platforms read it)
2. Use only the **8 Codex events** if the hook should work cross-platform; Claude-only hooks (e.g., `PreCompact`, `WorktreeCreate`) are fine but will silently no-op on Codex
3. Use `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}` in shared hook commands — `CLAUDE_PLUGIN_ROOT` wins (canonical for Claude Code; Codex sets it as compat alias), with `PLUGIN_ROOT` as fallback
4. Add `commandWindows` to every command hook. Use PowerShell syntax and Codex's canonical `$env:PLUGIN_ROOT`; never copy Bash parameter expansion into it
5. Test hook with both `$CLAUDE_PLUGIN_ROOT` and `$PLUGIN_ROOT` paths

These variables belong to the plugin hook command environment. They are not guaranteed in shells launched while following a shared `SKILL.md`.

### When adding an agent

1. Add agent `.md` to `{plugin}/agents/` — **Claude Code only**
2. For Codex: encode equivalent behavior in `AGENTS.md` at repo root
3. Both must be kept in sync manually — no auto-sync mechanism

### Version bumps

Both `dev/.claude-plugin/plugin.json` AND `dev/.codex-plugin/plugin.json` must be bumped together. CI enforces both — version mismatch between manifests blocks merge.

---

## Plugin Hook Command Environment

| Var | Codex | Claude Code |
|-----|-------|-------------|
| `$PLUGIN_ROOT` | Canonical installed plugin root | Not documented |
| `$PLUGIN_DATA` | Canonical writable plugin data directory | Not documented |
| `$CLAUDE_PLUGIN_ROOT` | Compatibility fallback for existing plugin hooks | Canonical installed plugin root |
| `$CLAUDE_PLUGIN_DATA` | Compatibility fallback for existing plugin hooks | Writable plugin data directory |
| `$CLAUDE_PROJECT_DIR` | Not documented | Project directory |

For shared Claude/Codex hook definitions, prefer `${CLAUDE_PLUGIN_ROOT:-${PLUGIN_ROOT}}` — `CLAUDE_PLUGIN_ROOT` is canonical for Claude Code and also set by Codex as a compat alias in plugin hooks.

Do not use these root variables to locate files from shared skill instructions. Resolve bundled scripts and references from the absolute parent directory of the `SKILL.md` actually loaded for the turn. Hook script bodies that need adjacent assets should resolve from `BASH_SOURCE[0]` or `__file__`.

Every command hook also needs a PowerShell-safe `commandWindows` using Codex's canonical `$env:PLUGIN_ROOT`.

The same Windows constraint reaches **any shipped script that shells out to an interpreter**, not just hook registrations. Windows installs routinely provide Python as `python` with no `python3` shim — which is why `hooks.json`'s commit-guard entry spells its `commandWindows` as `python ...`. A script that hardcodes `python3` does not error there; it takes whatever fallback branch it has, so a guard silently stops guarding while the run still reports success. Resolve the interpreter instead:

```sh
PY=$(command -v python3 || command -v python || true)
```

Shipped precedents: `hooks/session-start/run.sh` and `skills/task-review-cycle/scripts/commit-and-push.sh`.

## Positional Parameters in Skill Code Blocks

**Rule: no `$0`–`$9` (or `${0}`–`${9}`) anywhere in a fenced code block or inline code span of a
`SKILL.md` or a skill reference doc.** Use a named variable, a non-positional awk field
(`$NF`), or a construct that needs no field reference at all.

**Observed once** (2026-08-19, PR #238 session): a positional inside a fenced block was
substituted from the skill's own invocation arguments as the skill text was loaded.
`task-review-cycle` step 2-1 shipped

```
awk '{s+=$1}END{print s+0}'
```

and, when the skill was invoked as `task-review-cycle --from task-review`, the block arrived in
context as `awk '{s+=task-review}'`. The file on disk was correct — the corruption happened at
load, so nothing in the repo showed it and the failure surfaced only as a wrong runtime value.

**The substitution rule is uncharacterized.** One observation is not a mapping: which argument
lands in which index, whether `$0` and `${N}` are affected, and whether Codex behaves the same
way are all unknown. The rule above is therefore defensive and deliberately wider than the single
confirmed case — a block that contains no positional cannot be corrupted by any variant of the
behavior.

Enforced by `scripts/ci/check_harness_drift.py` (`[positional-param]`), which is a hard fail.
Scripts under `{plugin}/skills/*/scripts/` are exempt and unscanned: those execute from disk and
are never loaded as skill text.

## Executable Line Endings

All shell and Python scripts shipped in plugins must use LF line endings. Bash hooks installed on Windows still run through bash, and CRLF causes parse errors such as `set: pipefail\r: invalid option name`.

---

## Sources

- Claude Code: https://code.claude.com/docs/en/plugins-reference.md
- Codex CLI: https://developers.openai.com/codex/plugins/build
- Codex hooks: https://developers.openai.com/codex/hooks
- Codex skills: https://developers.openai.com/codex/skills
- Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
