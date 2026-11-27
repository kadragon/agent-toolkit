# Security Alert Filing and Templates

Use the route selected by `security-overview.md` § 2-1.

- **Public:** report the alert kind, source number, and suggested fix. Point to `/dev:task-new` with
  the kind and number. Skip all queue writes, including cleanup when no alerts are open.
- **Private GitHub issues:** use the remediation text below for the title and describe the action
  in the body. Include the alert kind and source number. File one `security` issue per alert with
  `queue_backend.py create`. For example, a Dependabot alert numbered 42 uses this item:

  ```json
  {"key":"gh-alert/dependabot/42","title":"Upgrade the affected dependency","body":"Dependabot alert #42. Upgrade to the patched version.","labels":["security"]}
  ```

  The backend adds `<!-- gh-alert: dependabot/42 -->` and reuses a matching open or closed issue
  filed by a trusted author without updating it. Use the same key on every scan. See the
  [queue contract](../../skills/task-next/references/queue-backend-contract.md) for the request
  envelope and the response fields.
- **Legacy backlog:** use the target path, template, rejected-item rules, and replacement rules
  below. Keep `tasks.md` for the current Sprint Contract.

## Target Path

The section is appended to the backlog at the root of the current repo:

```
$(git rev-parse --show-toplevel)/backlog.md
```

If the repo has no `backlog.md`, create one with a
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
- Read the flagged file at the reported line range (+-5 lines) from the default branch (fetched per `security-overview.md` § 2-1) to understand context.
- If the file no longer exists on the default branch, use the **"Dismiss stale alert"** template — a file missing only from the working tree is still live.

### Secret Scanning Items

- Note the alert type and location hint.
- Do NOT read or display the secret value.
- Action is always "Revoke and rotate".

### Rejected Items

Before writing an item, read the target `backlog.md` → `## Rejected — do not re-file`. An alert
the user already discarded (e.g. as accepted risk) is withheld unless this scan's evidence meets
that entry's re-file bar. Match only what the user rejected, never a whole package or rule:

| Alert | Matches an entry only on |
|-------|--------------------------|
| Dependabot | the same advisory ID (GHSA/CVE) |
| Code scanning | the same rule **and** file location |
| Secret scanning | the same secret type **and** location |

A severity higher than the one the entry records also meets the bar. List each withheld alert
in the summary with the entry it matched. If every alert is withheld, write no
`## Security Fixes` section — remove an existing one — and report only the Withheld line.

### Idempotency

If `backlog.md` already contains a `## Security Fixes` section:

Before replacing: run `git -C "$(git rev-parse --show-toplevel)" log -1 --format=%ai -- backlog.md`. If the file was modified by a human after last scan, prompt: "backlog.md has manual edits — overwrite? [y/N]". Proceed only on "y".

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

After updating backlog.md, present:

```
| Repo | Path | Items |
|------|------|-------|
| my-webapp | ~/dev/my-webapp/backlog.md | 5 |

Withheld (matched `## Rejected — do not re-file`): lodash GHSA-xxxx-xxxx-xxxx (MODERATE) — "accepted risk, dev-only dependency".

Suggested next step: begin fixing the highest-severity items.
```
