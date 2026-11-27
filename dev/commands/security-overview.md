---
description: "Scan the current repository's Dependabot, Code Scanning, and Secret Scanning alerts and report or queue prioritized fixes according to repository visibility and queue backend"
allowed-tools: ["Bash", "Read", "Write"]
---

# Security Overview

Scan GitHub security alerts for the current checkout's `origin` and use the matching route below. Other repositories are out of scope.

Respond in user's language; technical artifacts (commits, branches, file paths) in English.

## Execution Model

Single continuous flow: **Discover → Report or file fixes**.

## Phase 1: Discovery

### 1-1. Authenticate and resolve the repo

Verify `gh` authenticated. If not, stop and suggest `gh auth login`. The scan target is the checkout's `origin` remote — not bare `gh repo view`, which follows `GH_REPO` and prefers an `upstream` remote. `fetch-alerts.sh` resolves it; exit 2 (no git checkout or no origin) or 3 (origin is not a GitHub repo gh can read) → stop and report its message.

### 1-2. Collect alerts

**Default: use `fetch-alerts.sh`** — it fetches Dependabot (GraphQL), Code Scanning and Secret Scanning (REST) for this repo only. Use manual queries only when: (a) script unavailable, (b) user requests specific API exploration, (c) script fails. Never mix both in the same run.

```bash
SCAN_OUT=$(bash "${CLAUDE_PLUGIN_ROOT}/commands/security-overview/fetch-alerts.sh")
SCAN_DIR=$(tail -1 <<<"$SCAN_OUT")
```

Results go to a temp directory outside the repo (last output line), so raw alert data stays outside the working tree.

For query structure, field reference, error handling → **`${CLAUDE_PLUGIN_ROOT}/references/security-overview/api-patterns.md`**.

Bind all three alert requests to the canonical origin host. Before filing, verify that the current
`origin` still resolves to the same repository and confirm that its visibility is still private.
If the check fails, report only.

Expected errors: Code Scanning 403/404 and Secret Scanning 404 mean the feature is not enabled; the script writes `<type>.disabled` beside the `[]` result — report that type as "not enabled", not as 0. Any other failure lands in `.fetch-errors`.

**Critical**: Always strip `.secret` field from secret scanning responses to prevent credential leaks into context. `fetch-alerts.sh` strips secret fields automatically. If using manual queries, pipe through `jq 'del(.[] | .secret)'` before processing.

### 1-3. Present summary

Show one row for the repo:

| Repo | Dependabot | Code Scanning | Secret Scanning | Total |
|------|-----------|--------------|----------------|-------|
| repo-name | 3 (1 HIGH, 2 LOW) | 1 (1 ERROR) | 0 | 4 |

Mark a feature that is not enabled as "not enabled". If `${SCAN_DIR}/.fetch-errors` exists, show it and treat zero counts as unknown. Flag truncated results per api-patterns.md. Resolve the route before making any queue change, including a zero-alert cleanup.

## Phase 2: Report or file fixes

### 2-1. Resolve the route

Call `describe` with the repository root. Read the scanned origin URL and visibility from
`repo.txt` and `visibility.txt`. For manual discovery, resolve both from the explicit `origin` URL
with `gh repo view`, including its `visibility` field. Normalize repository visibility to lowercase.

```bash
QUEUE="${CLAUDE_PLUGIN_ROOT}/skills/task-next/scripts/queue_backend.py"
REPO_ROOT=$(git rev-parse --show-toplevel) || exit 1
REQUEST=$(jq -n --arg repo "$REPO_ROOT" '{contract: 1, repo: $repo}') || exit 1
DESCRIBE=$(python3 "$QUEUE" describe <<<"$REQUEST") || exit 1
```

- **Report only:** if the scanned GitHub repository is `public` or `internal`, or `describe.visibility`
  is `public`, report the alerts. If either lookup fails or the scanned GitHub visibility is unknown,
  also report the lookup failure. This gate applies to every GitHub host before any queue write.
- **Private GitHub issues:** if the scanned repository and `describe.visibility` are both `private`
  and `describe.backend` is `github`, file through `create`. If the issues backend cannot confirm
  private visibility, report the alerts without filing.
- **Legacy backlog:** if the scanned repository is confirmed private and the queue uses a legacy
  route, use the existing `backlog.md` workflow.

