# cc-plugins

Personal Claude Code plugins by kadragon.

## Plugins

### kadragon-tools

| Skill | Description |
|---|---|
| `dependabot-manager` | Dependabot PR 일괄 관리 — 탐색, 분류, 병합, 실패 분석, Grouped Updates 설정 |
| `dev-review-cycle` | PR 생성 → 리뷰 수집(Claude Code, Antigravity, Codex) → 피드백 통합 → CI 대기 → 머지까지 원스톱 워크플로우 |
| `harness-init` | 레포에 하네스 시스템 구축 — AGENTS.md(맵), docs/ 지식 기반, delegation routing, 평가 기준, golden principles, sweep 자동화. Anthropic + OpenAI harness engineering 원칙 기반 |

## Installation

```bash
claude plugins:add kadragon-tools --marketplace kadragon/cc-plugins
```

Or add manually to `~/.claude/settings.json`:

```json
{
  "enabledPlugins": {
    "kadragon-tools@cc-plugins": true
  },
  "extraKnownMarketplaces": {
    "cc-plugins": {
      "source": {
        "source": "github",
        "repo": "kadragon/cc-plugins"
      },
      "autoUpdate": true
    }
  }
}
```

## Prerequisites

- [GitHub CLI (`gh`)](https://cli.github.com/) — authenticated via `gh auth login`
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code)

## License

MIT
