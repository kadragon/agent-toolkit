---
name: dependabot-manager
description: Bulk dependabot PR triage — "manage dependabot PRs", "merge dependabot PRs", "clean up dependabot", "too many dependabot PRs", "consolidate dependency PRs", "batch update dependencies", "configure grouped updates", "audit dependabot config", "check dependabot status", "dependabot rebase", or multiple open dependency-update PRs — even without saying "dependabot". NOT for single-PR rebase only (use `@dependabot rebase`) unless full triage is also requested.
---

# Dependabot Manager

Manage dependabot PRs across all repos owned by authenticated GitHub user. Three phases: **Discovery → Triage → Action**.

Phases 1–2: `gh` CLI only (no clone). Only Phase 3 actions **3g (configure grouped updates)** and **3h (consolidate ungrouped PRs)** require a local clone; all other Phase 3 actions (merge, rebase, CI-fix, auto-merge) use `gh` CLI only.

Before executing a bundled file, resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded this turn. Use that concrete directory; do not infer it from a plugin-root environment variable.

## Phase 1: Discovery

```bash
gh search prs --author app/dependabot --state open --owner @me --json repository,number,title,url --limit 200
```

Group by repo, show count summary. None found → exit early. If returned count == 200 (the `--limit`), warn user results may be truncated — more open PRs may exist beyond this page.

## Phase 2: Triage

Triage all PRs in one pass — no per-repo agents needed:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
bash "$SKILL_DIR/scripts/triage.sh" \
  "owner/repo1:123" "owner/repo2:456" ...
```

Script returns JSON array with `category` per PR:

| Emoji | Category | Condition |
|---|---|---|
| ✅ | `ready` | CI passed + `mergeStateStatus: CLEAN` |
| 🔄 | `needs_rebase` | `CONFLICTING` or `BEHIND` |
| ❌ | `ci_failed` | Any check `FAILURE` |
| ⏳ | `ci_pending` | Checks still running |
| ⚪ | `no_ci` | No status checks configured |
| — | `closed` | PR already merged/closed — skip silently |
| — | `error` | `gh pr view` call failed — report repo:number and continue |
| — | `unknown` | `mergeStateStatus` not CLEAN/CONFLICTING/BEHIND — treat as `needs_rebase` for safety |

Also audit dependabot config per repo (one `gh api` call each) — check for `groups:` block and `github-actions` ecosystem. Then run `audit-automerge.sh` **after** `triage.sh` completes to check auto-merge readiness (`allow_auto_merge`, branch protection, required checks):

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
bash "$SKILL_DIR/scripts/audit-automerge.sh" \
  "owner/repo1" "owner/repo2" ...
```

See **`references/triage.md`** for details.

Show categorized results per repo with emoji prefix.

## Phase 3: Action

Present applicable actions at once after triage — don't offer serially. Only present actions for which triage found relevant PRs (e.g., skip "rebase stale PRs" if triage found no `needs_rebase` PRs). See **`references/actions.md`** per action procedure.

| Priority | Action | When |
|----------|--------|------|
| 1 | Batch merge ready PRs | CI passed + mergeable |
| 2 | Enable auto-merge | `ci_pending` PRs exist + repo not auto-merge ready |
| 3 | Handle major PRs | Major version bumps detected |
| 4 | Rebase stale PRs | CI passed but conflicting/behind |
| 5 | Analyze CI failures → fix pipeline | Any check failed |
| 6 | Warn about no-CI PRs | No status checks configured |
| 7 | Configure grouped updates | Missing or partial config |
| 8 | Consolidate ungrouped PRs | 3+ individual PRs, no groups |

## Autonomy Rules

**One confirmation per action class, then chain autonomously.** User approves action → complete full pipeline without re-asking.

Pause only:
- First merge of session (e.g., "merge these N ready PRs?")
- First PR creation (e.g., "create fix PRs for these N repos?")
- Unexpected CI failure on previously-passing PR
- Dependabot replaced PR (report new PR number/scope, confirm merge)

