# Phase 3: Actions

Present all applicable actions at once. One confirmation per action class, then execute the full pipeline autonomously — see Autonomy Rules in SKILL.md.

## 3a. Batch Merge Ready PRs

Offer to merge all ready PRs in one shot. Do **not** use `--auto` — these PRs are already CLEAN; `--auto` is only for `ci_pending` PRs. If `--auto` is used on a CLEAN PR, it fires immediately with no additional CI gating.

**Execution order:**
- PRs across **different repos** → run in parallel (background `&` + `wait`)
- Multiple PRs in the **same repo** → run sequentially (parallel causes "Base branch was modified" failure)

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
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/enable-automerge.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/enable-automerge.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/enable-automerge.sh" "owner/repo"
```

Interpret `protection_action`:
- `created` — branch protection added with detected CI check names; report contexts.
- `already_present` — protection exists; `allow_auto_merge` toggled, nothing else changed.
- `skipped` — no CI signal found. Warn: "auto-merge may fire immediately without required checks — consider adding branch protection manually."
- `unsupported_plan` — branch protection unavailable (private repo on free plan). `allow_auto_merge` is on but NO required checks exist. Do NOT apply `--auto` — treat as merge-on-manual-confirm.

### Step 3: Apply `--auto` to ci_pending PRs

For each `ci_pending` dependabot PR in repos that now have auto-merge enabled.
**Exclude repos that returned `skipped` or `unsupported_plan`** — they have no required checks, so `--auto` would merge immediately. Merge those only on manual confirm.

```bash
gh pr merge {number} -R {owner}/{repo} --auto --squash
```

Skip: `ci_failed`, `needs_rebase`, `no_ci` (unsafe — would merge without checks or needs rebase first). Also skip PRs in `skipped` / `unsupported_plan` repos.

### Step 4: Report

```
✅ Auto-merge enabled: N repos
🔀 --auto set on: M PRs (will merge when CI passes)
⚠️  Skipped (skipped protection): repo-a — add branch protection to avoid immediate merge
⚠️  Unsupported plan (free-plan private repo): repo-b — merge on manual confirm, --auto not applied
```

No further polling needed for these PRs — they will merge on their own when CI finishes.

---

## 3c. Handle Multiple Major PRs

Detect major PRs by title (major version number differs). Merging one makes others go behind, creating a serial bottleneck.

### Step 0: Check changelog before merge decision

For each major PR, resolve the **dependency's** source repo and fetch its release notes.
`repos/{owner}/{repo}` is the *app* repo — not the dependency — so always derive `dep_repo` first.

**Resolve `dep_repo`:**
Extract the dependency name from the PR title (e.g. `Bump actions/checkout from 3 to 4` → `actions/checkout`).
For GitHub Actions: `dep_repo` is the action slug directly (`{owner}/{action-name}`).
For npm packages: check `package.json` → `.repository.url`.
For PyPI packages: check `pyproject.toml` → `[project.urls] Repository`, or `setup.cfg` → `[metadata] url`.
Alternatively, use the PR body's "Release notes" / "Commits" link — both include a GitHub URL when available.
If `dep_repo` cannot be resolved, skip this step and note it to the user — do not silently return empty data.

```bash
dep_repo="<resolved-owner>/<resolved-repo>"   # replace with actual repo slug derived above
gh api "repos/$dep_repo/releases" --jq '.[0:3] | .[] | {tag: .tag_name, body: (.body // "" | .[0:500])}'
```

Report to user:
- **Breaking changes** (API removals, dropped runtime support, required migrations)
- **Runtime requirement changes** (e.g., Node.js minimum version bump) — cross-check against repo's CI workflow and `engines` field in `package.json`

Present findings before proposing merge or consolidation. User decides whether to proceed.

### Merge strategy

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

**Analysis alone is not a fix — it is a hypothesis.** Reading logs and the dependency changelog tells you what *probably* broke, but the new tool version is the only authority on its own config schema and rule set. A confident, well-reasoned proposal can still be wrong: a config key placed at the wrong nesting level, or a real error masked behind the one you spotted. So whoever applies the fix must verify it against the actual tool (see Step 2) before pushing — never push an analysis-only proposal.

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

1. **Create fix PRs** — spawn `sonnet` subagents in parallel, one per repo needing the fix. **The subagent must verify the fix against the real tool before pushing**, using the failing job's own command (from the workflow YAML) as the exit criterion:
   - For config/schema migrations, run the upgraded tool's own migration helper when it has one (e.g. `biome migrate --write`, `eslint --migrate`) rather than hand-editing — the tool writes the canonical config and won't guess the wrong key level.
   - Re-run the **exact failing command** (e.g. `bun run lint`, `npm test`) against the new dependency version and confirm it exits 0. A clean migration can still leave a real error the analysis missed (e.g. a rule promoted to error-level in the new major) — that error must be resolved too, not just the config.
   - Only push once the failing command is green locally. If it can't be made green (needs secrets, env, or a design decision), stop and report — do not push a still-red branch.
2. **Poll CI on fix PRs**:
   ```bash
   SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
   [[ -f "$SKILL_DIR/scripts/poll-ci.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/poll-ci.sh" >&2; exit 1; }
   bash "$SKILL_DIR/scripts/poll-ci.sh" \
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
   SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
   [[ -f "$SKILL_DIR/scripts/poll-ci.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/poll-ci.sh" >&2; exit 1; }
   bash "$SKILL_DIR/scripts/poll-ci.sh" \
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

- **npm**: `$SKILL_DIR/scripts/consolidate-deps.cjs`
- **Python**: `$SKILL_DIR/scripts/consolidate-deps.py`
- **Other ecosystems**: Manual workflow via Edit tool. Requires local clone.

Both scripts: fetch dependabot PRs → parse versions → create branch → apply bumps → test → commit → push → create consolidated PR → close originals.

**Mixed single + grouped PRs:** the scripts read each PR's title *and* body. Single-package PRs ("bump X from A to B") parse from the title; grouped PRs ("Bump the *X group* with N updates") carry their per-package versions only in the body, so the scripts fall back to parsing the body's `Updates \`pkg\` from A to B` lines. A PR that parses as neither is printed as a loud `WARNING: ... SKIPPING` and excluded — if you see one, consolidate it manually so its updates aren't missing from the combined PR. Security-update PRs are always individual (Dependabot never groups them), so a repo with a working `groups:` config can still legitimately show a group PR alongside several single security PRs — that's a consolidation case, not a broken config.

**Version fidelity:** `uv add`/`uv lock --upgrade-package` and `npm install` resolve to the *latest compatible* version, which may exceed the exact target a Dependabot PR pinned (e.g. resolving cryptography to 49.x when the PR targeted 48.0.1). That's usually fine and picks up extra fixes, but if exact parity with the reviewed PRs matters, pin with `==<version>` (uv) or the exact version string (npm) and confirm the lockfile shows the intended versions before pushing.
