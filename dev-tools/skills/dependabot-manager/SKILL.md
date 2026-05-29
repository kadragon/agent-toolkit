---
name: dependabot-manager
description: >
  This skill should be used when the user asks to "manage dependabot PRs",
  "merge dependabot PRs", "clean up dependabot", "consolidate dependency PRs",
  "batch update dependencies", "too many dependabot PRs", "configure grouped updates",
  "audit dependabot config", "review dependency PRs", "check dependabot status",
  "dependabot rebase", or describes multiple open dependency-update PRs across repos
  — even without saying "dependabot" explicitly.
  NOT when: user asks only to rebase a single PR (use `@dependabot rebase` directly without invoking this skill) unless full triage is explicitly requested.
---

# Dependabot Manager

Manage dependabot PRs across all repos owned by authenticated GitHub user. Three phases: **Discovery → Triage → Action**.

Phases 1–2: `gh` CLI only (no clone). Only Phase 3 actions **3g (configure grouped updates)** and **3h (consolidate ungrouped PRs)** require a local clone; all other Phase 3 actions (merge, rebase, CI-fix, auto-merge) use `gh` CLI only.

## Phase 1: Discovery

```bash
gh search prs --author app/dependabot --state open --owner @me --json repository,number,title,url --limit 200
```

Group by repo, show count summary. None found → exit early.

## Phase 2: Triage

Triage all PRs in one pass — no per-repo agents needed:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/triage.sh \
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
bash ${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/audit-automerge.sh \
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

## Subagent Model Selection

Spawn subagents only for tasks needing read + reasoning (CI log analysis, multi-step git workflows). Scripts handle rest.

Spawn `sonnet` subagents for CI log analysis, config fix PR creation, and PR consolidation.

## Scripts

```
scripts/triage.sh            — batch triage; replaces per-repo triage agents
scripts/audit-automerge.sh   — check allow_auto_merge + branch protection per repo
scripts/enable-automerge.sh  — enable allow_auto_merge + create branch protection if missing
scripts/poll-ci.sh           — poll until all PRs reach terminal CI state (fallback)
scripts/consolidate-deps.cjs — consolidate npm/Node.js dependabot PRs
scripts/consolidate-deps.py  — consolidate Python dependabot PRs
```

Invoke via `${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/<name>`.

## Interaction

- Prose output (summaries, questions, status reports) → user's language. Technical artifacts (branch names, commit messages, PR titles, code, CLI commands) → English always.
- Errors: unauthenticated → suggest `gh auth login`; rate-limited → reduce scope; permission denied → report which repos.