Never pause for:
- Polling CI status
- Triggering `@dependabot rebase` after merging CI infra fix
- Merging PR that CI just passed in already-approved pipeline
- Running `enable-automerge.sh` on individual repos after initial batch confirmed

## Known Gotchas

- **Rebase not automatic**: After merging CI infra fix (e.g., Node.js version bump), Dependabot does NOT auto-rebase blocked PRs — always send `@dependabot rebase` explicitly. After sending the rebase command, wait and re-list PRs (`gh pr list --author app/dependabot --state open`) until the rebased PR appears before proceeding to Phase 3 actions.
- **Dependabot may replace PRs**: After rebase, Dependabot sometimes closes the stale PR and opens a new one with a different number and updated scope. Re-list with `--author app/dependabot --state open` after rebase and confirm new PR numbers before any merge or further action — never use original PR numbers from pre-rebase triage.
- **Branch protection needs GitHub Pro on private repos**: `enable-automerge.sh` on a private repo on the free plan gets `403 Upgrade to GitHub Pro` from the protection API. The script reports `protection_action: "unsupported_plan"` and exits 0 (so a batch run survives) — but `allow_auto_merge` is on with NO required checks, so any later `gh pr merge --auto` fires immediately. Treat these repos as merge-on-manual-confirm, not auto.
- **No CI signal = same immediate-merge risk**: when `enable-automerge.sh` finds no CI checks it returns `protection_action: "skipped"` — `allow_auto_merge` on, no required checks. Identical risk to `unsupported_plan`: `--auto` would merge immediately. Treat `skipped` repos as merge-on-manual-confirm too.
- **Same-repo parallel merge causes "Base branch was modified"**: when a repo has multiple ready PRs, merging them in parallel background processes fails because the first merge advances the base branch before the second can land. Merge PRs from the **same repo sequentially**; PRs across different repos can run in parallel.
- **Deferred same-repo PRs go stale too**: the same-repo rule above only protects PRs merged *within one batch*. A PR from the same repo held back for a later action (major-bump changelog review, CI-fix queue, manual confirm) goes stale the moment any other same-repo PR merges in an earlier batch — its merge later fails with "cannot be cleanly created" / merge conflict, not just "base branch modified". Before merging any held-back PR, re-check if a same-repo PR merged since triage; if so, treat it as `needs_rebase` and send `@dependabot rebase` first rather than attempting the merge directly.

## Subagent Model Selection

Spawn subagents only for tasks needing read + reasoning (CI log analysis, multi-step git workflows). Scripts handle rest.

Spawn `sonnet` subagents for CI log analysis, config fix PR creation, and PR consolidation.

A fix subagent's analysis is a hypothesis, not a fix — it must verify against the actual failing command (re-run the failing lint/test/build to exit 0, using the tool's own migration helper for config changes) before pushing. Never push an analysis-only proposal. See `references/actions.md` §3e Step 2.

## Scripts

```
scripts/triage.sh            — batch triage; replaces per-repo triage agents
scripts/audit-automerge.sh   — check allow_auto_merge + branch protection per repo
scripts/enable-automerge.sh  — enable allow_auto_merge + create branch protection if missing
scripts/poll-ci.sh           — poll until all PRs reach terminal CI state (fallback)
scripts/consolidate-deps.cjs — consolidate npm/Node.js dependabot PRs
scripts/consolidate-deps.py  — consolidate Python dependabot PRs
```

Invoke via the concrete resolved path `$SKILL_DIR/scripts/<name>` after capturing and validating `SKILL_DIR` in the same command block.

## Interaction

- Prose output (summaries, questions, status reports) → user's language. Technical artifacts (branch names, commit messages, PR titles, code, CLI commands) → English always.
- Errors: unauthenticated → suggest `gh auth login`; rate-limited → reduce scope; permission denied → report which repos.
