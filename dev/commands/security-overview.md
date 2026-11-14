---
description: "Scan GitHub security alerts (Dependabot, Code Scanning, Secret Scanning) for the repo in the current directory and append prioritized fix tasks to its backlog.md"
allowed-tools: ["Bash", "Read", "Write"]
---

# Security Overview

Scan GitHub security alerts for the repository checked out in the current working directory, then append a prioritized `## Security Fixes` section to that repo's `backlog.md`. Other repos the user owns are out of scope.

Respond in user's language; technical artifacts (commits, branches, file paths) in English.

## Execution Model

Single continuous flow: **Discover → Generate Tasks**.

## Phase 1: Discovery

### 1-1. Authenticate and resolve the repo

Verify `gh` authenticated. If not, stop and suggest `gh auth login`. Resolve the current directory's repo; if `gh repo view` fails (not a git checkout, or no GitHub remote), stop and say so.

```bash
REPO_INFO=$(gh repo view --json nameWithOwner,url -q '"\(.nameWithOwner) \(.url)"')
echo "${REPO_INFO}"
```

### 1-2. Collect alerts

**Default: use `fetch-alerts.sh`** — it fetches Dependabot (GraphQL), Code Scanning and Secret Scanning (REST) for this repo only. Use manual queries only when: (a) script unavailable, (b) user requests specific API exploration, (c) script fails. Never mix both in the same run.

```bash
bash "${CLAUDE_PLUGIN_ROOT}/commands/security-overview/fetch-alerts.sh"
```

For query structure, field reference, error handling → **`${CLAUDE_PLUGIN_ROOT}/references/security-overview/api-patterns.md`**.

Expected errors: Code Scanning 403/404 and Secret Scanning 404 mean the feature is not enabled — record as "not enabled", skip.

**Critical**: Always strip `.secret` field from secret scanning responses to prevent credential leaks into context. `fetch-alerts.sh` strips secret fields automatically. If using manual queries, pipe through `jq 'del(.[] | .secret)'` before processing.

### 1-3. Present summary

Show one row for the repo:

| Repo | Dependabot | Code Scanning | Secret Scanning | Total |
|------|-----------|--------------|----------------|-------|
| repo-name | 3 (1 HIGH, 2 LOW) | 1 (1 ERROR) | 0 | 4 |

Mark a feature that is not enabled as "not enabled". If the total is zero, report that and stop — do not touch `backlog.md`.

## Phase 2: Update backlog.md

Write a `## Security Fixes` section into the current repo's `backlog.md`. Do NOT write to `tasks.md` — that file is the current Sprint Contract and is deleted at sprint close, so findings placed there are lost.

### 2-1. Read code context

Before writing fix tasks, read the relevant files:

- **Dependabot**: Read dependency manifests (package.json, requirements.txt, etc.) for current versions. Skip lock files. Before writing items, check for already-open Dependabot PRs: run `gh search prs --author app/dependabot --state open --repo <owner>/<repo> --limit 100 --json number,title,url` once (not per-alert), then match each alert's package name exactly (not by substring) against the package token in PR titles. Pattern details → **`${CLAUDE_PLUGIN_ROOT}/references/security-overview/api-patterns.md`** § Cross-referencing Open PRs.
- **Code Scanning**: Read flagged file at lines `max(1, flagged_line - 5)` through `flagged_line + 5` inclusive. If file deleted: do NOT dismiss via API autonomously — mark in backlog.md as `[STALE - file deleted]` and add action item `- [ ] Manually dismiss via GitHub Security tab`.
- **Secret Scanning**: Note alert type and location. Do NOT read or display secret values.

### 2-2. Write the backlog.md section

Template, formatting rules, severity ordering, idempotency → **`${CLAUDE_PLUGIN_ROOT}/references/security-overview/backlog-template.md`**.

Key rules:
- Each `- [ ]` = one atomic, actionable fix.
- Order by severity: CRITICAL > HIGH > MODERATE > LOW.
- Omit empty sections.
- If an alert's package matches an open Dependabot PR, write the PR-pointer item instead of the manual upgrade item — format → backlog-template.md.
- An alert matching the repo's `## Rejected — do not re-file` entry is withheld unless its re-file bar is met; list it in the summary — backlog-template.md § Rejected Items.

### 2-3. Present result

After writing, show the repo, `backlog.md` path, and item count. Include the Withheld line for alerts held back by `## Rejected — do not re-file` (it explains any gap from the Phase 1 totals), and suggest next step.

## Error Handling

| Condition | Action |
|-----------|--------|
| `gh` not authenticated | Stop, suggest `gh auth login` |
| Rate limited | Report progress, suggest waiting |
| Not a GitHub repo checkout | Stop, ask the user to run from the repo directory |
| Permission denied | Report which alert type was unreadable, continue with the rest |
