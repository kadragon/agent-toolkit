# Auto-memory Settings (informational)

Not auto-applied by harness-init: the memory boundary is a team decision, so init documents it
(SKILL.md Step 8) and leaves the toggle alone.

## Auto-memory (model-authored)

Recent Claude Code (v2.1.59+) writes its own discovered learnings to a per-project memory dir (`MEMORY.md` + topic files). The first ~200 lines / 25 KB of `MEMORY.md` load every session; topic files load on demand. It is per-repo, shared across worktrees, machine-local.

**Boundary with the harness you author** — keep them distinct so they don't drift:

| Home | Holds | Authored by |
|------|-------|-------------|
| AGENTS.md, `.claude/rules/`, `docs/` | durable code/repo facts — architecture, conventions, golden principles | human, version-controlled |
| auto-memory (`MEMORY.md`) | discovered preferences, cross-session learnings | the model, machine-local |

A code fact that belongs in `docs/` should never live only in auto-memory (it won't survive a fresh clone or reach other contributors). Conversely, don't hand-curate `MEMORY.md` — that's the model's scratchpad.

**Settings:**

```json
{
  "autoMemoryEnabled": true,
  "autoMemoryDirectory": "~/.claude/projects/<project>/memory"
}
```

- Disable per-session with `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`, or globally via `autoMemoryEnabled: false`.
- Relocate with `autoMemoryDirectory` (e.g. onto a synced volume).

Source: [Memory (CLAUDE.md, rules, auto-memory) — Claude Code Docs](https://code.claude.com/docs/en/memory)
