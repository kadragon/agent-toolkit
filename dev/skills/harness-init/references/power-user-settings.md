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

**Not for long-context models.** The whole premise is "quality degrades before the window fills." On a ~1M-window model that is told by its own base instructions to keep working through summarization, compacting at 75% throws away live context to pre-empt a degradation you have not measured — and 75% of 1M is more context than most sessions ever reach. Leave it unset unless you have watched quality drop in this repo's own long sessions; then set it just below where it dropped.

**Why not auto-apply**: 75 is aggressive for debugging sessions that legitimately need long context; 83 is wasteful on short tasks. No single value fits everyone, and the bugs above mean the benefit is probabilistic.

## Extended-thinking budget

Extended thinking ("thinking hard") is a token sink that's easy to forget is on. `/effort` switches per-session:

- `low` — minimal thinking, fastest, cheapest
- `medium` — balanced
- `high` — deeper reasoning, more tokens
- `xhigh` — above `high`, below `max`
- `max` — maximum thinking budget

`auto` also exists (settable as `CLAUDE_CODE_EFFORT_LEVEL` in `settings.json` `env`) and lets the model pick per turn — the sane default now. Verify the tier list against `/effort` in the installed CLI before documenting it in a repo; the set has grown at least once.

**Guidance**: leave it on `auto` for normal coding. Pin `high`/`max` per session only for architectural decisions or deep debugging, `low` for mechanical edits and glue-code tasks.

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

Write a `handoff-<feature>.md` at the **start** of work that genuinely spans sessions — goals, constraints, current state — and reload it next session. That value is model-independent: a new CLI session starts cold no matter how large the window.

What is *not* model-independent is the older framing of this pattern as a compaction escape hatch (agents "wrap up prematurely" when autocompaction looms — see `workflows-template.md` → Context Anxiety). Long-context models are instructed to work through summarization, so do not write handoffs mid-task to pre-empt compaction, and do not read this section as an endorsement of `CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=75`.

## Sources

- [CLAUDE_AUTOCOMPACT_PCT_OVERRIDE Guide — TurboAI](https://www.turboai.dev/blog/claude-autocompact-pct-override-guide)
- [Claude Code Context Buffer mechanics — claudefa.st](https://claudefa.st/blog/guide/mechanics/context-buffer-management)
- [anthropics/claude-code#31806](https://github.com/anthropics/claude-code/issues/31806)
- [anthropics/claude-code#36381](https://github.com/anthropics/claude-code/issues/36381)
- [Output styles — Claude Code Docs](https://code.claude.com/docs/en/output-styles)
- [Memory (CLAUDE.md, rules, auto-memory) — Claude Code Docs](https://code.claude.com/docs/en/memory)
- ["Claude Code used 2.5M tokens on my project. I got it down to 425K" — DEV Community](https://dev.to/cytostack/claude-code-used-25m-tokens-on-my-project-i-got-it-down-to-425k-with-6-hook-scripts-d40)
