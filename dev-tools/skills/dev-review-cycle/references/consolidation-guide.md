# Review Consolidation Guide

Detailed procedure for consolidating multi-reviewer feedback (Step 3 of dev-review-cycle).

## Source Attribution

Step 2-1 now launches 1–N skill-based reviewers in parallel. Each sub-agent tags its findings with a `source` field (the skill `id`, e.g., `pr-review-toolkit:review-pr`, `code-review`, `security-review`). Antigravity uses source `agy`; Codex uses source `codex`.

When consolidating, preserve the source tags in the table's **Source** column. If multiple reviewers flag the same issue, merge them into one row and list all sources (e.g., `pr-review-toolkit:review-pr, codex`).

## Consolidation Procedure

All reviewers use the same P0-P3 priority scheme, making deduplication straightforward.

### 1. Deduplicate

Merge identical issues flagged by multiple reviewers into a single entry, listing all source skill ids (e.g., `pr-review-toolkit:review-pr, codex`).

### 2. Resolve Conflicts

When reviewers disagree, prefer the suggestion aligned with project conventions (CLAUDE.md / AGENTS.md). If conventions are silent, prefer the more conservative option and note the disagreement.

### 3. Categorize

Categorize each remaining suggestion: bug fix, performance, readability, style, architecture.

### 4. Discard Convention Conflicts

Remove suggestions that conflict with project conventions.

### 5. Scope Classification

For each remaining suggestion, determine whether it falls within the current PR's scope:

- **In-scope:** Issue was **introduced or made significantly worse** by this PR AND is fixable without expanding the PR's stated purpose.
- **Out-of-scope:** Issue is pre-existing in code this PR didn't touch, OR requires architectural change beyond this PR's purpose, OR is in an unchanged file.
- **Quick-win (apply as in-scope):** Pre-existing issue in an adjacent unchanged file that is a trivial 1–2 line fix and does not expand the PR's logical scope. Explicitly note it as a quick-win when classifying.

When in doubt between in-scope and out-of-scope, prefer out-of-scope — keeping PRs focused reduces review churn.

### 6. Present to User

Present the consolidated list as a table with:
- Priority (P0-P3)
- Title
- Source attribution (skill id, e.g. `pr-review-toolkit:review-pr` / `agy` / `codex`)
- Scope column (In / Out)
- Recommendation (apply / skip with reason)

After the findings table, add a "Reviewers Skipped" section listing any review candidates that were not launched, with reason (e.g., "out of scope for this diff", "exceeds 4-agent cap").

**STOP and ask the user for confirmation.** (Skip this step if `--auto` is active and proceed directly to applying in-scope changes.) The user may approve all, reject some, change scope classifications, or request modifications.

## Recording Out-of-Scope Items in tasks.md

After user confirmation, if any suggestions were classified as out-of-scope:

1. Read the existing `tasks.md` in the project root. If it does not exist, create one.
2. Append items under a `## Review Backlog` section. Classify each item using harness tags based on its nature.

### Format When a PR Exists

```markdown
## Review Backlog

### PR #<PR_NUMBER> — <PR title> (<date>)

- [ ] [debt] <suggestion summary> (source: <skill-id>) — <file:line if applicable>
- [ ] [doc] <suggestion summary> (source: <skill-id>) — <file:line if applicable>
```

### Format When `--no-hub` (No PR)

```markdown
## Review Backlog

### <FEATURE_BRANCH> — <commit summary> (<date>)

- [ ] [debt] <suggestion summary> (source: <skill-id>) — <file:line if applicable>
```

### Tag Guide

| Tag | Use for |
|-----|---------|
| `[debt]` | Code quality, refactoring |
| `[doc]` | Documentation gaps |
| `[constraint]` | Missing tests or architectural rules |
| `[harness]` | Tooling or CI improvements |

Each out-of-scope suggestion becomes a `- [ ]` item for tracking in a future cycle. If a `## Review Backlog` section already exists, append the new PR's items — do not overwrite previous entries.
