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

Delegation is a golden principle — skipping a mandatory gate is a violation. Read `docs/delegation.md` for full routing table and context manifests. All triggers are objective and measurable.

| Trigger (objective) | Delegate | Gate |
|---------------------|----------|------|
| Target module has >5 files or >500 LOC | Explore agent (sonnet) | Mandatory, blocking |
| Change touches ≥3 directories | Architecture analysis (opus) | Mandatory, blocking |
| First edit in a directory this session | Explore agent (sonnet) | Mandatory, blocking |
| File matches `**/auth/**`, `**/billing/**`, `prisma/migrations/**` | Analysis agent (sonnet) | Mandatory, blocking |
| After implementation (always) | QA verification (sonnet) | Mandatory, blocking |
| Feature complete | Product evaluator (opus) | Mandatory, blocking |
| Every commit | Code reviewer (sonnet) | Background |
| Same failure x2 | Deep investigation (opus) | Escalation, blocking |

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
