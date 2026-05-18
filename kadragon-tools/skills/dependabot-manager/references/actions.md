# Phase 3: Actions

Present all applicable actions at once. One confirmation per action class, then execute the full pipeline autonomously — see Autonomy Rules in SKILL.md.

## 3a. Batch Merge Ready PRs

Offer to merge all ready PRs in one shot:

```bash
gh pr merge {number} -R {owner}/{repo} --squash
```

## 3b. Enable Auto-Merge

**When:** any repo has `ci_pending` PRs AND `ready_for_auto_merge: false` from the Phase 2 audit.

### Step 1: Confirm once

Show the user the affected repos and their `missing` items. One confirmation covers all repos — then proceed autonomously.

### Step 2: Enable per repo (parallel)

For each repo needing activation, run:

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/enable-automerge.sh "owner/repo"
```

Interpret `protection_action`:
- `created` — branch protection added with detected CI check names; report contexts.
- `already_present` — protection exists; `allow_auto_merge` toggled, nothing else changed.
- `skipped` — no CI signal found. Warn: "auto-merge may fire immediately without required checks — consider adding branch protection manually."

### Step 3: Apply `--auto` to ci_pending PRs

For each `ci_pending` dependabot PR in repos that now have auto-merge enabled:

```bash
gh pr merge {number} -R {owner}/{repo} --auto --squash
```

Skip: `ci_failed`, `needs_rebase`, `no_ci` (unsafe — would merge without checks or needs rebase first).

### Step 4: Report

```
✅ Auto-merge enabled: N repos
🔀 --auto set on: M PRs (will merge when CI passes)
⚠️  Skipped (skipped protection): repo-a — add branch protection to avoid immediate merge
```

No further polling needed for these PRs — they will merge on their own when CI finishes.

---

## 3c. Handle Multiple Major PRs

Detect major PRs by title (major version number differs). Merging one makes others go behind, creating a serial bottleneck.

- **2 or fewer major PRs** — sequential merge + `@dependabot rebase` on remaining
- **3+ major PRs** — offer consolidated branch (`chore/major-dependency-updates`): apply all bumps together, create single PR, close originals with `gh pr close --comment "Included in #{consolidated_pr}"`

## 3d. Handle Rebase-Needed PRs (non-major)

Comment `@dependabot rebase` on each:

```bash
gh pr comment {number} --repo {owner}/{repo} --body "@dependabot rebase"
```

## 3e. CI Failure Analysis + Fix Pipeline

### Step 1: Analyze

Get failed job logs:

```bash
gh run list --repo {owner}/{repo} --branch {head-branch} --limit 3 --json databaseId,name,conclusion
gh run view {run-id} --repo {owner}/{repo} --log-failed 2>&1 | head -100
```

Spawn parallel `sonnet` subagents for repos with different failure patterns. For repos with the same root cause, analyze one and apply the pattern to the rest.

Common failure patterns:

| Pattern | Likely cause |
|---------|-------------|
| Runtime version mismatch | Tool upgraded its minimum engine requirement (e.g., wrangler requires Node 22) |
| Type errors | Breaking API change in dependency |
| Test failures | Behavioral change in dependency |
| Build failures | Peer dependency mismatch |
| Lint failures | New rules introduced by dependency |

### Step 2: Fix Pipeline (once user approves fix approach)

After the user confirms the fix strategy, execute this pipeline autonomously without re-asking:

1. **Create fix PRs** — spawn `sonnet` subagents in parallel, one per repo needing the fix
2. **Poll CI on fix PRs**:
   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/poll-ci.sh \
     --timeout 600 "owner/repo1:{fix-pr}" "owner/repo2:{fix-pr}" ...
   ```
3. **Merge fix PRs** — once all show `ready`:
   ```bash
   gh pr merge {fix-pr} --repo {owner}/{repo} --squash
   ```
4. **Trigger rebase on blocked dependabot PRs** — always do this explicitly; Dependabot does not auto-rebase after an infra fix:
   ```bash
   gh pr comment {dep-pr} --repo {owner}/{repo} --body "@dependabot rebase"
   ```
5. **Re-list open dependabot PRs** — Dependabot may close the original and open a new PR with a different number:
   ```bash
   gh pr list --repo {owner}/{repo} --author app/dependabot --state open --json number,title,url
   ```
6. **Poll CI on rebased dependabot PRs**:
   ```bash
   bash ${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/poll-ci.sh \
     --timeout 600 "owner/repo1:{new-dep-pr}" ...
   ```
7. **Merge dependabot PRs** — once all show `ready`. If auto-merge is enabled for the repo (see 3b), apply `gh pr merge --auto --squash` and skip the polling step; the merge fires automatically when CI passes.
8. **Report completion**

## 3f. Handle No-CI PRs

Warn that merging without CI is risky. If user proceeds, confirm per PR (not batch).

## 3g. Configure Grouped Updates

For repos missing grouped updates or `github-actions` ecosystem, offer to configure. Create branch `chore/configure-dependabot-grouped-updates`, add config:

```yaml
groups:
  dependencies:
    patterns: ["*"]
    update-types: ["minor", "patch"]
```

If repo uses Actions but lacks `github-actions` ecosystem, also add:

```yaml
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      actions:
        patterns: ["*"]
        update-types: ["minor", "patch"]
```

## 3h. Consolidate Ungrouped PRs (Fallback)

For repos with 3+ individual PRs and no grouped updates, offer consolidation using bundled scripts:

- **npm**: `${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/consolidate-deps.cjs`
- **Python**: `${CLAUDE_PLUGIN_ROOT}/skills/dependabot-manager/scripts/consolidate-deps.py`
- **Other ecosystems**: Manual workflow via Edit tool. Requires local clone.

Both scripts: fetch dependabot PRs → parse versions → create branch → apply bumps → test → commit → push → create consolidated PR → close originals.
