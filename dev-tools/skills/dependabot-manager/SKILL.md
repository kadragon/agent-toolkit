---
name: dependabot-manager
description: Bulk dependabot PR triage — "manage dependabot PRs", "merge dependabot PRs", "clean up dependabot", "too many dependabot PRs", "consolidate dependency PRs", "batch update dependencies", "configure grouped updates", "audit dependabot config", "check dependabot status", "dependabot rebase", or multiple open dependency-update PRs — even without saying "dependabot". NOT for single-PR rebase only (use `@dependabot rebase`) unless full triage is also requested.
---

# Dependabot Manager

Manage dependabot PRs across all repos owned by authenticated GitHub user. Three phases: **Discovery → Triage → Action**.

Phases 1–2 and most of Phase 3 use `gh` CLI only, no clone — only **3g** (configure grouped updates) and **3h** (consolidate ungrouped PRs) need one.

**Setup** (once per session, before any bundled script): resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded this turn — don't infer it from a plugin-root env var.
```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
```

## Phase 1: Discovery

```bash
gh search prs --author app/dependabot --state open --owner @me --json repository,number,title,url --limit 200
```

Group by repo, show count summary. None found → exit early. Count == 200 (the `--limit`) → warn results may be truncated.

## Phase 2: Triage

```bash
bash "$SKILL_DIR/scripts/triage.sh" "owner/repo1:123" "owner/repo2:456" ...
```

Returns a JSON array with `category` per PR:

| Emoji | Category | Condition |
|---|---|---|
| ✅ | `ready` | CI passed + `mergeStateStatus: CLEAN` |
| 🔄 | `needs_rebase` | `CONFLICTING` or `BEHIND` |
| ❌ | `ci_failed` | Any check `FAILURE` |
| ⏳ | `ci_pending` | Checks still running |
| ⚪ | `no_ci` | No status checks configured |
| — | `closed` / `error` / `unknown` | Skip / report and continue / treat as `needs_rebase` |

Also audit dependabot config per repo (`groups:` block, `github-actions` ecosystem present?). Then, **after** triage, check auto-merge readiness:

```bash
bash "$SKILL_DIR/scripts/audit-automerge.sh" "owner/repo1" "owner/repo2" ...
```

See **`references/triage.md`** for field details. Show categorized results per repo with emoji prefix.

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

Rebase timing, PR replacement, auto-merge risk tiers, same-repo merge ordering, and major/grouped-PR peer-dep deadlocks — see **`references/gotchas.md`** before any merge/rebase/auto-merge action.

## Subagents

Spawn `sonnet` subagents only for read+reasoning work (CI log analysis, fix-PR creation, consolidation) — scripts handle the rest. A subagent's fix is a hypothesis, not a fix: it must re-run the actual failing command and confirm exit 0 before pushing. Never push an analysis-only proposal. See `references/actions.md` §3e Step 2.

## Scripts

```
scripts/triage.sh            — batch triage; replaces per-repo triage agents
scripts/audit-automerge.sh   — check allow_auto_merge + branch protection per repo
scripts/enable-automerge.sh  — enable allow_auto_merge + create branch protection if missing
scripts/poll-ci.sh           — poll until all PRs reach terminal CI state (fallback)
scripts/consolidate-deps.cjs — consolidate npm/Node.js dependabot PRs
scripts/consolidate-deps.py  — consolidate Python dependabot PRs
```

Invoke as `$SKILL_DIR/scripts/<name>` (see Setup above).

## Interaction

- Prose output (summaries, questions, status reports) → user's language. Technical artifacts (branch names, commit messages, PR titles, code, CLI commands) → English always.
- Errors: unauthenticated → suggest `gh auth login`; rate-limited → reduce scope; permission denied → report which repos.