For public results, list each alert by kind and number and give a suggested fix. Point the user to `/dev:task-new` with the kind and alert number to start a fix. Do not call `create`, save drafts, or edit `backlog.md` or `tasks.md`, even when there are zero alerts.

### 2-2. Read code context

Before writing fix tasks, read the relevant files:

- **Dependabot**: Read dependency manifests (package.json, requirements.txt, etc.) for current versions. Skip lock files. Before writing items, check for already-open Dependabot PRs: run `gh search prs --author app/dependabot --state open --repo <owner>/<repo> --limit 100 --json number,title,url` once (not per-alert), then match each alert's package name exactly (not by substring) against the package token in PR titles. Pattern details → **`${CLAUDE_PLUGIN_ROOT}/references/security-overview/api-patterns.md`** § Cross-referencing Open PRs.
- **Code Scanning**: Alerts describe the default branch, so read from it, not the working tree — a feature branch or worktree may lack a file that is still live. Alert paths are relative to the repo root. Fetch the remote's current default branch explicitly once per run — a plain `git fetch` skips it on a single-branch clone and never follows a renamed default:

  ```bash
  DEFAULT_BRANCH=$(git ls-remote --symref origin HEAD | sed -n 's|^ref: refs/heads/\(.*\)[[:blank:]]HEAD$|\1|p')
  DEFAULT_OK=no
  [[ -n "$DEFAULT_BRANCH" ]] \
    && git fetch --quiet origin "+refs/heads/${DEFAULT_BRANCH}:refs/remotes/origin/${DEFAULT_BRANCH}" \
    && git remote set-head origin "$DEFAULT_BRANCH" >/dev/null \
    && git rev-parse --verify -q "origin/HEAD^{commit}" >/dev/null \
    && DEFAULT_OK=yes
  ```

  `DEFAULT_OK` not `yes` → existence is unknown: include `(file not verified — default branch unreachable)` in the result. Otherwise, per alert, `git cat-file -e "origin/HEAD:<path>"` decides existence; when it exists, read lines `max(1, flagged_line - 5)` through `flagged_line + 5` inclusive from `git show "origin/HEAD:<path>"`. When it does not, mark it `[STALE - file deleted]` and suggest manual dismissal in the GitHub Security tab. Never dismiss via API autonomously.
- **Secret Scanning**: Note alert type and location. Do NOT read or display secret values.

### 2-3. File fixes and present the result

Follow **`${CLAUDE_PLUGIN_ROOT}/references/security-overview/backlog-template.md`** for remediation wording and the route-specific rules. Keep `tasks.md` for Sprint Contracts.

**Private GitHub issues:** check `rejected` for explicit rejections using the reference's matching rules. Build one item per remaining alert with its positive source `number`, using `gh-alert/<kind>/<number>` as the key and `["security"]` as labels. Use the kind names `dependabot`, `code-scanning`, and `secret-scanning`. Submit the items in a single `create` request to the same queue backend. The backend derives the hidden `<!-- gh-alert: <kind>/<number> -->` marker from the key and reuses an existing issue with that marker. Report new, reused, withheld, and failed or pending items. With zero eligible alerts, skip `create`. Report malformed alerts without a number and skip those items.

**Legacy backlog:** write or replace `## Security Fixes` in the current repo's `backlog.md`, following the reference's manual-edit and rejected-item rules. With zero alerts and no fetch errors, remove an existing section subject to the manual-edit check. With fetch errors and zero collected alerts, leave the section in place.

Key rules:
- Each `- [ ]` = one atomic, actionable fix.
- Order by severity: CRITICAL > HIGH > MODERATE > LOW.
- Omit empty sections.
- If an alert's package matches an open Dependabot PR, write the PR-pointer item instead of the manual upgrade item — format → backlog-template.md.
- An alert matching the repo's `## Rejected — do not re-file` entry is withheld unless its re-file bar is met; list it in the summary — backlog-template.md § Rejected Items.

After a legacy write, show the repo, `backlog.md` path, and item count. Include the Withheld line for alerts held back by `## Rejected — do not re-file`.

## Error Handling

| Condition | Action |
|-----------|--------|
| `gh` not authenticated | Stop, suggest `gh auth login` |
| Rate limited | Report progress, suggest waiting |
| Not a GitHub repo checkout | Stop, ask the user to run from the repo directory |
| Permission denied | Report which alert type was unreadable, continue with the rest |
