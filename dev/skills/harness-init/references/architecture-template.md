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

## Writing Tips

- **Be specific about paths.** "Services are in `src/services/`" beats "the service layer."
- **State the rules, not the aspirations.** If the rule is frequently violated, say so: "Services should not import from controllers. (Currently 3 violations — see backlog.md.)"
- **Link to enforcement.** "This boundary is enforced by {lint rule / test / CI check}."
- **Update when the code changes.** A doc that contradicts code is a bug.
