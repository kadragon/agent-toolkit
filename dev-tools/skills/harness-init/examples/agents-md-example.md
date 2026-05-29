# TaskFlow Agent Rules

A Next.js 14 SaaS task management app with PostgreSQL, Prisma ORM, and Tailwind CSS.

## Docs Index (read on demand)

| File | When to read |
|------|--------------|
| `docs/architecture.md` | Before modifying source structure or adding new modules |
| `docs/conventions.md` | Before writing new components, API routes, or DB queries |
| `docs/workflows.md` | When starting any implementation cycle |
| `docs/delegation.md` | Before delegating to sub-agents |
| `docs/eval-criteria.md` | When evaluating completed features |
| `docs/runbook.md` | For build, test, deploy commands and troubleshooting |

## Golden Principles

Invariants enforced mechanically. Violations block commits.

1. **No raw Prisma outside `lib/db/`** — All database access goes through typed query functions. Enforced by ESLint `no-restricted-imports` rule.
2. **Input validation at API boundary** — Every API route and server action validates input with Zod schemas from `lib/validators/`. Enforced by custom ESLint rule.
3. **No `any` type** — TypeScript strict mode with `noImplicitAny`. Enforced by `tsconfig.json` + CI type check.
4. **Server components by default** — `"use client"` only when the component needs browser APIs or event handlers. Enforced by PR review checklist.
5. **Audit fields on all mutations** — Every INSERT/UPDATE includes `createdAt`/`updatedAt` via Prisma middleware. Enforced by Prisma middleware (automatic).

## Delegation (Hard Stop)

Delegation is a golden principle — skipping a mandatory gate is a violation. Read `docs/delegation.md` for full routing table, context manifests, and orchestrator patterns. All triggers are objective and measurable.

**Mechanical enforcement.** This table is not advisory — hooks back it up:
- `.claude/hooks/trigger-router.sh` (UserPromptSubmit) maps prompt phrases → explicit `Use Skill(X)` / `Spawn Agent(X)` instructions. Default-on whenever the delegation table is non-empty.
- `.claude/hooks/delegation-gate.sh` (PreToolUse on `Edit|Write`) blocks edits to critical paths without prior delegation evidence in `_workspace/`. **Critical-path repos only** — install when the delegation table has at least one path-based "Mandatory, blocking" row. The example here shows the maximalist case (both hooks); minimalist repos may ship only the router.

If a mandatory row fires for your task and the agent attempts to edit anyway, the gate halts the edit. To extend coverage, update both the table here and `.claude/trigger-routes.json` in the same commit.

**Execution mode selection (read `docs/delegation.md` → Pattern Selection):**
- Sub-agents share findings mid-flight → Agent Team (`TeamCreate` + `SendMessage`)
- Independent parallel results → Orchestrator-Subagent (`Agent` with `run_in_background`)
- Phase-dependent → Hybrid (see `references/orchestrator-template.md`)

| Trigger (objective) | Delegate | Mode | Gate |
|---------------------|----------|------|------|
| Target module has >5 files or >500 LOC | Explore agent (sonnet) | sub-agent | Mandatory, blocking |
| Change touches ≥3 directories | Architecture analysis (opus) | sub-agent | Mandatory, blocking |
| First edit in a directory this session | Explore agent (sonnet) | sub-agent | Mandatory, blocking |
| File matches `**/auth/**`, `**/billing/**`, `prisma/migrations/**` | Analysis agent (sonnet) | sub-agent | Mandatory, blocking |
| After implementation (always) | QA verification (sonnet) | sub-agent | Mandatory, blocking |
| Feature complete | Product evaluator (opus) | sub-agent | Mandatory, blocking |
| Multi-perspective review needed | Review team (sonnet × N) | **agent team** | Optional |
| Cross-layer refactor (≥3 modules) | Refactor team (opus lead + sonnet) | **agent team** | Escalation |
| Every commit | Code reviewer (sonnet) | background | Background |
| Same failure x2 | Deep investigation (opus) | sub-agent | Escalation, blocking |

**Intermediate artifacts:** `_workspace/{phase:02d}_{agent}_{artifact}.{ext}`. See `docs/delegation.md` → Data Transfer Protocols.

## Token Economy

Rules that apply every message — keep the context window lean.

1. Do not re-read a file already read in this session. If you need to check a change, read only the diff/region.
2. Do not call tools just to confirm information you already have. Simple questions deserve direct answers.
3. Run independent tool calls in parallel (multiple reads, grep + glob, etc.) — not sequentially.
4. Delegate any analysis that would produce >20 lines of output to a sub-agent; return only the conclusion to this context.
5. Do not restate what the user just said. They can read their own message.

## Working with Existing Code

- Components in `src/components/ui/` are shadcn/ui primitives — modify via `npx shadcn-ui add`, never edit directly
- Database schema changes require a Prisma migration (`npx prisma migrate dev --name {desc}`)
- Server actions live alongside their page in `app/`, not in a shared actions file
- Test with `npm test` before every commit; integration tests need `DATABASE_URL` pointing to test DB
- Styling uses Tailwind utility classes only — no CSS modules, no styled-components

## Language Policy

- Code, commits, docs: English
- User-facing strings: i18n via `next-intl` (English + Korean)

## Platform Pointers (optional — include only in multi-agent-tool environments)

If the team uses more than one AI coding tool, add this section so each tool's agent finds the canonical rules:

```markdown
## Platform Pointers
- Claude Code / Codex: `AGENTS.md` (this file)
- Cursor: `.cursorrules` (add `@AGENTS.md` inside it)
- Gemini CLI: `GEMINI.md` (add `@AGENTS.md` pointer)
- GitHub Copilot: `.github/copilot-instructions.md` (copy key sections)
```

**Skip this section** on single-tool repos — it adds noise with no benefit.

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
