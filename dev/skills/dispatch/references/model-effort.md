# Model families and starting effort

Read this when choosing a Codex model or a starting effort in SKILL.md step 3, or when a
launch stops on model resolution.

## Codex families

Docs and handoffs name Codex models by family only: `luna`, `terra`, `sol`. A versioned slug
goes stale when the next release lands, so `dispatch.py launch --cli codex --model <family>`
resolves it at launch from `$CODEX_HOME/models_cache.json` (default `~/.codex`):

- entries with `visibility: list` whose slug is `gpt-<version>-<family>`;
- skipping entries with an `upgrade` value, which Codex sets on a retiring model;
- the highest numeric version wins.

The receipt and `--dry-run` output carry `model_family` (as requested) and `model` (the slug
passed to `codex -m`). A full slug passes through unchanged. A missing or unreadable cache, or no
matching entry, stops the launch: start Codex once to refresh the cache, or pass a full slug.
The launcher refuses `fable` and `astra` (bare or as any `gpt-*-astra`) on either CLI.

`terra` is a writing and visual model, not a mid-tier coding model: mid-tier Codex coding and
review run on `sol` at `medium`.

## Starting effort

| Model | Start | Vendor guidance |
|-------|-------|-----------------|
| `haiku` | `medium`, agentic coding included; `low` only for a short lookup that edits no file | Haiku 5.5: "Start with `medium` for most work, including agentic coding." "In long agent prompts, the model is more likely to skip a search, stop early, or skip a check at `low`." [A] |
| `luna` | `high`; `medium` only for a short lookup that edits no file; never `ultra` | "Luna, for clear, repeatable tasks." "For Luna, start with High." Luna supports efforts up to Max, not Ultra. [O] |
| `sonnet` | `medium` for well-specified coding; `high` for harder or longer work | Sonnet 5.5: "start with `medium` for well-specified tasks and move to `high` for harder or longer ones." [A] |
| `sol` | `medium`, the everyday start; top-tier work by the effort table | Sol, "for everyday work." [O] |
| `opus` | `medium`; judgment work by the effort table | Opus 5.5: "`medium` is the default." [A] |
| `terra` | by the effort table | Terra, "for everyday writing and visual work." [O] |

"Most tasks do not need Max or Ultra." [O]

When a result falls short, `escalation.md` decides between more effort and a larger model.

Sources, read 2026-11-26:

- [O] OpenAI, models: https://learn.chatgpt.com/docs/models
- [A] Anthropic, effort: https://platform.claude.com/docs/en/build-with-claude/effort
