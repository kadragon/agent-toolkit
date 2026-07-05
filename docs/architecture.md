# Architecture

## Stack

| Layer | Technology |
|-------|-----------|
| Plugin format | Claude Code plugin (`.claude-plugin/plugin.json`) |
| Languages | Bash (hooks, scripts), Python 3.x (data/analysis scripts) |
| Distribution | GitHub marketplace via `kadragon/agent-toolkit` |
| CI | GitHub Actions |
| Secondary target | Codex (`.codex-plugin/plugin.json`, `.agents/plugins/`) |

## Source Layout

```
dev-tools/
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

productivity/
  .claude-plugin/plugin.json
  agents/
  skills/
    hwpx/
    persona-debate/

.claude/
  agents/                      # project-level agent roles (not shipped)
  skills/                      # project-level orchestrator skills
  hooks/                       # project-level hooks
  settings.json                # hook wiring
  trigger-routes.json          # route table for trigger-router.sh

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
- No cross-plugin imports — `dev-tools/` skill must not reference `productivity/` paths
- Agent artifacts go to the session scratchpad directory (path given in the system prompt) — never committed, never repo-root
- Delegation-gate evidence files live in `.claude/tmp/` (gitignored, repo-local — see `references/enforcement-template.md`)

### Boundaries

- Each plugin is independently installable — no shared deps at runtime
- `dev-tools/skills/harness-init/references/` is internal to harness-init; do not reference from other skills

## Key Abstractions

1. **`plugin.json` version** — sole mechanism for marketplace update propagation; missed bump = marketplace not updated
2. **`SKILL.md` `description:` field** — primary auto-invocation signal; directive phrasing ("ALWAYS invoke when...") outperforms descriptive
3. **Agent roles** (`.claude/agents/*.md`) — reusable subagent definitions; Markdown body is system prompt; frontmatter controls tools/model
4. **Trigger router** (`.claude/hooks/trigger-router.sh`) — pattern-matches prompt → emits explicit delegation instruction; raises ~50% description-only baseline toward deterministic
5. **`backlog.md`** — queue of work not yet in flight; reconciled by `scripts/reconcile-harness.py` against `backlog.md` sprints
