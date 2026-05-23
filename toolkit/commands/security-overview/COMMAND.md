---
description: "Scan all GitHub security alerts (Dependabot, Code Scanning, Secret Scanning) across owned repos and write per-repo plan.md with prioritized fix tasks"
allowed-tools: ["Bash", "Read", "Write"]
---

# Security Overview

Scan all GitHub security alerts across authenticated user's repos, ensure affected repos cloned locally, produce per-repo `plan.md` with prioritized fix tasks.

Respond in user's language; technical artifacts (commits, branches, file paths) in English.

## Execution Model

Single continuous flow: **Discover → Ensure Local → Generate Plans**.

## Phase 1: Discovery

### 1-1. Authenticate and list repos

Verify `gh` authenticated. If not, stop and suggest `gh auth login`.

Note: `fetch-alerts.sh` caps repo discovery at 300 — accounts with more repos will see incomplete results.

```bash
GH_USER=$(gh api user --jq '.login')
gh repo list "${GH_USER}" --json name,url --limit 300 -q '.[] | "\(.name) \(.url)"'
```

### 1-2. Collect Dependabot alerts

Fetch all Dependabot vulnerability alerts in single paginated GraphQL call.

**Default: use `scripts/fetch-alerts.sh`.** Use manual query only when: (a) script unavailable, (b) user requests specific API exploration, (c) script fails. Never mix both in the same run.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/commands/security-overview/fetch-alerts.sh"
```

For query structure, field reference, pagination details → **`${CLAUDE_PLUGIN_ROOT}/commands/security-overview/api-patterns.md`** § Dependabot.

### 1-3. Collect Code Scanning and Secret Scanning alerts

Fetch alerts per repo via REST. Handle expected errors:

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 403/404 | Feature not enabled | Record as "not enabled", skip |

**Critical**: Always strip `.secret` field from secret scanning responses to prevent credential leaks into context. `fetch-alerts.sh` strips secret fields automatically. If using manual queries, pipe through `jq 'del(.[] | .secret)'` before processing.

### 1-4. Present summary

Show consolidated table of repos with alerts:

| Repo | Dependabot | Code Scanning | Secret Scanning | Total |
|------|-----------|--------------|----------------|-------|
| repo-name | 3 (1 HIGH, 2 LOW) | 1 (1 ERROR) | 0 | 4 |

Sort by total descending. Include severity breakdown. Skip repos with zero alerts.

After table: total repos scanned, repos with/without alerts, breakdown by type and severity.

## Phase 2: Ensure Local Repos

Clone only repos that Phase 1 identified as having active alerts. Do not clone repos with zero alert count.

### 2-1. Determine workspace directory

Default to **parent** of current working directory. If `pwd` is home directory, `/tmp`, or contains fewer than 2 path components after `$HOME`, confirm target directory with user before cloning.

```bash
WORKSPACE_DIR=$(dirname "$(pwd)")
```

### 2-2. Check and clone

For each affected repo:
1. Check if `${WORKSPACE_DIR}/${REPO_NAME}` exists.
2. If missing, clone: `gh repo clone ${GH_USER}/${REPO_NAME} "${WORKSPACE_DIR}/${REPO_NAME}"`

Report status: already-local vs newly-cloned repos. If clone fails for one repo, log the error, continue with remaining repos. Report all failures in final summary. Do NOT abort the entire run.

## Phase 3: Generate plan.md

Write **separate** `plan.md` into **each affected repo's root**. Do NOT create single consolidated file.

### 3-1. Read code context

Before writing fix plans, read relevant files per repo:

- **Dependabot**: Read dependency manifests (package.json, requirements.txt, etc.) for current versions. Skip lock files.
- **Code Scanning**: Read flagged file at lines `max(1, flagged_line - 5)` through `flagged_line + 5` inclusive. If file deleted: do NOT dismiss via API autonomously — mark in plan.md as `[STALE - file deleted]` and add action item `- [ ] Manually dismiss via GitHub Security tab`.
- **Secret Scanning**: Note alert type and location. Do NOT read or display secret values.

### 3-2. Write plan.md

Template, formatting rules, severity ordering, idempotency → **`${CLAUDE_PLUGIN_ROOT}/commands/security-overview/plan-template.md`**.

Key rules:
- Each `- [ ]` = one atomic, actionable fix.
- Order by severity: CRITICAL > HIGH > MODERATE > LOW.
- Omit empty sections.

### 3-3. Present result

After generating all files, show summary table with repo, path, item count. Include total items and suggest next step.

## Error Handling

| Condition | Action |
|-----------|--------|
| `gh` not authenticated | Stop, suggest `gh auth login` |
| Rate limited | Report progress, suggest waiting or reducing scope |
| Permission denied on repos | Report skipped repos, continue |
| Clone fails | Report error, continue with other repos |
