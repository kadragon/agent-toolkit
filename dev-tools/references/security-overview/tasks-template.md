# tasks.md Template and Rules

Rules and template for generating per-repo `tasks.md` files with security fix tasks.

## Target Path

Each affected repo gets its own tasks.md:

```
${WORKSPACE_DIR}/${REPO_NAME}/tasks.md
```

Where `WORKSPACE_DIR` is the **parent** of the current working directory.
Do NOT create a single consolidated file.

## Template

```markdown
## Security Fixes — <repo-name>

> Fix all open GitHub security alerts for this repository.

### Dependabot Alerts

- [ ] Upgrade <package> from <current> to <patched> (<severity>) — <advisory summary>
- [ ] Monitor <package> for patch release (<severity>) — <advisory summary> (no patched version available yet)

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

### Code Scanning Items

- Include the file path and line number.
- Read the flagged file at the reported line range (+-5 lines) to understand context.
- If the file no longer exists, use the **"Dismiss stale alert"** template.

### Secret Scanning Items

- Note the alert type and location hint.
- Do NOT read or display the secret value.
- Action is always "Revoke and rotate".

### Idempotency

If `tasks.md` already exists and contains a `## Security Fixes` section:

Before replacing: run `git log -1 --format=%ai tasks.md`. If the file was modified by a human after last scan, prompt: "tasks.md has manual edits — overwrite? [y/N]". Proceed only on "y".

On confirmation (or if no human edit detected):
- **Replace** that section with fresh scan results.
- **Preserve** all other content in the file.

This prevents duplicate entries from repeated runs.

## Example Output

```markdown
## Security Fixes — my-webapp

> Fix all open GitHub security alerts for this repository.

### Dependabot Alerts

- [ ] Upgrade express from 4.17.1 to 4.21.2 (HIGH) — Prototype Pollution in qs
- [ ] Upgrade jsonwebtoken from 8.5.1 to 9.0.0 (CRITICAL) — JWT signature bypass
- [ ] Monitor lodash for patch release (MODERATE) — ReDoS vulnerability (no patched version available yet)

### Code Scanning Alerts

- [ ] Fix js/sql-injection: SQL injection from user input — src/db/queries.js:42
- [ ] Dismiss stale alert js/xss: Cross-site scripting — src/old-handler.js (file no longer exists)
```

## Summary Format

After generating all tasks.md files, present:

```
| Repo | Path | Items |
|------|------|-------|
| my-webapp | ~/dev/my-webapp/tasks.md | 5 |
| api-server | ~/dev/api-server/tasks.md | 2 |

Total: 7 fix items across 2 repos.

Suggested next step: Open each repo directory and begin fixing the highest-severity items, or ask to work through a specific repo.
```
