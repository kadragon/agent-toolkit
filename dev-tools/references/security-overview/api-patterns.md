# GitHub Security API Patterns

Detailed API usage patterns for the three GitHub security alert types. Consult this when
customizing queries, debugging API responses, or handling edge cases.

## Dependabot — GraphQL

The GraphQL approach fetches all repos + alerts in a single paginated call, avoiding per-repo REST overhead.

### Query Structure

```graphql
{
  viewer {
    repositories(first: 100, ownerAffiliations: OWNER) {
      nodes {
        name
        url
        vulnerabilityAlerts(first: 100, states: OPEN) {
          totalCount
          nodes {
            securityVulnerability {
              package { name ecosystem }
              severity
              advisory { summary ghsaId }
              firstPatchedVersion { identifier }
            }
          }
        }
      }
    }
  }
}
```

### Key Fields

| Field | Purpose |
|-------|---------|
| `severity` | CRITICAL, HIGH, MODERATE, LOW |
| `package.name` / `ecosystem` | Affected dependency and ecosystem (npm, pip, etc.) |
| `advisory.ghsaId` | Unique advisory identifier for linking |
| `firstPatchedVersion.identifier` | Target version to upgrade to; **null** = no fix yet |

### Pagination

`gh api graphql --paginate` handles cursor-based pagination automatically. Each page returns up to 100 repos. For accounts with >100 repos, multiple pages are fetched transparently.

### Common Issues

- **Empty `vulnerabilityAlerts`**: Repo may have Dependabot disabled or no supported manifest.
- **`firstPatchedVersion` is null**: No fix available. Task item should use "Monitor" template.

## Cross-referencing Open PRs

Before writing a manual "Upgrade" task, check whether an open Dependabot PR already covers the alert's package. One call per affected repo (the set from Phase 1), not all repos.

### Query Structure

```bash
gh search prs --author app/dependabot --state open --repo "${OWNER}/${REPO}" \
  --json number,title,url
```

### Response Fields

| Field | Purpose |
|-------|---------|
| `number` | PR number, used in the pointer item |
| `title` | Match against alert's package name (substring match) |
| `url` | PR URL, used in the pointer item |

### Matching Logic

Dependabot PR titles follow `bump <package> from X to Y` (Go/JS ecosystems) or `build(deps): bump <package> ...` (Actions/other configs) conventions. Substring-match the alert's `securityVulnerability.package.name` against `title` — no need for exact semver comparison. First match wins.

### Common Issues

- **Title format varies by ecosystem/config**: some configs prefix with `build(deps):` or `build(deps-dev):`, others don't. Substring match on package name tolerates this.
- **Closed/merged PRs must not match**: `--state open` already excludes these; do not drop the flag.
- **Rate limits**: run once per affected repo (already scoped by Phase 1), never per-alert — an N+1 pattern here burns REST quota fast.

## Code Scanning — REST

```bash
gh api "repos/${OWNER}/${REPO}/code-scanning/alerts?state=open&per_page=100"
```

### Response Fields

| Field | Purpose |
|-------|---------|
| `rule.id` | Rule identifier (e.g., `js/sql-injection`) |
| `rule.description` | Human-readable rule description |
| `rule.severity` | error, warning, note |
| `most_recent_instance.location.path` | File path |
| `most_recent_instance.location.start_line` | Line number |
| `tool.name` | Scanner tool (CodeQL, etc.) |

### Severity Mapping

CodeQL returns `rule.severity` as `error`, `warning`, or `note`. Map to tasks.md severity labels as follows:

| `rule.severity` | tasks.md severity | Notes |
|-----------------|-----------------|-------|
| `error` | CRITICAL | Code injection, auth bypass, or similar high-impact issues |
| `error` | HIGH | All other `error`-level rules not matching CRITICAL criteria |
| `warning` | MODERATE | |
| `note` | LOW | |

Use CRITICAL for `error`-severity rules whose `rule.id` or `rule.description` relates to injection, authentication, authorization, or remote code execution. Use HIGH for all other `error`-severity rules.

### Error Handling

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 200 | Success | Process alerts |
| 403 | Code scanning not enabled | Record as "not enabled", skip |
| 404 | Repository not found or no analysis | Record as "not enabled", skip |
| 503 | Service unavailable | Retry once after 5s |

### Empty vs Disabled

An empty array `[]` means code scanning is enabled but found no alerts. A 403/404 means it is not configured.

## Secret Scanning — REST

```bash
gh api "repos/${OWNER}/${REPO}/secret-scanning/alerts?state=open&per_page=100" \
  --jq '[.[] | del(.secret)]'
```

**Critical**: Always strip the `.secret` field with `del(.secret)` to prevent leaking credential values into context.

### Response Fields

| Field | Purpose |
|-------|---------|
| `secret_type` | Type of secret (e.g., `github_personal_access_token`) |
| `secret_type_display_name` | Human-readable type name |
| `locations_url` | API URL to fetch where the secret was found |
| `state` | open, resolved |
| `resolution` | null, false_positive, revoked, used_in_tests, pattern_edited |

### Error Handling

| HTTP Status | Meaning | Action |
|-------------|---------|--------|
| 200 | Success | Process alerts (strip secrets) |
| 404 | Secret scanning disabled or not available | Record as "not enabled", skip |

## Rate Limiting

GitHub API has rate limits:
- **GraphQL**: 5,000 points/hour (the Dependabot query uses ~1 point per page)
- **REST**: 5,000 requests/hour

For accounts with many repos, Code Scanning + Secret Scanning REST calls may approach limits (2 calls per repo). If rate-limited:
1. Report which repos were completed
2. Suggest waiting or reducing scope to repos with known alerts
