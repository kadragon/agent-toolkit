# Architecture Template

The architecture doc is the "lay of the land" — it tells the agent where things are and how they connect. Keep it factual and verifiable against the actual code.

## Template Structure

```markdown
# Architecture

## Stack

| Layer | Technology |
|-------|-----------|
| Language | {e.g., TypeScript 5.x} |
| Framework | {e.g., Next.js 14, App Router} |
| Database | {e.g., PostgreSQL 16 via Prisma ORM} |
| Frontend | {e.g., React 18, Tailwind CSS} |
| Build | {e.g., Turbopack, pnpm workspaces} |
| CI | {e.g., GitHub Actions} |

## Source Layout

{Describe the directory structure at the level agents need to navigate.}

## Layer Rules

{Define which layers can depend on which. This is where architectural enforcement lives.}

### Dependency Direction

{Direction flows downward. Upper layers may import lower layers, not the reverse.}

### Boundaries

{What crosses module/package boundaries and what doesn't.}

## Data Access

{How the application talks to databases/external services. DAO patterns, repository layer, ORM usage.}

## Key Abstractions

{The 3-5 most important abstractions an agent needs to understand to work in this codebase. Not an exhaustive list — just the ones that cause confusion.}
```

## Concrete Example: Next.js SaaS App

```markdown
# Architecture

## Stack

| Layer | Technology |
|-------|-----------|
| Language | TypeScript 5.4 |
| Framework | Next.js 14, App Router |
| Database | PostgreSQL 16 via Prisma ORM |
| Auth | NextAuth.js v5 |
| Frontend | React 18, Tailwind CSS, shadcn/ui |
| Build | Turbopack (dev), Webpack (prod) |
| CI | GitHub Actions |

## Source Layout

src/
  app/              # Next.js App Router pages and layouts
    (auth)/         # Auth-related routes (grouped, no URL segment)
    (dashboard)/    # Dashboard routes
    api/            # API route handlers
  components/       # Shared React components
    ui/             # shadcn/ui primitives
  lib/              # Business logic and utilities
    db/             # Prisma client, queries, transactions
    auth/           # Auth config and helpers
    validators/     # Zod schemas for input validation
  types/            # Shared TypeScript types

## Layer Rules

### Dependency Direction

app/ -> components/ -> lib/ -> types/
         (UI)        (logic)  (contracts)

Upper layers may import lower layers, not the reverse.
lib/ must NEVER import from app/ or components/.

### Boundaries

- `app/api/` handlers call `lib/` functions — no direct DB queries in route handlers
- `components/` are pure UI — no fetch calls, no DB imports
- `lib/db/` is the only module that imports Prisma client
- Zod schemas in `lib/validators/` are the single source of truth for input shapes

## Data Access

All database access goes through `lib/db/`. Pattern:

  lib/db/users.ts     -> findUser(), createUser(), updateUser()
  lib/db/projects.ts  -> findProject(), listProjects()

Each file exports query functions. No raw Prisma calls outside lib/db/.
Transactions use Prisma interactive transactions ($transaction).

## Key Abstractions

1. **Server Actions** — Form mutations use server actions in `app/`, not API routes
2. **Query functions** — All DB access via typed functions in `lib/db/`, never inline Prisma
3. **Zod schemas** — Input validation at API boundary, shared between client and server
```

## Writing Tips

- **Be specific about paths.** "Services are in `src/services/`" beats "the service layer."
- **State the rules, not the aspirations.** If the rule is frequently violated, say so: "Services should not import from controllers. (Currently 3 violations — see tasks.md.)"
- **Link to enforcement.** "This boundary is enforced by {lint rule / test / CI check}."
- **Update when the code changes.** A doc that contradicts code is a bug.
