# agent-toolkit

Plugin marketplace (dev-tools + productivity) by kadragon. This repo IS the harness — skills, agents, hooks shipped to other repos.

## Docs Index (read on demand)

| File | When to read |
|------|--------------|
| `docs/architecture.md` | Before adding new skill/agent/hook or modifying plugin structure |
| `docs/conventions.md` | Before writing shell scripts, commit messages, or bumping versions |
| `docs/workflows.md` | When starting any implementation cycle |
| `docs/delegation.md` | Before delegating to sub-agents |
| `docs/eval-criteria.md` | When evaluating skill quality |
| `docs/runbook.md` | For validate/test commands and troubleshooting |

## Golden Principles

Invariants enforced mechanically. Violations block merges.

1. **Version bump mandatory** — If files under `dev-tools/` changed, `dev-tools/.claude-plugin/plugin.json` version must increment. Same for `productivity/`. Enforced by CI (`harness-check.yml`). Semver: add skill/agent → minor; modify → patch; remove/rename → major.
2. **Shell capture-before-use** — Shell patterns must show `var=$(cmd)` before `$var` use. Never reference a variable before the capture step. Enforced by code review + PR checklist.
3. **Delegation discipline** — Objective triggers in `docs/delegation.md` are hard stops. Skipping a mandatory gate is a violation. Triggers are measurable (file count, path pattern) — not subjective.
4. **Agent integrity** — Never state a value as fact without directly reading it from a file/command output this session. Write `[unknown — read {source}]` instead of guessing. Applies to: version numbers, file paths, skill names, API shapes.

## Delegation (Hard Stop)

Read `docs/delegation.md` for full routing table. All triggers are objective.

`.claude/hooks/trigger-router.sh` (UserPromptSubmit) maps prompt phrases → explicit `Use Skill(X)` / `Spawn Agent(X)` instructions.

| Trigger (objective) | Delegate | Model |
|---------------------|----------|-------|
| Plugin area not explored this session, target >3 files | explorer | sonnet |
| Implementation task from backlog | implementer | sonnet |
| After any source edit | qa-verifier | sonnet |
| Skill quality assessment | skill-evaluator | opus |
| Same failure ×2 | advisor tool | — |

## Token Economy

1. Do not re-read a file already read this session. Check diff/region only.
2. No tool calls to confirm known facts. Direct answers for simple questions.
3. Independent tool calls in parallel — never sequential when not dependent.
4. Delegate analysis that produces >20 lines to sub-agent; return conclusion only.
5. Do not restate user's message.

## Working with Existing Code

- `plugin.json` is the release contract — bump it last, after all skill changes, before PR
- Skills are in `{plugin}/skills/{name}/SKILL.md` — `description:` field drives auto-invocation
- Agent roles in `.claude/agents/*.md` — used both as subagent and Agent Teams teammate
- Tests: Python scripts in `{plugin}/skills/{name}/scripts/` — run with `python {script} --test` if `--test` flag exists
- Validate harness: `bash /Users/kadragon/.claude/plugins/cache/kadragon/dev-tools/3.0.7/skills/harness-init/scripts/validate-harness.sh`

## Platform Pointers

This repo targets two AI coding tools:

- **Claude Code** — `AGENTS.md` (this file)
- **Codex** — `.agents/plugins/marketplace.json` + `{plugin}/.codex-plugin/plugin.json`

## Language Policy

- Code, commits, docs: English
- User responses: Korean (always, even when thinking in English)

## Maintenance

Update this file **only** when ALL of the following are true:

1. Information is not directly discoverable from code / config / manifests / docs
2. It is operationally significant — affects build, test, deploy, or runtime safety
3. It would likely cause mistakes if left undocumented
4. It is stable and not task-specific

**Never add:** architecture summaries, directory overviews, style conventions
already enforced by tooling, anything already visible in the repo, or
temporary / task-specific instructions.

Prefer modifying or removing outdated entries over appending. When unsure, add
a short inline `TODO:` comment rather than inventing guidance.

Size budget: target ≤100 lines, hard warn >200. Move long content to
`docs/*.md` and leave a pointer line here.
