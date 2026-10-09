# Golden Principles Guide

Golden principles are real project invariants that, if violated, cause the most damage.
There is no minimum count; omit the section when no applicable invariant exists. They must be mechanically enforceable — a principle without a lint rule, test, or hook is just a wish.

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

Configured roles or an actual delegation workflow can justify delegation guidance. Default
inline; higher-level prohibitions remain binding. Add objective triggers only for verified
coordination needs, within choices the higher layers permit. A threshold is a local policy,
not an assumed global gate; file counts or output length alone do not mandate delegation.

Independent verification can justify a separate reviewer without parallel implementation.
Name only available roles or supported built-ins. Keep detailed routing in an existing workflow
or delegation doc when needed; no mandatory table or generic golden principle is required.

Enforce a justified critical-path trigger mechanically only after an observed miss or a
concrete safety need, using existing hooks/workflow checks. A prose threshold that contradicts
higher-level authorization cannot grant permission to spawn.

## Agent Integrity Principle (Universal)

Preserve applicable integrity boundaries against fabricated values. Read the targeted
instruction layers before duplicating this rule; its universal relevance does not require a
new Golden Principles section or another copy in every repository.

**The principle:** `not_observed != absent`. Missing local proof means unverified — not impossible, not default, not inferred from general knowledge.

**Concrete rule to include in AGENTS.md:**

> **Fabrication ban:** If you have not directly read the value from a file, command output, or tool result in this session, you must not state it as fact. Write `[unknown — read {source} to verify]` instead. Applies to: port numbers, API endpoints, schema fields, config values, version numbers, feature flags.

**Why this matters:** Language models have strong priors from training data. An agent asked "what port does this service run on?" will often answer `3000` or `8080` from training — even when the actual `docker-compose.yml` says `4000`. The agent doesn't lie intentionally; it pattern-matches. The integrity principle forces a Read before a claim.

**Enforcement:** PreToolUse hook that warns when an agent's message contains a port, URL, or version string that doesn't appear in any file read during this session. Hard to implement perfectly — even a soft advisory version (log the warning, don't block) reduces fabrications significantly.

**High-risk domains for fabrication:**
- Port numbers, connection strings, database names
- API endpoint paths and HTTP methods
- Schema field names and types
- Feature flag names and default values
- Dependency versions and package names

**In spec/plan files:** When generating `spec.md`, `backlog.md`, or task descriptions, mark any value not directly read as `[unknown]`. Future sessions that read the spec see a concrete work item: "resolve `[unknown]`", not a silent lie.

## From Principle to Enforcement

Each principle needs at least one enforcement mechanism:

| Enforcement | When to use | Example |
|-------------|-------------|---------|
| **Lint rule** | Pattern is syntactically detectable | "No `${}` in SQL without justification comment" |
| **Structural test** | Architectural boundary | "Controllers may not import from data layer" |
| **Pre-commit hook** | Must catch before commit | "Run schema validation on migration files" |
| **CI check** | Needs full build context | "SpotBugs static analysis on compiled classes" |
| **PostToolUse hook** | Catch during agent editing | "Run lint on every file save" |
