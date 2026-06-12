# Review Consolidation Guide

Detailed procedure for consolidating multi-reviewer feedback (Step 3 of dev-review-cycle).

## Source Attribution

Step 2-1 now launches 1–N skill-based reviewers in parallel. Each sub-agent tags its findings with a `source` field (the skill `id`, e.g., `pr-review-toolkit:review-pr`, `code-review`, `security-review`). Antigravity uses source `agy`; Codex uses source `codex`.

When consolidating, preserve the source tags in the table's **Source** column. If multiple reviewers flag the same issue, merge them into one row and list all sources (e.g., `pr-review-toolkit:review-pr, codex`).

## Consolidation Procedure

All reviewers use the same P0-P3 priority scheme, making deduplication straightforward.

### 1. Deduplicate

Merge identical issues flagged by multiple reviewers into a single entry, listing all source skill ids (e.g., `pr-review-toolkit:review-pr, codex`).

### 2. Re-verify Against the Diff

This is the step where the orchestrator earns its keep. The delegated reviewers never cross-check each other — a pattern match in one reviewer can be surfaced as a finding without any confirming signal from the others.

Verification has two tiers:

- **P0/P1 candidates → independent verifier agent.** Self-checking your own consolidation absorbs the reviewers' bias; an agent with fresh context and Read/Grep access re-checks each candidate at its file:line, confirms it was introduced by this branch, and returns `confirmed | refuted | uncertain` verdicts with evidence. (Procedure and prompt are in SKILL.md Step 3 — the verifier gate.) Refuted findings go to a "Refuted by verifier" section in the output, not the action table.
- **P2/P3 candidates → inline re-read.** Re-read the actual diff lines referenced by each merged finding yourself and verify the issue is real in *this* code. A separate agent for nits is not worth the cost.

Drop a finding if:
- The flagged line was not actually changed by this PR (pre-existing; landed here by file name only)
- The reviewer's concern doesn't apply to the specific pattern in the code (e.g., flagged "no error handling" on a function that explicitly returns an error value)
- The concern is theoretical and has no concrete path to harm given the actual call context

Keep findings that survive direct inspection. A finding with a concrete file:line in the diff and a clear mechanism is worth surfacing. A plausible-sounding pattern match without a traceable path is not.

### 3. Drop Low-Confidence and Excluded Findings

Reviewers emit a `confidence` score (0–100) per finding. Drop findings with confidence below 75 from the action table — list them in a collapsed "Low confidence (not actioned)" note instead, so the signal isn't silently lost. Also drop findings a reviewer itself hedged as speculative or unconfirmed regardless of score. The reviewer's own hedging is a signal — if it isn't confident, the consolidator shouldn't absorb the uncertainty into the output.

Also drop findings in these excluded categories — surfacing them adds noise without actionable value:

- **Purely theoretical risk** — DoS, timing attacks, resource exhaustion with no practical exploit path in this context
- **Style owned by a linter** — formatting, naming conventions, import order if a linter config already covers them
- **Missing rate limiting, audit logs, or monitoring** — absence of defence-in-depth features is a product decision, not a code defect
- **Third-party library vulnerabilities** — out of scope for a PR review; handle via Dependabot or a separate audit
- **Issues in test files** unless the test itself is wrong (e.g., a test that asserts nothing)
- **Documentation gaps in files this PR didn't touch**

These categories exist because every reviewer has a tendency to surface low-confidence, catch-all patterns. Dropping them at consolidation keeps the output focused on what the engineer can and should act on now.

### 4. Resolve Conflicts

When reviewers disagree, prefer the suggestion aligned with project conventions (CLAUDE.md / AGENTS.md). If conventions are silent, prefer the more conservative option and note the disagreement.

### 5. Categorize

Categorize each remaining suggestion: bug fix, performance, readability, style, architecture.

### 6. Discard Convention Conflicts

Remove suggestions that conflict with project conventions.

### 7. Scope Classification

For each remaining suggestion, determine whether it falls within the current PR's scope:

- **In-scope:** Issue was **introduced or made significantly worse** by this PR AND is fixable without expanding the PR's stated purpose.
- **Out-of-scope:** Issue is pre-existing in code this PR didn't touch, OR requires architectural change beyond this PR's purpose, OR is in an unchanged file.

When in doubt between in-scope and out-of-scope, prefer out-of-scope — keeping PRs focused reduces review churn.

### 8. Apply Approval-Bias Gate

Not every in-scope finding should block the merge. Sort by whether it gates forward motion:

- **P0 / P1 (correctness bugs, concrete security risk, broken tests)** — must be resolved before merge. These are findings with a clear, demonstrable path to breakage or exploit.
- **P2 / P3 (readability, style, minor improvements, low-confidence concerns)** — do NOT apply inline; route to `tasks.md` as backlog items. A PR with only P2/P3 in-scope findings is effectively approved.

The reason for this asymmetry: blocking a clean PR on a P3 nit forces the engineer to touch unrelated code, creates merge-conflict risk, and makes the review cycle feel punishing. P2/P3 findings are real and worth tracking — `tasks.md` ensures they're not forgotten — but they don't belong between the PR and the merge button.

### 9. Present to User

Present the consolidated list as a table with:
- Priority (P0-P3)
- Title
- Source attribution (skill id, e.g. `pr-review-toolkit:review-pr` / `agy` / `codex`)
- Verdict column for P0/P1 (confirmed / uncertain — from the verifier gate)
- Scope column (In / Out)
- Gate column (Blocking / Backlog) — Blocking = P0/P1 in-scope; Backlog = P2/P3 in-scope or out-of-scope
- Recommendation (apply / skip with reason)

After the findings table, add:
- A "Refuted by verifier" section listing P0/P1 candidates the verifier rejected, with its one-line evidence — visible so the user can override a wrong refutation.
- A "Reviewers Skipped" section listing any review candidates that were not launched, with reason (e.g., "trivial diff — single reviewer sufficient", "out of scope for this diff", "exceeds 4-agent cap").

**STOP and ask the user for confirmation.** (Skip this step if `--auto` is active and proceed directly to applying blocking changes.) The user may approve all, reject some, change scope classifications, or request modifications.

## Recording Backlog Items in tasks.md

After user confirmation, route to `tasks.md`: all out-of-scope findings AND all in-scope P2/P3 findings.

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

Each backlog suggestion becomes a `- [ ]` item for tracking in a future cycle. If a `## Review Backlog` section already exists, append the new PR's items — do not overwrite previous entries.
