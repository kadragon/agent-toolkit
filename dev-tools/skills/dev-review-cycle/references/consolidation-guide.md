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

### 3. Contest Round

A bounded, single extra round for borderline-confidence findings — not an iterative convergence loop. An unbounded "iterate until findings stabilize" mechanism was considered and explicitly rejected (cost/latency); this step runs at most once per PR.

**Contestable findings** — a finding enters the contest round if its `confidence` is in the 50–74 band. Below 50 stays auto-dropped in Step 4 — no meaningful signal worth contesting.

(An earlier draft of this trigger also fired on "disputed" findings — flagged by one source but supposedly covered by another. Dropped: no reviewer in this pipeline reports which files it examined, only which files it flagged — see SKILL.md Step 2-1's findings-only JSON contract and the free-form prose agy/Codex emit. Without coverage data, "disputed" could only be evaluated by guessing, which this repo's own agent-integrity rule forbids. The confidence-band trigger alone uses only data the reviewers actually emit.)

Findings already resolved by the P0/P1 verifier gate (Section 2 of this guide) do NOT enter the contest round — the two gates target disjoint severities (P0/P1 vs the 50–74 confidence band) and never compete for the same finding, so they can run in parallel (see SKILL.md Step 3).

**Mechanic — one batched agent call, no loop:**
- Collect ALL contestable findings from the PR into a single list. If the list is empty, skip the round entirely — do not spawn an agent for zero work.
- Otherwise spawn exactly one fresh sub-agent for the whole batch (not one agent per finding), using the same `run_in_background: true` pattern and Sonnet model as the P0/P1 verifier gate (SKILL.md Step 3).
- Prompt: give the agent the diff and the full list of contestable findings; ask it to argue for or against each, independent of the original reviewer's framing ("is this a real issue introduced by this diff — yes/no — with file:line evidence"). Fresh eyes, same principle as the P0/P1 verifier.
- This is a single round. It does not iterate until findings stabilize — do not re-run it, and do not spawn a second contest round even if the agent's verdicts seem uncertain.

**Outcome routing:**
- `confirmed` → promote into the normal action table alongside other findings, tagged in the Verdict column (e.g. `contest-confirmed`) so the user can see it was upgraded via the contest round.
- `refuted` → route to a "Refuted by contest round" section in the Step 10 output (mirrors "Refuted by verifier"), visible so the user can override — never silently dropped.

### 4. Drop Low-Confidence and Excluded Findings

Reviewers emit a `confidence` score (0–100) per finding. Findings in the 50–74 band were already routed through the Contest Round (Step 3) — confirmed ones are already in the action table, refuted ones are already in the "Refuted by contest round" section. What's left here is confidence below 50: drop these from the action table — list them in a collapsed "Low confidence (not actioned)" note instead, so the signal isn't silently lost. Also drop findings a reviewer itself hedged as speculative or unconfirmed regardless of score. The reviewer's own hedging is a signal — if it isn't confident, the consolidator shouldn't absorb the uncertainty into the output.

Also drop findings in these excluded categories — surfacing them adds noise without actionable value:

- **Purely theoretical risk** — DoS, timing attacks, resource exhaustion with no practical exploit path in this context
- **Style owned by a linter** — formatting, naming conventions, import order if a linter config already covers them
- **Missing rate limiting, audit logs, or monitoring** — absence of defence-in-depth features is a product decision, not a code defect
- **Third-party library vulnerabilities** — out of scope for a PR review; handle via Dependabot or a separate audit
- **Issues in test files** unless the test itself is wrong (e.g., a test that asserts nothing)
- **Documentation gaps in files this PR didn't touch**

These categories exist because every reviewer has a tendency to surface low-confidence, catch-all patterns. Dropping them at consolidation keeps the output focused on what the engineer can and should act on now.

### 5. Resolve Conflicts

When reviewers disagree, prefer the suggestion aligned with project conventions (CLAUDE.md / AGENTS.md). If conventions are silent, prefer the more conservative option and note the disagreement.

### 6. Categorize

Categorize each remaining suggestion: bug fix, performance, readability, style, architecture.

### 7. Discard Convention Conflicts

Remove suggestions that conflict with project conventions.

### 8. Scope Classification

For each remaining suggestion, determine whether it falls within the current PR's scope:

- **In-scope:** Issue was **introduced or made significantly worse** by this PR AND is fixable without expanding the PR's stated purpose.
- **Out-of-scope:** Issue is pre-existing in code this PR didn't touch, OR requires architectural change beyond this PR's purpose, OR is in an unchanged file.

When in doubt between in-scope and out-of-scope, prefer out-of-scope — keeping PRs focused reduces review churn.

### 9. Apply / Skip Gate

All in-scope findings are applied before merge, regardless of severity. Sort by severity so critical items are addressed first:

- **P0 / P1 (correctness bugs, concrete security risk, broken tests)** — must be resolved before merge. These are findings with a clear, demonstrable path to breakage or exploit.
- **P2 / P3 (readability, style, minor improvements, low-confidence concerns)** — apply inline along with P0/P1. The reviewer already reviewed this PR's files — fixing while context is live is cheaper than deferring.

### 10. Present to User

Present the consolidated list as a table with:
- Priority (P0-P3) — rows sorted by severity (P0 first) so critical items are visible at the top
- Title
- Source attribution (skill id, e.g. `pr-review-toolkit:review-pr` / `agy` / `codex`)
- Verdict column: `confirmed` / `uncertain` for P0/P1 candidates (from the verifier gate); `contest-confirmed` for any severity upgraded via the Contest Round
- Scope column (In / Out)
- Gate column (Apply / Skip) — Apply = in-scope (all severities); Skip = out-of-scope
- Recommendation (apply / skip with reason)

After the findings table, add:
- A "Refuted by verifier" section listing P0/P1 candidates the verifier rejected, with its one-line evidence — visible so the user can override a wrong refutation.
- A "Refuted by contest round" section listing contestable findings (Step 3) the contest round rejected, with its one-line evidence — visible so the user can override a wrong refutation.
- A "Reviewers Skipped" section listing any review candidates that were not launched, with reason (e.g., "trivial diff — single reviewer sufficient", "out of scope for this diff", "exceeds 4-agent cap").

**STOP and ask the user for confirmation.** (Skip this step if `--auto` is active and proceed directly to applying all in-scope changes.) The user may approve all, reject some, change scope classifications, or request modifications.

## Recording Backlog Items in tasks.md

After user confirmation, route to `tasks.md`: all out-of-scope findings only.

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
