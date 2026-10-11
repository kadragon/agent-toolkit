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

### `mods` — Claude Code interface mods

Claude Code only. Built on the early-access function-hooks API, so it needs a recent Claude Code
build and may break on an update; `dev` and `prod` do not depend on it.

| Mod | Description | Setting |
|---|---|---|
| `next-steps` | After an answer, suggests up to three follow-up prompts above the prompt. A digit puts one in the draft for you to edit or send, `0` dismisses. Nothing is sent for you. | `Next steps` (on by default), `Next steps model` (`haiku`) |
| `status-band` | Two rows above the prompt, each figure in its own color: model and effort, directory and git branch, session time, prompt-cache time left, hook count and skill count with the size of the skill listing, then context fill and the 5-hour and 7-day rate limits with their resets. A figure the engine has no reading for is left out. | `Status band` (on by default), `Status band cache TTL (minutes)` (`60`) |

Each suggestion costs one small model call per eligible turn. Turns that were interrupted, refused,
errored, run by a subagent, or answered in under 100 characters are skipped. UX after the community
`next-steps` mod (hamzafer.github.io).

`status-band` shows what a `statusLine` command such as claude-hud
(github.com/jarrodwatts/claude-hud, whose layout it follows) shows, so running both draws the same
figures twice: remove the `statusLine` entry from your `settings.json` if you switch. The mod never
edits your settings. It redraws once a minute and after each turn.

The cache figure is an estimate: the engine tells a mod neither the cache's lifetime nor what is
left of it, so the band counts the setting's minutes down from the last main-thread response. Set
it to `5` where your session runs on the short cache. The hook count is the command hooks in your
merged settings plus those of every enabled plugin, read off the files that declare them; hooks
modules such as this one's are not counted.

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
claude plugin install mods@kadragon   # optional
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
