# kadragon/toolkit

Personal Claude Code plugin marketplace by kadragon.

## Skills

| Skill | Description | Claude Code | Codex |
|---|---|---|---|
| `harness-init` | Bootstraps agent infrastructure (AGENTS.md, docs/, hooks) | ✅ | ❌ |
| `dev-review-cycle` | Orchestrates Claude/Antigravity/Codex reviewers, merges | ✅ | ❌ |
| `security-overview` | Aggregates GitHub security alerts across owned repos | ✅ | ✅ |
| `dependabot-manager` | Bulk Dependabot PR operations | ✅ | ⚠️ |
| `hwpx` | Korean HWPX document creation and editing | ✅ | ✅ |

## Installation

### Claude Code

```bash
claude plugin marketplace add kadragon/toolkit
claude plugin install toolkit@kadragon
```

Via `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "toolkit@kadragon": true
  },
  "extraKnownMarketplaces": {
    "kadragon": {
      "source": {
        "source": "github",
        "repo": "kadragon/toolkit"
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
  --repo kadragon/toolkit \
  --path toolkit/skills/<name>
```

Install only ✅/⚠️ skills from table above.

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) — `gh auth login`
- [Claude Code](https://claude.ai/code)

## License

MIT