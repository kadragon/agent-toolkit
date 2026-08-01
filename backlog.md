# Backlog

## prod plugin

- [ ] [FIX] `prod/.claude-plugin/plugin.json` declares no `"agents": "./agents/"` field, but `prod/agents/persona-actor.md` exists and `prod/skills/persona-debate/SKILL.md:48` spawns `prod:persona-actor` by name. Per `docs/platform-specs.md:30,38`, the field is required for plugin-shipped agents to load — verify whether the spawn actually resolves, then either add the field or drop the `prod:` reference (found while working the PR #182 review backlog)
