# backlog.md Template and Rules

Rules and template for appending a security-fix section to each affected repo's `backlog.md`.

Findings outlive the cycle that produced them, so they belong in `backlog.md` — the repo's only
persistent queue. Never write them to `tasks.md`: that file is the current Sprint Contract and is
deleted whole at sprint close, and `task_nodes.py prune-tasks` refuses to run against a `tasks.md`
holding a `## Security Fixes` section.

## Target Path

The section is appended to each affected repo's own backlog:

```
${WORKSPACE_DIR}/${REPO_NAME}/backlog.md
```

Where `WORKSPACE_DIR` is the **parent** of the current working directory.
Do NOT create a single consolidated file. If a repo has no `backlog.md`, create one with a
`# Backlog` heading, then append the section below it.

## Template

```markdown
## Security Fixes — <repo-name>

> Fix all open GitHub security alerts for this repository.

### Dependabot Alerts

- [ ] Upgrade <package> from <current> to <patched> (<severity>) — <advisory summary>
- [ ] Monitor <package> for patch release (<severity>) — <advisory summary> (no patched version available yet)
- [ ] PR #<number> already open for <package> — use repo-dependabot to triage/merge (<url>)

### Code Scanning Alerts

- [ ] Fix <rule-id>: <description> — <file>:<line>
- [ ] Dismiss stale alert <rule-id>: <description> — file no longer exists

### Secret Scanning Alerts

- [ ] Revoke and rotate <secret-type> — <location hint>
```

## Rules

### General

- Each `- [ ]` is one atomic, actionable fix.
- Omit empty sections (skip "Secret Scanning Alerts" if there are none).
- Order items by severity within each section: CRITICAL > HIGH > MODERATE > LOW.

### Dependabot Items

- Include the specific version to upgrade to (from `firstPatchedVersion`).
- If `firstPatchedVersion` is null, use the **"Monitor"** template instead of "Upgrade".
- Read the dependency manifest (package.json, requirements.txt, pyproject.toml, go.mod, etc.) to determine the current version. Do NOT read lock files.
- If an open Dependabot PR matches the package name exactly (see api-patterns.md § Cross-referencing Open PRs), use the **"PR already open"** template instead of "Upgrade"/"Monitor". Otherwise fall back to the existing Upgrade/Monitor logic.

### Code Scanning Items

- Include the file path and line number.
- Read the flagged file at the reported line range (+-5 lines) to understand context.
- If the file no longer exists, use the **"Dismiss stale alert"** template.

### Secret Scanning Items

- Note the alert type and location hint.
- Do NOT read or display the secret value.
- Action is always "Revoke and rotate".

### Idempotency

If `backlog.md` already contains a `## Security Fixes` section:

Before replacing: run `git log -1 --format=%ai backlog.md`. If the file was modified by a human after last scan, prompt: "backlog.md has manual edits — overwrite? [y/N]". Proceed only on "y".

On confirmation (or if no human edit detected):
- **Replace** that section with fresh scan results.
- **Preserve** all other content in the file — other `##` groups and `## Review Backlog` findings
  live in the same file and must survive untouched.

This prevents duplicate entries from repeated runs.

## Example Output

```markdown
## Security Fixes — my-webapp

> Fix all open GitHub security alerts for this repository.

### Dependabot Alerts

- [ ] Upgrade jsonwebtoken from 8.5.1 to 9.0.0 (CRITICAL) — JWT signature bypass
- [ ] PR #42 already open for express — use repo-dependabot to triage/merge (https://github.com/kadragon/my-webapp/pull/42)
- [ ] Monitor lodash for patch release (MODERATE) — ReDoS vulnerability (no patched version available yet)

### Code Scanning Alerts

- [ ] Fix js/sql-injection: SQL injection from user input — src/db/queries.js:42
- [ ] Dismiss stale alert js/xss: Cross-site scripting — src/old-handler.js (file no longer exists)
```

## Summary Format

After updating all backlog.md files, present:

```
| Repo | Path | Items |
|------|------|-------|
| my-webapp | ~/dev/my-webapp/backlog.md | 5 |
| api-server | ~/dev/api-server/backlog.md | 2 |

Total: 7 fix items across 2 repos.

Suggested next step: Open each repo directory and begin fixing the highest-severity items, or ask to work through a specific repo.
```
