# Conventions Template

The conventions doc captures naming patterns, coding standards, and framework-specific rules that agents frequently get wrong. Only include what the linter does NOT already catch — duplicating lint rules wastes context.

## Template Structure

```markdown
# Conventions

## Naming

| Element | Pattern | Example |
|---------|---------|---------|
| Files | {pattern} | {example} |
| Functions | {pattern} | {example} |
| Components | {pattern} | {example} |
| Database tables | {pattern} | {example} |
| API endpoints | {pattern} | {example} |
| Environment vars | {pattern} | {example} |
| CSS classes | {pattern} | {example} |

## Code Style

### Import Order

{Define the canonical import order. Example:}

1. Standard library
2. External packages
3. Internal packages (absolute)
4. Relative imports
5. Type-only imports

### Error Handling

{Project-specific error handling conventions. Example:}

- Wrap external errors with domain-specific error types
- Never swallow errors silently — log or propagate
- Use structured error codes, not free-form strings

### Async Patterns

{If applicable. Example:}

- Prefer async/await over raw promises
- Cancel long-running operations on component unmount
- Never fire-and-forget — always handle the promise

## Framework-Specific Rules

### {Framework Name}

{Rules that go beyond the framework defaults. Only include what agents get wrong.}

**Examples by framework:**

#### React / Next.js
- Server components by default; add `"use client"` only when needed
- Data fetching in server components, not useEffect
- Route handlers return NextResponse, not plain objects

#### Django / FastAPI
- Serializers validate input; views orchestrate, never validate directly
- Background tasks via Celery, not threading
- All model fields have explicit `verbose_name`

#### Spring Boot
- Constructor injection only, never field injection
- DTOs for API boundaries, entities for persistence — never expose entities
- Transactions at service layer, never at controller

## API Conventions

{If the project has APIs:}

### Request/Response Format

- Envelope: `{ "data": ..., "error": ..., "meta": ... }`
- Pagination: cursor-based, not offset-based
- Dates: ISO 8601 with timezone

### Status Codes

| Scenario | Code |
|----------|------|
| Success | 200 / 201 |
| Validation error | 400 |
| Auth failure | 401 / 403 |
| Not found | 404 |
| Server error | 500 |

## Git Conventions

### Commit Messages

{Define the project's commit message format. Example:}

```
[TYPE] description

TYPE: FEAT | FIX | REFACTOR | DOCS | CONSTRAINT | HARNESS
```

### Branch Naming

{Example:}

- Feature: `feature/{ticket-id}-{short-desc}`
- Fix: `fix/{ticket-id}-{short-desc}`
- Hotfix: `hotfix/{short-desc}`

### Branch Policy

- **Never commit directly to `main`/`master`.** Create a feature branch before the first edit of any task.
- If agents find themselves on the default branch when starting work, they must `git checkout -b` before staging changes.
- Document any exception (e.g. direct-push repos) explicitly in `AGENTS.md` — default behavior is branch-per-task.
```

## Writing Tips

- **Only add what the linter misses.** If ESLint already enforces import order, skip it.
- **Be prescriptive, not descriptive.** "Use snake_case for DB columns" beats "We generally prefer snake_case."
- **Include counter-examples.** Show what NOT to do — agents learn boundaries from negative examples.
- **Update when the convention changes.** A convention doc that contradicts the codebase trains agents to write inconsistent code.
