# Golden Principles Guide

Golden principles are the 3-7 invariants specific to a project that, if violated, cause the most damage. They must be mechanically enforceable — a principle without a lint rule, test, or hook is just a wish.

## How to Discover Golden Principles

Ask these questions:

1. **"What breaks production most often?"** → The answer usually reveals the top 2-3 principles.
2. **"What do new team members get wrong first?"** → Agents will make the same mistakes.
3. **"What rules exist that people forget?"** → If humans forget, agents will too — encode mechanically.
4. **"What security boundaries must never be crossed?"** → SQL injection, auth bypass, secret exposure.

## Examples by Tech Stack

### Web Backend (Node/Python/Java/Go)

1. **Input validation at boundaries** — Parse and validate all external input at API entry points, not deep in business logic.
2. **No raw SQL with user input** — Use parameterized queries or ORM. String concatenation with user data is a security boundary violation.
3. **Auth middleware on every route** — No endpoint should be accidentally unprotected.
4. **Structured logging** — All log statements use structured format (JSON/key-value), never string interpolation.
5. **Database migrations are additive** — Never drop columns in a migration; deprecate first.

### Frontend (React/Vue/Svelte)

1. **No inline styles for layout** — Use the design system's spacing/layout tokens.
2. **All user-facing strings go through i18n** — No hardcoded text in components.
3. **API calls go through the client layer** — Components never call fetch/axios directly.
4. **Error boundaries on every route** — No route should crash the entire app.

### Data Pipeline (Python/Spark/dbt)

1. **Schema validation on ingestion** — Every data source has a schema contract; fail fast on mismatch.
2. **Idempotent transforms** — Running the same transform twice produces the same result.
3. **No PII in logs** — All logging must sanitize sensitive fields.
4. **Partition keys are immutable** — Never change the partitioning scheme of a production table.

### Mobile (iOS/Android/React Native)

1. **No network calls on main thread** — All IO is async.
2. **Feature flags for new features** — Nothing ships without a kill switch.
3. **Backward-compatible API changes** — Old app versions must not break on API updates.

### Infrastructure (Terraform/Pulumi/CDK)

1. **No manual resource creation** — Everything is in code; drift is a bug.
2. **Least privilege IAM** — No wildcard permissions; scope to specific resources.
3. **State file is sacred** — Never manually edit terraform state.

## Writing Good Principles

**Good:** "All INSERT/UPDATE statements include audit timestamp columns via the `audit_macro` include."
- Specific, mechanically checkable, explains the mechanism.

**Bad:** "Always write secure code."
- Vague, not checkable, not actionable.

**Good:** "API response types must be generated from OpenAPI spec. Hand-written response types are not allowed."
- Specific, enforceable via lint rule, prevents drift.

**Bad:** "Keep types in sync with the API."
- How? When? What does "in sync" mean?

## Delegation Discipline (Cross-Cutting Principle)

Delegation is not a "nice-to-have guideline" — when the project uses sub-agents, delegation discipline should be a golden principle. The reason: agents consistently overestimate their own understanding and skip delegation when triggers are subjective. If "delegate before modifying unfamiliar module" is the rule, the agent will decide it's familiar enough and proceed directly every time.

**The fix: objective, measurable triggers that remove agent judgment from the decision.**

### Why Subjective Triggers Fail

| Subjective trigger | Agent's likely reasoning | Result |
|---|---|---|
| "Before modifying unfamiliar module" | "I read the file, I understand it" | Skips delegation |
| "When the change is complex" | "This is straightforward" | Skips delegation |
| "If unsure about the impact" | "I'm fairly confident" | Skips delegation |

Models have a systematic bias toward overconfidence about their own comprehension. Any trigger that requires self-assessment of understanding will be bypassed.

### Objective Trigger Examples

| Objective trigger | Why it works |
|---|---|
| "Module has >5 files OR >500 LOC" | Measurable, no judgment needed |
| "File not in the last 10 commits by this agent session" | Git history is factual |
| "Touches ≥3 modules in one change" | Count-based, unambiguous |
| "Changes a file matching `**/auth/**` or `**/billing/**`" | Path-based, mechanical |
| "Any schema migration" | File-type trigger, no judgment |
| "First edit in a directory this session" | Session-scoped, trackable |

### Writing the Principle

**Good:** "Before modifying any module with >5 files: delegate to Explore agent. Before any change touching ≥3 directories: delegate to Architecture analysis agent. No exceptions — this is a golden principle, not a suggestion."

**Bad:** "Delegate when working on unfamiliar or complex parts of the codebase."

### Enforcement

Delegation principles can be enforced via:
- **PreToolUse hook** — Check if the target file/directory matches a delegation trigger before allowing Edit/Write
- **Workflow checkpoint** — Delegation is a named step in the `code` workflow, not a footnote
- **Session log audit** — Sweep checks whether delegation actually happened for qualifying changes

## From Principle to Enforcement

Each principle needs at least one enforcement mechanism:

| Enforcement | When to use | Example |
|-------------|-------------|---------|
| **Lint rule** | Pattern is syntactically detectable | "No `${}` in SQL without justification comment" |
| **Structural test** | Architectural boundary | "Controllers may not import from data layer" |
| **Pre-commit hook** | Must catch before commit | "Run schema validation on migration files" |
| **CI check** | Needs full build context | "SpotBugs static analysis on compiled classes" |
| **PostToolUse hook** | Catch during agent editing | "Run lint on every file save" |
