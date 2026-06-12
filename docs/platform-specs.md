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
| Env var | `$CLAUDE_PLUGIN_ROOT` | `$PLUGIN_ROOT` (canonical), `$CLAUDE_PLUGIN_ROOT` compatibility fallback |
| Instruction file | `CLAUDE.md` (Anthropic-specific) | `AGENTS.md` (cross-tool standard) |

---

## Claude Code Plugin Spec

### plugin.json key fields

```json
{
  "name": "dev-tools",
  "version": "3.0.7",
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

Key: `description` field + trigger router (`trigger-router.sh`) together drive auto-invocation.

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
            "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/foo/run.sh",
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
  "name": "dev-tools",
  "version": "3.0.7",
  "skills": "./skills/",
  "mcpServers": "./.mcp.json"
}
```

**Critical difference:** NO `agents` field. NO `commands` field. Agents → `AGENTS.md`.

### SKILL.md frontmatter (Codex)

Same file as Claude Code, but Codex reads an additional sidecar:

```yaml
# skills/{name}/agents/openai.yaml
policy:
  allow_implicit_invocation: true
display_name: "UI Name Override"
icon: "path/to/icon.svg"
mcp_tools:
  - "server_name__tool_name"
```

Implicit invocation = Codex auto-selects skill from description match (same as Claude Code).

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
      "name": "dev-tools",
      "source": { "source": "local", "path": "./dev-tools" },
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
2. Optionally add `skills/{name}/agents/openai.yaml` for Codex-specific metadata
3. No `commands/` analog in Codex — do not rely on slash-command invocation for cross-platform skills

### When adding a hook

1. Add to `{plugin}/hooks.json` (both platforms read it)
2. Use only the **8 Codex events** if the hook should work cross-platform; Claude-only hooks (e.g., `PreCompact`, `WorktreeCreate`) are fine but will silently no-op on Codex
3. Use `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` in shared hook commands so Codex uses its canonical variable and Claude Code keeps working
4. Test hook with Codex `$PLUGIN_ROOT` and Claude `$CLAUDE_PLUGIN_ROOT` paths

### When adding an agent

1. Add agent `.md` to `{plugin}/agents/` — **Claude Code only**
2. For Codex: encode equivalent behavior in `AGENTS.md` at repo root
3. Both must be kept in sync manually — no auto-sync mechanism

### Version bumps

Both `dev-tools/.claude-plugin/plugin.json` AND `dev-tools/.codex-plugin/plugin.json` must be bumped together. CI enforces both — version mismatch between manifests blocks merge.

---

## Environment Variables

| Var | Codex | Claude Code |
|-----|-------|-------------|
| `$PLUGIN_ROOT` | Canonical installed plugin root | Not documented |
| `$PLUGIN_DATA` | Canonical writable plugin data directory | Not documented |
| `$CLAUDE_PLUGIN_ROOT` | Compatibility fallback for existing plugin hooks | Canonical installed plugin root |
| `$CLAUDE_PLUGIN_DATA` | Compatibility fallback for existing plugin hooks | Writable plugin data directory |
| `$CLAUDE_PROJECT_DIR` | Not documented | Project directory |

For shared Claude/Codex hook definitions, prefer `${PLUGIN_ROOT:-${CLAUDE_PLUGIN_ROOT}}` so Codex uses its canonical variable and Claude Code keeps working.

## Executable Line Endings

All shell and Python scripts shipped in plugins must use LF line endings. Bash hooks installed on Windows still run through bash, and CRLF causes parse errors such as `set: pipefail\r: invalid option name`.

---

## Sources

- Claude Code: https://code.claude.com/docs/en/plugins-reference.md
- Codex CLI: https://developers.openai.com/codex/plugins/build
- Codex hooks: https://developers.openai.com/codex/hooks
- Codex skills: https://developers.openai.com/codex/skills
- Codex AGENTS.md: https://developers.openai.com/codex/guides/agents-md
