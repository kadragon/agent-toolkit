# Architecture

## Stack

| Layer | Technology |
|-------|-----------|
| Plugin format | Claude Code plugin (`.claude-plugin/plugin.json`) |
| Languages | Bash (hooks, scripts), Python 3.x (data/analysis scripts), TypeScript (`mods/` function hooks only) |
| Distribution | GitHub marketplace via `kadragon/agent-toolkit` |
| CI | GitHub Actions |
| Secondary target | Codex (`.codex-plugin/plugin.json`, `.agents/plugins/`) |

## Source Layout

```
dev/
  .claude-plugin/plugin.json   # semver manifest — bump before merge
  agents/                      # plugin-shipped agent roles
  hooks/                       # hook scripts (references/)
  skills/                      # one dir per skill, each has SKILL.md
    harness-init/
      SKILL.md
      scripts/                 # bash/python scripts
      references/              # reference docs for skill system prompt
      examples/
  commands/                    # slash commands

prod/
  .claude-plugin/plugin.json
  agents/
  skills/
    hwpx/
    persona-debate/

mods/                          # Claude Code only — no .codex-plugin, not in the Codex marketplace
  .claude-plugin/plugin.json   # own semver line; userConfig holds each mod's options
  hooks/
    hooks.json                 # names the one hooks module the engine loads
    register.ts                # entry: calls each mod's register by name
    band.tsx                   # the one hook on the band above the prompt; stacks each mod's rows
    status-band/               # one directory per mod: register.tsx, pure logic, *.test.ts(x)
  types/index.d.ts             # $.state contract for every mod

.claude/
  agents/                      # project-level agent roles (not shipped)
  skills/                      # project-level orchestrator skills
  settings.json                # permissions + auto-mode wiring

.agents/
  plugins/                     # Codex plugin manifests
  skills -> ../.claude/skills  # symlink — do not delete
```

## Layer Rules

### Dependency Direction

```
plugin.json
  -> skills/ (SKILL.md + scripts/)
  -> agents/ (agent roles)
  -> hooks/ (hook scripts)
```

- Skills within a plugin may reference that plugin's `agents/` and `references/`
- No cross-plugin imports — `dev/` skill must not reference `prod/` paths
- Agent artifacts go to the session scratchpad directory (path given in the system prompt) — never committed, never repo-root
- Delegation-gate evidence files live in `.claude/tmp/` (gitignored, repo-local — see `references/enforcement-template.md`)

### Boundaries

- Each plugin is independently installable — no shared deps at runtime
- `mods/` is the only place function-hooks code lives. The API is early access and moves between
  Claude Code releases, so nothing under `dev/` or `prod/` may depend on a mod being loaded.
- Inside a mod, engine calls (`$`, `on`, JSX) stay in `register.tsx`; decision logic is plain
  TypeScript beside it with no `claude-code` import, so it survives an API change and tests without `$`.
- A mod never submits a prompt or changes a turn's result on its own: it offers, the person acts.
- The engine takes one unmatched hook per event from a plugin, and one per `ui.render` site. Mods that
  draw above the prompt each export a row builder, and `mods/hooks/band.tsx` holds the single band hook
  that stacks them; `$` and an atom's key never cross an import, so both are spelled in that file.
- `dev/skills/harness-init/references/` owns shared templates (backlog schema, harness invariants); other skills, agents and scripts cite a file there (`dev:harness-init` → `references/<file>`) instead of copying its content

## Key Abstractions

1. **`plugin.json` version** — sole mechanism for marketplace update propagation; missed bump = marketplace not updated
2. **`SKILL.md` `description:` field** — primary auto-invocation signal; directive phrasing ("ALWAYS invoke when...") outperforms descriptive
3. **Agent roles** (`.claude/agents/*.md`) — reusable subagent definitions; Markdown body is system prompt; frontmatter controls tools/model
4. **`backlog.md`** — queue of work not yet in flight; line deletion is owned by `task_nodes.py prune-backlog` at pre-merge cleanup, not by `scripts/reconcile-harness.py` (which closes the `tasks.md` sprint block and reverts orphan or failed-sprint `[>]` markers to `[ ]` while preserving their lines)
