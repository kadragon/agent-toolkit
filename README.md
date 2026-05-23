# skills

Personal Claude Code plugins by kadragon.

## Plugins

### kadragon-tools

| Skill | Claude Code | Codex | Description |
|---|---|---|---|
| `security-overview` | ✅ | ✅ | GitHub security alert aggregator across owned repos |
| `hwpx` | ✅ | ✅ | Korean HWPX document creation/editing |
| `dependabot-manager` | ✅ | ⚠️ | Dependabot bulk PR ops. Codex: subagent steps degrade (no Claude sonnet subagents) |
| `dev-review-cycle` | ✅ | ❌ | Orchestrates Claude/Antigravity/Codex reviewers — Claude-only host |
| `harness-init` | ✅ | ❌ | Bootstraps `.agents/skills` symlink + Claude-shaped harness |

## Installation

### Claude Code

```bash
claude plugins:add kadragon-tools --marketplace kadragon/skills
```

Or add manually to `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "kadragon-tools@skills": true
  },
  "extraKnownMarketplaces": {
    "skills": {
      "source": {
        "source": "github",
        "repo": "kadragon/skills"
      },
      "autoUpdate": true
    }
  }
}
```

### Codex

Codex ignores Claude marketplaces. Install skills via Codex's built-in `skill-installer`:

```text
# In Codex
> install skill from github kadragon/skills path kadragon-tools/skills/<name>
```

Or run the installer script directly:

```bash
~/.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py \
  --repo kadragon/skills \
  --path kadragon-tools/skills/<name>
```

Then restart Codex. Install only ✅/⚠️ skills from the table above.

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) — authenticated via `gh auth login`
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

## License

MIT
