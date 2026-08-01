# Tasks

## Review Backlog

### PR #183 — fold by-name bump carve-out into shipped skills; track agent role files (2026-08-01)

All items below are **content defects in `.claude/agents/*.md`**. PR #183 changed only their
tracking status (`.gitignore`), not a byte of their bodies, so each was classified out-of-scope
per `consolidation-guide.md` §8. Fix them together in one follow-up.

- [ ] [debt] `skill-evaluator` Exit Criteria writes its verdict to `{scratchpad}/02_skill-evaluator_{skill-name}.md` with the path derived from its *own* system prompt, contradicting `docs/delegation.md:84` ("sub-agents must not guess or reconstruct it") — the lead cannot find the file. Compounding: `tools:` grants no `Write`, Boundaries say "do not edit anything", and Bash is limited to read-only self-tests, so the criterion is unsatisfiable as written; the `02_` slot also collides with `02_implementer_diff.md` (`docs/delegation.md:82`). One fix resolves all three: either return the scored table as the tool result, or grant scoped `Write` plus a lead-supplied absolute path and renumber the phase slot (source: review, codex) — `.claude/agents/skill-evaluator.md:5,20,36`
- [ ] [doc] `skill-evaluator` Check 1 says "test router with sample phrases from the description", but a router does not exist — contradicted by line 19 of the same file ("model-judged; no router in this repo"), `AGENTS.md:29`, and `docs/eval-criteria.md:19`. Restate per `docs/eval-criteria.md:19`: draft representative prompts, confirm the skill is the unambiguous best match, confirm the `NOT for …` cases exclude neighboring skills (source: review) — `.claude/agents/skill-evaluator.md:28`
- [ ] [debt] `qa-verifier` lists "`plugin.json` version bumped" under **Checks (always run)**, but a docs/`AGENTS.md`/`backlog.md`-only change needs no manifest bump, so the check fails a QA cycle that should pass. Make it conditional on a shipped plugin asset actually changing, per `docs/conventions.md:115-133` (source: codex) — `.claude/agents/qa-verifier.md:28`
- [ ] [doc] `implementer` Boundaries reads "files outside the listed plugin area; do not touch tests…" — the first clause has no prohibition verb, so it parses as an inclusion, the opposite of intent. Siblings (`explorer.md:20`, `qa-verifier.md:20`, `skill-evaluator.md:20`) all state prohibitions. Fix: "do not touch files outside the listed plugin area; …" (source: review) — `.claude/agents/implementer.md:22`

### Harness gap found while running the cycle (2026-08-01)

- [ ] [debt] `dev:task-next` pre-merge cleanup omits the CHANGELOG step on the *tasks.md finding group* path, while the h1-sprint and backlog.md-group paths both require one. `docs/conventions.md:30-33` states the rule unconditionally ("One line per completed cycle") and PR #176's review-backlog cycle did get an entry, so the skill's per-source branching is wrong — Codex caught the missing entry in this very PR. Add the CHANGELOG step to the finding-group path (source: codex + this cycle) — `dev/skills/task-next/SKILL.md` § "Pre-merge cleanup"
