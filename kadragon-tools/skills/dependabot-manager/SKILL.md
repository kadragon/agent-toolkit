---
name: dependabot-manager
description: >
  This skill should be used when the user asks to "manage dependabot PRs",
  "merge dependabot PRs", "clean up dependabot", "consolidate dependency PRs",
  "batch update dependencies", "too many dependabot PRs", "configure grouped updates",
  "audit dependabot config", "review dependency PRs", "check dependabot status",
  "dependabot rebase", or describes multiple open dependency-update PRs across repos
  — even without saying "dependabot" explicitly.
---

# Dependabot Manager

Manage dependabot PRs across all repos owned by the authenticated GitHub user in three phases: **Discovery → Triage → Action**.

Phases 1–2 operate entirely via `gh` CLI (no clone). Phase 3 actions may require local clone for config edits and consolidation.

## Phase 1: Discovery

```bash
gh search prs --author app/dependabot --state open --owner @me --json repository,number,title,url --limit 200
```

Group by repo, present count summary. If none found, exit early.

## Phase 2: Triage

Use the bundled script to triage all PRs in one pass — no per-repo agents needed:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/triage.sh \
  "owner/repo1:123" "owner/repo2:456" ...
```

The script returns a JSON array with `category` for each PR:

| Emoji | Category | Condition |
|---|---|---|
| ✅ | `ready` | CI passed + `mergeStateStatus: CLEAN` |
| 🔄 | `needs_rebase` | `CONFLICTING` or `BEHIND` |
| ❌ | `ci_failed` | Any check `FAILURE` |
| ⏳ | `ci_pending` | Checks still running |
| ⚪ | `no_ci` | No status checks configured |

Also audit dependabot config per repo (one `gh api` call each) — check for `groups:` block and `github-actions` ecosystem. Run `audit-automerge.sh` to check auto-merge readiness (`allow_auto_merge`, branch protection, required checks). See **`references/triage.md`** for details.

Present categorized results per repo with emoji prefix.

## Phase 3: Action

Present all applicable actions at once after triage — don't offer them serially one-by-one. See **`references/actions.md`** for each action's procedure.

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

**One confirmation per action class, then chain autonomously.** Once the user approves an action, complete the full pipeline without re-asking at each step.

Pause and confirm only:
- First merge of a session (e.g., "merge these N ready PRs?")
- First PR creation (e.g., "create fix PRs for these N repos?")
- Unexpected CI failure in a PR that was previously passing
- Dependabot replaced a PR with a new one (report the new PR number/scope and confirm merge)

Never pause for:
- Polling CI status
- Triggering `@dependabot rebase` after merging a CI infra fix
- Merging a PR that CI just passed as part of an already-approved pipeline
- Running `enable-automerge.sh` on individual repos after initial batch is confirmed

## Known Gotchas

- **Rebase is not automatic**: After merging a CI infra fix (e.g., Node.js version bump), Dependabot does NOT automatically rebase blocked PRs — always send `@dependabot rebase` explicitly.
- **Dependabot may replace PRs**: After a rebase, check `--author app/dependabot --state open` rather than querying original PR numbers — Dependabot sometimes closes a stale PR and creates a new one with different number and updated scope.

## Subagent Model Selection

Spawn subagents only for tasks that require reading and reasoning (CI log analysis, multi-step git workflows). Scripts handle the rest.

| Task | Model |
|------|-------|
| CI failure log analysis | `sonnet` |
| Config fix PR creation (clone + edit + push) | `sonnet` |
| PR consolidation / major bump handling | `sonnet` |

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

- Respond in the user's language; keep technical artifacts (commits, PRs, branches) in English.
- Errors: unauthenticated → suggest `gh auth login`; rate-limited → reduce scope; permission denied → report which repos.
