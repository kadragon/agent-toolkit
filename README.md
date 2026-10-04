# kadragon/agent-toolkit

Personal agent plugin marketplace by kadragon.

Three plugins:

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

### `pr-study` — PR study pane (Claude Code only)

A function-hook mod: docks a pane beside the transcript with study points for the current branch's
diff against `main` (file +/− bars, concept cards, tickable self-check questions, links to
`.repo-quiz/mistakes.md`). Refreshes after each main-loop turn when the diff changed; `/pr-study`
forces a rebuild. Uses one `haiku` call per changed diff. Docking needs the fullscreen layout. The mod
API is early access, so a Claude Code update may break it. Not shipped to Codex.

## Installation

> **Migrating from `toolkit@kadragon`?** The former single plugin is now split into
> `dev@kadragon` and `prod@kadragon`. Remove the old plugin
> (`claude plugin uninstall toolkit@kadragon`) and install both below.
> Also update any SessionStart hook that referenced `toolkit:harness-maintenance` —
> maintenance now runs inside the `dev` plugin's single SessionStart dispatcher
> (`hooks/session-start/run.sh`).

### npx skills

```bash
# All skills
npx skills add kadragon/agent-toolkit

# Specific skills
npx skills add kadragon/agent-toolkit --skill hwpx
npx skills add kadragon/agent-toolkit --skill persona-debate
npx skills add kadragon/agent-toolkit --skill task-review
npx skills add kadragon/agent-toolkit --skill task-review-cycle  # required — task-review only forwards to it
npx skills add kadragon/agent-toolkit --skill harness-init
```

### Claude Code

```bash
claude plugin marketplace add kadragon/agent-toolkit
claude plugin install dev@kadragon
claude plugin install prod@kadragon
claude plugin install pr-study@kadragon  # optional, Claude Code only
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
