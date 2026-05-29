# kadragon/claude-toolkit

Personal Claude Code plugin marketplace by kadragon.

Two plugins:

### `dev-tools` — development

| Skill | Description | Claude Code | Codex |
|---|---|---|---|
| `harness-init` | Bootstraps agent infrastructure (AGENTS.md, docs/, hooks) | ✅ | ❌ |
| `dev-review-cycle` | Orchestrates Claude/Antigravity/Codex reviewers, merges | ✅ | ❌ |
| `security-overview` | Aggregates GitHub security alerts across owned repos | ✅ | ✅ |
| `dependabot-manager` | Bulk Dependabot PR operations | ✅ | ⚠️ |

### `productivity` — document authoring

| Skill | Description | Claude Code | Codex |
|---|---|---|---|
| `hwpx` | Korean HWPX document creation and editing | ✅ | ✅ |

## Installation

### Claude Code

```bash
claude plugin marketplace add kadragon/claude-toolkit
claude plugin install dev-tools@kadragon
claude plugin install productivity@kadragon
```

Via `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "dev-tools@kadragon": true,
    "productivity@kadragon": true
  },
  "extraKnownMarketplaces": {
    "kadragon": {
      "source": {
        "source": "github",
        "repo": "kadragon/claude-toolkit"
      },
      "autoUpdate": true
    }
  }
}
```

### Codex

Codex ignores Claude marketplaces. Install skills via `skill-installer`:

```bash
~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo kadragon/claude-toolkit \
  --path dev-tools/skills/<name>      # or productivity/skills/<name>
```

Install only ✅/⚠️ skills from table above.

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) — `gh auth login`
- [Claude Code](https://claude.ai/code)

## License

MIT