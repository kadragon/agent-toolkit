# kadragon/agent-toolkit

Personal agent plugin marketplace by kadragon.

Two plugins:

### `dev-tools` — development

| Skill | Description | Claude Code | Codex |
|---|---|---|---|
| `harness-init` | Bootstraps agent infrastructure (AGENTS.md, docs/, hooks) | ✅ | ❌ |
| `dev-review-cycle` | Orchestrates Claude/Antigravity/Codex reviewers, merges | ✅ | ❌ |
| `orchestrate` | Multi-agent delegation playbook | ✅ | ❌ |
| `harness-curator` | Mines transcripts to manage harness assets | ✅ | ❌ |
| `loop-engineer` | Iterative quality-improvement loop (Reflexion + independent verifier) for artifacts with no test gate | ✅ | ❌ |
| `dependabot-manager` | Bulk Dependabot PR operations | ✅ | ⚠️ |

**Commands:**

| Command | Description | Claude Code | Codex |
|---|---|---|---|
| `/security-overview` | Scans GitHub security alerts (Dependabot, Code Scanning, Secret Scanning) across owned repos, writes per-repo `plan.md` | ✅ | ❌ |

### `productivity` — document authoring

| Skill | Description | Claude Code | Codex |
|---|---|---|---|
| `hwpx` | Korean HWPX document creation and editing | ✅ | ✅ |
| `persona-debate` | Structured debate among Korean personas | ✅ | ⚠️ |

## Installation

> **Migrating from `toolkit@kadragon`?** The former single plugin is now split into
> `dev-tools@kadragon` and `productivity@kadragon`. Remove the old plugin
> (`claude plugin uninstall toolkit@kadragon`) and install both below.
> Also update any SessionStart hook that referenced `toolkit:harness-maintenance` —
> the hook now ships as `dev-tools:harness-maintenance`.

### npx skills

```bash
# All skills
npx skills add kadragon/agent-toolkit

# Specific skills
npx skills add kadragon/agent-toolkit --skill hwpx
npx skills add kadragon/agent-toolkit --skill persona-debate
npx skills add kadragon/agent-toolkit --skill dev-review-cycle
npx skills add kadragon/agent-toolkit --skill harness-init
npx skills add kadragon/agent-toolkit --skill orchestrate
npx skills add kadragon/agent-toolkit --skill loop-engineer
```

### Claude Code

```bash
claude plugin marketplace add kadragon/agent-toolkit
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
codex plugin add dev-tools@kadragon
codex plugin add productivity@kadragon
```

Install only ✅/⚠️ skills from table above.

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) — `gh auth login`
- [Claude Code](https://claude.ai/code)
- [Codex](https://github.com/openai/codex)

## License

MIT
