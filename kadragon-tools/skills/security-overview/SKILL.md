---
name: security-overview
description: Scan all GitHub security alerts (Dependabot, Code Scanning, Secret Scanning) across every repo owned by the authenticated user, ensure each repo is cloned locally, and generate a per-repo plan.md with prioritized fix tasks. This skill should be used when the user mentions "security alerts", "vulnerability scanning", "dependabot overview", "code scanning", "secret scanning", "check my repos for vulnerabilities", or "security overview". Trigger even if only one alert type is mentioned — the skill covers all three.
---

# Security Overview

Scan all GitHub security alerts across authenticated user's repos, ensure affected repos cloned locally, produce per-repo `plan.md` with prioritized fix tasks.

Respond in user's language; technical artifacts (commits, branches, file paths) in English.

## Execution Model

Single continuous flow: **Discover → Ensure Local → Generate Plans**.

## Phase 1: Discovery

### 1-1. Authenticate and list repos

Verify `gh` authenticated. If not, stop and suggest `gh auth login`.

```bash
GH_USER=$(gh api user --jq '.login')
gh repo list "${GH_USER}" --json name,url --limit 300 -q '.[] | "\(.name) \(.url)"'
```

### 1-2. Collect Dependabot alerts

Fetch all Dependabot vulnerability alerts in single paginated GraphQL call. Execute `scripts/fetch-alerts.sh` directly, or extract query pattern for manual use.

For query structure, field reference, pagination details → **`references/api-patterns.md`** § Dependabot.

### 1-3. Collect Code Scanning and Secret Scanning alerts

Fetch alerts per repo via REST. Handle expected errors:

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 403/404 | Feature not enabled | Record as "not enabled", skip |

Endpoint details, response fields → **`references/api-patterns.md`** § Code Scanning / Secret Scanning.

**Critical**: Always strip `.secret` field from secret scanning responses to prevent credential leaks into context.

### 1-4. Present summary

Show consolidated table of repos with alerts:

| Repo | Dependabot | Code Scanning | Secret Scanning | Total |
|------|-----------|--------------|----------------|-------|
| repo-name | 3 (1 HIGH, 2 LOW) | 1 (1 ERROR) | 0 | 4 |

Sort by total descending. Include severity breakdown. Skip repos with zero alerts.

After table: total repos scanned, repos with/without alerts, breakdown by type and severity.

## Phase 2: Ensure Local Repos

For each repo with alerts, ensure local clone exists.

### 2-1. Determine workspace directory

Default to **parent** of current working directory. If current directory not typical workspace child (e.g., running from home), confirm target with user before cloning.

```bash
WORKSPACE_DIR=$(dirname "$(pwd)")
```

### 2-2. Check and clone

For each affected repo:
1. Check if `${WORKSPACE_DIR}/${REPO_NAME}` exists.
2. If missing, clone: `gh repo clone ${GH_USER}/${REPO_NAME} "${WORKSPACE_DIR}/${REPO_NAME}"`

Report status: already-local vs newly-cloned repos.

## Phase 3: Generate plan.md

Write **separate** `plan.md` into **each affected repo's root**. Do NOT create single consolidated file.

### 3-1. Read code context

Before writing fix plans, read relevant files per repo:

- **Dependabot**: Read dependency manifests (package.json, requirements.txt, etc.) for current versions. Skip lock files.
- **Code Scanning**: Read flagged file at reported line range (+-5 lines). If file deleted, mark alert stale.
- **Secret Scanning**: Note alert type and location. Do NOT read or display secret values.

### 3-2. Write plan.md

Template, formatting rules, severity ordering, idempotency → **`references/plan-template.md`**.

Key rules:
- Each `- [ ]` = one atomic, actionable fix.
- Order by severity: CRITICAL > HIGH > MODERATE > LOW.
- Omit empty sections.
- If plan.md exists with `## Security Fixes` section, **replace** that section only (preserve other content).

### 3-3. Present result

After generating all files, show summary table with repo, path, item count. Include total items and suggest next step.

## Error Handling

| Condition | Action |
|-----------|--------|
| `gh` not authenticated | Stop, suggest `gh auth login` |
| Rate limited | Report progress, suggest waiting or reducing scope |
| Permission denied on repos | Report skipped repos, continue |
| Clone fails | Report error, continue with other repos |

## Resources

### Scripts

- **`scripts/fetch-alerts.sh`** — Standalone script collecting all three alert types. Outputs structured JSON to scan directory. Execute directly or read for query patterns.

### Reference Files

- **`references/api-patterns.md`** — GraphQL/REST query details, response field reference, error handling, rate limiting.
- **`references/plan-template.md`** — plan.md template, formatting rules, severity ordering, idempotency, example output.