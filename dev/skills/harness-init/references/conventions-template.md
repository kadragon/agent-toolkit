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

## {Area agents get wrong}

{Only rules the linter does not own, each prescriptive, with a counter-example.}

## Git Conventions

### Commit Messages

{Define the project's commit message format. Example:}

```
[TYPE] description
```

{Define one row per type the repo actually uses. Example:}

| Type | Meaning |
|------|---------|
| `[FEAT]` | New behavior |
| `[FIX]` | Bug fix — requires a reproduction step before the fix |
| `[REFACTOR]` | Structure only, no behavior change |
| `[DOCS]` | Documentation only |
| `[CONSTRAINT]` | Structural guards only (lint rule, CI check, schema) |
| `[HARNESS]` | Skill / hook / agent instruction changes |

{Keep the bug-fix row and its reproduction clause: where this repo generated
`docs/eval-criteria.md`, its bug-fix reproduction rule cites this row as the owning convention,
and dropping the row leaves that requirement with nothing to cite.}

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
