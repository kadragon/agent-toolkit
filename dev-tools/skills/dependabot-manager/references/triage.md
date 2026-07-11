# Phase 2: Per-Repo Triage

All checks use `gh` CLI remotely — no local clone needed.

## 2a. Config Audit

```bash
gh api repos/{owner}/{repo}/contents/.github/dependabot.yml --jq '.content' | base64 -d
```

Check for: `groups:` block with `update-types: [minor, patch]`. Report status (configured / partial / missing / no file).

**GitHub Actions check:** If `.github/workflows/` exists, verify `package-ecosystem: "github-actions"` is in dependabot config. Actions without version tracking miss security patches — flag as warning if missing.

**404 on standard path ≠ "missing" if active dependabot PRs exist.** Before reporting `no file`, confirm with a full-tree search — the config may live at a non-standard path, or the repo may have no committed config at all (UI-only Dependabot version-updates setup):

```bash
gh api repos/{owner}/{repo}/git/trees/{default_branch}?recursive=true --jq '.tree[].path' | grep -i dependabot
```

Empty result + active dependabot PRs → report as "no committed config (possibly UI-enabled)", not a silent miss.

## 2b. PR Status Check

```bash
gh pr view {number} -R {owner}/{repo} --json number,title,mergeable,mergeStateStatus,statusCheckRollup,headRefName
```

See SKILL.md category table for the full emoji/category/condition mapping.

## 2c. Auto-Merge Readiness Audit

Run after PR triage — one call covers all repos discovered in Phase 1:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/audit-automerge.sh \
  "owner/repo1" "owner/repo2" ...
```

Output fields per repo: `allow_auto_merge`, `has_protection`, `required_checks`, `ready_for_auto_merge`, `missing`.

Report with emoji:
| Emoji | Status | Condition |
|---|---|---|
| 🟢 | Ready | `ready_for_auto_merge: true` |
| 🟡 | Partial | `allow_auto_merge` missing only |
| 🟠 | Not ready | `branch_protection` or `required_checks` missing |

## 2d. Triage Report

Present categorized results per repo with emoji prefix. For failed/rebase/no-CI items, include a detail line explaining the issue. Append auto-merge readiness after each repo block.
