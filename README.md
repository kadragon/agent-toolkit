# kadragon/agent-toolkit

Personal agent plugin marketplace by kadragon.

Two plugins:

### `dev` — development

| Skill | Description | Claude Code | Codex |
|---|---|---|---|
| `harness-init` | Bootstraps agent infrastructure (AGENTS.md, docs/, hooks) | ✅ | ❌ |
| `task-review` | Orchestrates Claude/Antigravity/Codex reviewers, merges | ✅ | ❌ |
| `harness-curate` | Mines transcripts to manage harness assets | ✅ | ❌ |
| `repo-dependabot` | Bulk Dependabot PR operations | ✅ | ⚠️ |

**Commands:**

| Command | Description | Claude Code | Codex |
|---|---|---|---|
| `/security-overview` | Scans GitHub security alerts (Dependabot, Code Scanning, Secret Scanning) across owned repos, writes per-repo `plan.md` | ✅ | ❌ |

### `prod` — document authoring

| Skill | Description | Claude Code | Codex |
|---|---|---|---|
| `hwpx` | Korean HWPX document creation and editing | ✅ | ✅ |
| `persona-debate` | Structured debate among Korean personas | ✅ | ⚠️ |

## Installation

> **Migrating from `toolkit@kadragon`?** The former single plugin is now split into
> `dev@kadragon` and `prod@kadragon`. Remove the old plugin
> (`claude plugin uninstall toolkit@kadragon`) and install both below.
> Also update any SessionStart hook that referenced `toolkit:harness-maintenance` —
> the hook now ships as `dev:harness-maintenance`.

### npx skills

```bash
# All skills
npx skills add kadragon/agent-toolkit

# Specific skills
npx skills add kadragon/agent-toolkit --skill hwpx
npx skills add kadragon/agent-toolkit --skill persona-debate
npx skills add kadragon/agent-toolkit --skill task-review
npx skills add kadragon/agent-toolkit --skill harness-init
```

### Claude Code

```bash
claude plugin marketplace add kadragon/agent-toolkit
claude plugin install dev@kadragon
claude plugin install prod@kadragon
```

Via `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "dev@kadragon": true,
    "prod@kadragon": true
  },
  "extraKnownMarketplaces": {
    "kadragon": {
      "source": {
        "source": "github",
        "repo": "kadragon/agent-toolkit"
      },
      "autoUpdate": true
    }
  }
}
```

### Codex

Codex uses `.agents/plugins/marketplace.json` and `.codex-plugin/plugin.json` manifests:

```bash
codex plugin marketplace add kadragon/agent-toolkit
codex plugin add dev@kadragon
codex plugin add prod@kadragon
```

Install only ✅/⚠️ skills from table above.

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) — `gh auth login`
- [Claude Code](https://claude.ai/code)
- [Codex](https://github.com/openai/codex)

## License

MIT
