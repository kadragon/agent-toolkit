# agent-toolkit

Plugin marketplace (dev + prod) by kadragon. This repo IS the harness — skills, agents, hooks shipped to other repos.

## Docs Index (read on demand)

| File | When to read |
|------|--------------|
| `docs/architecture.md` | Before adding new skill/agent/hook or modifying plugin structure |
| `docs/conventions.md` | Before writing shell or Python scripts, commit messages, or bumping versions |
| `docs/workflows.md` | When starting any implementation cycle |
| `docs/delegation.md` | When you have decided to delegate — brief format, effort tier, handoff protocol |
| `docs/eval-criteria.md` | When evaluating skill quality |
| `docs/runbook.md` | For validate/test commands and troubleshooting |
| `docs/platform-specs.md` | Before writing any skill/hook/agent — covers both Claude Code and Codex CLI spec differences |

## Golden Principles

Invariants enforced mechanically. Violations block merges.

1. **Version bump mandatory** — If files under `dev/` changed, both `dev/.claude-plugin/plugin.json` AND `dev/.codex-plugin/plugin.json` versions must increment (keep in sync). Same for `prod/`. Enforced by CI (`harness-check.yml`) for both platforms. Semver: add skill/agent → minor; modify → patch; remove/rename → major.
2. **Shell capture-before-use** — Shell patterns must show `var=$(cmd)` before `$var` use. Never reference a variable before the capture step. Enforced by code review + PR checklist.
3. **Agent integrity** — Never state a value as fact without directly reading it from a file/command output this session. Write `[unknown — read {source}]` instead of guessing. Applies to: version numbers, file paths, skill names, API shapes.

## Delegation

**The bar lives in your platform's global instruction layer, not here** — `~/.claude/CLAUDE.md` (Claude Code) or `~/.codex/AGENTS.md` (Codex). Default inline. Delegate only when the user asks or a skill directs — **and** only if the work then also clears the global gate (10+ files to read/summarize · 3+ truly independent units · output would flood main context). Both conditions, not either. Coupled, sequential, or judgment-heavy work stays inline. This repo does not impose a lower threshold.

Once you have decided to delegate, `docs/delegation.md` covers *how* — role routing, the four-field spawn brief, effort tier, handoff protocol. Auto-invocation is description-driven: it relies on each `SKILL.md`/agent `description:` field; there is no prompt-matching router hook in this repo.

| Role | Fits | Model |
|------|------|-------|
| explorer | Read-only map of an unfamiliar plugin area | sonnet |
| implementer | A `backlog.md` item with a Sprint Contract | sonnet |
| qa-verifier | Verifying work a *different* agent implemented | sonnet |
| skill-evaluator | Skill quality assessment | opus |

## Token Economy

1. Do not re-read a file already read this session. Check diff/region only.
2. No tool calls to confirm known facts. Direct answers for simple questions.
3. Independent tool calls in parallel — never sequential when not dependent.
4. Do not restate user's message.

## Working with Existing Code

- `plugin.json` is the release contract — bump it last, after all skill changes, before PR
- Skills are in `{plugin}/skills/{name}/SKILL.md` — `description:` field drives auto-invocation
- Agent roles in `.claude/agents/*.md` — used both as subagent and Agent Teams teammate
- Tests: Python scripts in `{plugin}/skills/{name}/scripts/` — run with `python {script} --test` if `--test` flag exists
- Validate harness: run `validate-harness.sh` from the installed `dev/harness-init` skill. Resolve the newest cached copy:
  ```sh
  bash "$(ls -d ~/.claude/plugins/cache/kadragon/dev/*/skills/harness-init/scripts/validate-harness.sh | sort -V | tail -1)"
  ```

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
