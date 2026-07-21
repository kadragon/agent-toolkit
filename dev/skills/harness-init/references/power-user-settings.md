# Power-User Settings Catalog (informational)

Community-validated optional settings that trade off specific axes. **Not auto-applied by harness-init** — each has real trade-offs or outstanding bugs. Read through and pick per repo/user preference.

## Auto-compaction threshold

Default auto-compaction fires around 95% context usage — by which point quality has already noticeably degraded. Lowering the threshold means Claude compacts earlier, while the conversation is still coherent.

```json
{
  "env": {
    "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "75"
  }
}
```

**Recommended values**:

| Value | Use case |
|-------|----------|
| 60-70 | Short tasks, aggressive quality preservation |
| **75** | General development (most common pick) |
| 80-83 | Complex multi-file work needing max context |

**Known limitations (as of 2026-04)**:
- Effective cap is ~83% — setting higher silently clamps. See anthropics/claude-code#31806.
- Does not always trigger at the exact configured threshold — some reports of drift to 67-80% before compaction fires. See anthropics/claude-code#36381.
- `/context` display ignores the override and still shows the default buffer. See anthropics/claude-code#27189.

**Why not auto-apply**: 75 is aggressive for debugging sessions that legitimately need long context; 83 is wasteful on short tasks. No single value fits everyone, and the bugs above mean the benefit is probabilistic.

## Extended-thinking budget

Extended thinking ("thinking hard") is a token sink that's easy to forget is on. `/effort` switches per-session:

- `low` — minimal thinking, fastest, cheapest
- `medium` — default
- `high` — deeper reasoning, more tokens
- `max` — maximum thinking budget

**Guidance**: Pin `medium` as the session default for normal coding. Bump to `high`/`max` only for architectural decisions or deep debugging. Drop to `low` for mechanical edits and glue-code tasks.

Not something harness-init should force — it's a per-task decision.

## Output styles

Claude Code's response verbosity is controlled by output styles. Default is tuned for software engineering. Explanatory/Learning styles explicitly produce **more** output — so avoid those unless onboarding.

To define a project-specific terse style, create `.claude/output-styles/terse.md` with frontmatter + a short system-prompt-appendix asking Claude to skip preamble, reasoning summaries, and post-action recaps. Then `/output-style terse` to activate.

**Worth doing if**: the repo's agents consistently over-explain completed work. Measurable via `ccusage` — output tokens per message should drop noticeably after switching.

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

**Why not auto-apply**: it's on by default in recent versions and the boundary is a team decision — harness-init only documents it (a line in AGENTS.md `## Maintenance`), it does not flip the toggle.

## Autocompact-aware handoff

When autocompaction is imminent, agents often preemptively wrap up work prematurely ("context anxiety" — see `workflows-template.md`). Companion pattern: write a `handoff-<feature>.md` file at the start of multi-session work, containing goals, constraints, and current state. Reload it in the next session to pick up cleanly instead of relying on compaction recovery.

This is a process habit, not a setting — but pairs naturally with `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=75` since it acknowledges compaction is a brute operation better avoided than tuned.

## Sources

- [CLAUDE_AUTOCOMPACT_PCT_OVERRIDE Guide — TurboAI](https://www.turboai.dev/blog/claude-autocompact-pct-override-guide)
- [Claude Code Context Buffer mechanics — claudefa.st](https://claudefa.st/blog/guide/mechanics/context-buffer-management)
- [anthropics/claude-code#31806](https://github.com/anthropics/claude-code/issues/31806)
- [anthropics/claude-code#36381](https://github.com/anthropics/claude-code/issues/36381)
- [Output styles — Claude Code Docs](https://code.claude.com/docs/en/output-styles)
- [Memory (CLAUDE.md, rules, auto-memory) — Claude Code Docs](https://code.claude.com/docs/en/memory)
- ["Claude Code used 2.5M tokens on my project. I got it down to 425K" — DEV Community](https://dev.to/cytostack/claude-code-used-25m-tokens-on-my-project-i-got-it-down-to-425k-with-6-hook-scripts-d40)
