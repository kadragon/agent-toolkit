# Runbook Template

The runbook is the operational cheat sheet — how to build, test, deploy, and troubleshoot. Write it for an agent that has never seen this project before.

## Template Structure

```markdown
# Runbook

## Quick Start

### Prerequisites

- {Runtime}: version {X.Y} (`{version check command}`)
- {Package manager}: version {X.Y}
- {Database}: running on `localhost:{port}`
- {Other services}: {description}

### Setup

{Exact commands to go from clone to running:}

git clone {repo}
cd {repo}
{install command}       # e.g., npm install, pip install -e .
{env setup}             # e.g., cp .env.example .env
{db setup}              # e.g., npx prisma migrate dev
{start command}         # e.g., npm run dev

### Verify

{How to confirm setup worked:}

- Open `http://localhost:{port}` — expect {what}
- Run `{smoke test command}` — expect {what}

## Build

| Command | Purpose |
|---------|---------|
| `{build cmd}` | Production build |
| `{dev cmd}` | Development server with hot reload |
| `{type check cmd}` | Type checking without emitting |

## Test

| Command | Purpose |
|---------|---------|
| `{test all cmd}` | Run full test suite |
| `{test unit cmd}` | Unit tests only |
| `{test integration cmd}` | Integration tests (requires running DB) |
| `{test single cmd} {path}` | Run a single test file |
| `{coverage cmd}` | Test coverage report |

### Test Conventions

- Test files live in `{test directory pattern}`
- Naming: `{naming pattern}` (e.g., `*.test.ts`, `test_*.py`)
- Fixtures in `{fixtures path}`

## Lint & Format

| Command | Purpose |
|---------|---------|
| `{lint cmd}` | Lint check |
| `{lint fix cmd}` | Lint with auto-fix |
| `{format cmd}` | Format all files |
| `{format check cmd}` | Check formatting without writing |

## Deploy

### Environments

| Environment | URL | Branch | Deploy method |
|-------------|-----|--------|---------------|
| Development | {url} | {branch} | {method} |
| Staging | {url} | {branch} | {method} |
| Production | {url} | {branch} | {method} |

### Deploy Steps

{Exact steps, not vague references:}

1. {step 1}
2. {step 2}
3. {verification step}

## Common Failures

### {Failure 1: descriptive title}

**Symptom:** {what the agent sees}
**Cause:** {root cause}
**Fix:** {exact steps}

### {Failure 2: descriptive title}

**Symptom:** {what the agent sees}
**Cause:** {root cause}
**Fix:** {exact steps}

## Environment Variables

| Variable | Required | Description | Example |
|----------|----------|-------------|---------|
| `{VAR_NAME}` | {yes/no} | {purpose} | `{example value}` |

Note: Never commit actual secrets. Use `.env.example` with placeholder values.
```

## Writing Tips

- **Commands must be copy-pasteable.** No "run the build command" — write `npm run build`.
- **Include failure modes.** Agents hit the same failures humans do. Pre-loading the fix saves cycles.
- **Keep it current.** A runbook with stale commands is worse than no runbook — the agent trusts it and fails silently.
- **Test the runbook.** Clone the repo fresh, follow the runbook. If it fails, fix the runbook.
