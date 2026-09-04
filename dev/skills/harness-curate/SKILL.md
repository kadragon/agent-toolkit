---
name: harness-curate
description: >-
  Mine session transcripts to propose new harness assets, fix triggering misses, prune unused
  skills/agents/hooks, and disable plugins that never fire in a repo. Retrospecting the
  conversation you are in → harness-capture. Repo structure validation → harness-init.
version: 2.0.0
disable-model-invocation: true
---

# Harness Curator — analyze transcripts, manage skills/agents/hooks

Sessions reset, so "what I keep doing" lives in the transcripts. This skill mines
`~/.claude/projects/<project>/*.jsonl` (and Codex sessions), classifies what it finds into five
signals, and **routes each to the matching creator** — `skill-creator`,
`plugin-dev:agent-creator`, `hookify`, `update-config`. It never reimplements a generator.

Resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded this turn.

**Scope:** `current` (default, the project at cwd) · `all` (every project — cross-project
recurrence drives Step 4) · `--project <abs path>`.

## Step 1 — Scan

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
SCAN="$SKILL_DIR/scripts/scan_transcripts.py"
python3 "$SCAN"                              # current project (cwd)
python3 "$SCAN" all                          # every project
python3 "$SCAN" --project "/abs/path"        # one named project
python3 "$SCAN" --full                       # re-review the whole PROMPTS history
```

Sections per project: `SKILLS-ACTIVE` (skill → sessions used), `AGENTS-USED`,
`CORRECTION-SIGNALS` / `AGENT-CORRECTION-SIGNALS` (asset active, then the user pushed back),
`HARNESS-FRICTION` (a hook or rule the user keeps fighting), `VERIFIER-FAILURES` (CI / test /
hook denials — machine verdicts), `PROMPTS` (cluster these). `CODEX-*` blocks carry the same
sections for Codex sessions — cluster prompts together, keep usage counts separate per platform
(`current`/`--project` only; `all` cannot map Codex cwd back to a project).

Usage and correction sections are cumulative; `PROMPTS` is new-since-last-run (`lastRunMs`
from the project's `.harness-curator-state.json`, stamped in Step 6) unless `--full`. Large
output (`all`, thousands of prompts) → delegate the reading to `Explore` and analyze the returned
summaries; record shapes are in `references/transcript-format.md`.

## Step 2 — Inventory

Glob what exists so candidates do not duplicate it: `~/.claude/plugins/**/skills/*/SKILL.md`,
`~/.claude/plugins/**/agents/*.md`, `~/.claude/plugins/**/commands/*.md`,
`~/.claude/skills/*/SKILL.md`, `./.claude/skills/*/SKILL.md`, `./.claude/agents/*.md`, and the
rules in `~/.claude/CLAUDE.md` plus the project's `CLAUDE.md` / `AGENTS.md`. Cross-reference
against `SKILLS-ACTIVE` / `AGENTS-USED`.

Two file lenses on the inventory:

- **Unparseable** — a `SKILL.md` or agent `.md` whose frontmatter lacks `name` or `description`
  never loads. Route to a frontmatter fix, not the description optimizer.
- **Stale** — last committed 60+ days ago, judged from the asset's *own* repo:

  ```bash
  assets=("path/to/skill/SKILL.md" "path/to/agent.md")   # from the glob above
  for asset in "${assets[@]}"; do
    repo_root=$(git -C "$(dirname "$asset")" rev-parse --show-toplevel 2>/dev/null)
    [ -n "$repo_root" ] || { echo "non-git: $asset"; continue; }
    last_commit=$(git -C "$repo_root" log --follow -1 --format='%ci' -- "$asset")
    [ -n "$last_commit" ] || { echo "untracked: $asset"; continue; }
    echo "$last_commit  $asset"   # flag when 60+ days old
  done
  ```

  Stale but firing → refresh candidate. Never fires → Signal 4.

## Step 3 — Classify into five signals

Detection rules and the delegate brief per signal: `references/signal-taxonomy.md`.

| Signal | Detected from | Route |
|--------|---------------|-------|
| **1. New-asset candidate** | a prompt shape recurring ≥3 times that no inventory asset covers | `skill-creator` / `plugin-dev:agent-creator` / `update-config` (hook) |
| **2. Triggering miss** | prompts in an existing asset's domain while it is absent or low in `SKILLS-ACTIVE` / `AGENTS-USED` (≥2) | skill → `skill-creator` description optimizer; agent → `plugin-dev:agent-development` |
| **3. Underperforming or over-firing asset** | `CORRECTION-SIGNALS`, `HARNESS-FRICTION`, or ≥2 same-cause `VERIFIER-FAILURES` on one asset | skill → `skill-creator` modify; agent → `plugin-dev:agent-development`; hook → loosen via `hookify` / `update-config`; a `CLAUDE.md`/`AGENTS.md` line → surface it, the user edits |
| **4. Unused asset** | ~0 across lifetime in `SKILLS-ACTIVE` / `AGENTS-USED` | delete, after the adversarial check in Step 7 |
| **5. Domain knowledge candidate** | a fact or constraint restated in ≥2 sessions, not a workflow | `docs/<topic>.md` in the owning repo; `AGENTS.md` gets the index row only |

Ignore one-offs. A deterministic repeat (the same mechanical step every session) promotes to a
hook rather than a skill. **Permission-prompt tuning is out of scope** — never touch the
`permissions` block. Agent roles are created here, not at init: a triggering miss where work an
absent role should own is repeatedly done inline is the evidence; when a role lands, the repo's
`docs/delegation.md` gains its routing row then, with no model pinned.

## Step 4 — Decide asset scope

Seen in one project → project-local `./.claude/skills/` or `./.claude/agents/`. Recurs across
projects (`all` scope) → recommend a plugin asset (`dev/` or `prod/`), flagged ⚠ cross-project.
Never silently create a project-local asset for a cross-project pattern.

## Step 5 — Repo-fit plugin disable

Candidates: plugins `true` in the global `enabledPlugins` whose skills and agents fired ~0× in
this repo (`SKILLS-ACTIVE` / `AGENTS-USED`, bare plugin name = the part before the first `:`)
**and** whose domain the repo's stack visibly lacks. Usage evidence is required — never disable
on repo characteristics alone. Confirm each plugin individually, then:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
DISABLE="$SKILL_DIR/scripts/disable_plugins.py"
python3 "$DISABLE" <confirmed bare plugin names>          # cwd
python3 "$DISABLE" --project=/abs/path/to/repo <names>    # another repo
```

Writes `false` entries into the *project* `.claude/settings.json` only, atomically, resolving
each name to its `plugin@market` key. Tell the user the effect shows after `/plugin` reload or a
restart.

## Step 6 — Report and record

One ranked table, candidates only — `| Signal | Cluster / Asset | Freq | Evidence | → Route |
Scope | Why |` — then a `Watch:` line for near-misses (2×). Then stamp the run so the next scan's
`PROMPTS` window starts here:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
RECORD="$SKILL_DIR/scripts/record_run.py"
python3 "$RECORD"                               # cwd
python3 "$RECORD" --project /abs/path/to/repo   # another repo
```

## Step 7 — Route to the creator (on confirmation)

Ask whether to act on the **top** candidate now. Never auto-create. On yes, invoke the matching
skill with a brief — goal · constraint · **the objective check that accepts the edit** (a
`skill-creator` eval pass, a re-run of the missed trigger, a fixture event piped through the
hook). Failing the check means revert, not retry-until-green. No check available → the edit may
land on confirmation, disclosed as unverified.

- **Delete an unused asset** — adversarial check first: spawn one independent reviewer
  (`Explore` / `general-purpose`) to argue why removal is unsafe (a rare critical path, a
  slash-command or hook route the scanner cannot see, a backstop for a failure not yet recurred).
  A real reason → downgrade to `Watch:`. Otherwise confirm, remove, and remind the user to bump the
  owning plugin's version.
- **Domain knowledge** — write `docs/<topic>.md` and one `AGENTS.md` Docs Index row; the fact
  itself never goes into `AGENTS.md`/`CLAUDE.md`. A repo-scoped fact that lives in auto-memory
  moves the same way, then the memory file is deleted through the Skill tool with
  "dev:harness-capture" (Memory hygiene), which owns destructive memory prunes.
- **A global `~/.claude/CLAUDE.md` line** is never edited here — surface it, the user decides.

## Additional Resources

- **`references/signal-taxonomy.md`** — detection rules, thresholds, and delegate brief per signal.
- **`references/transcript-format.md`** — `*.jsonl` record shapes, grep patterns, project-path encoding.
- **`scripts/scan_transcripts.py`** — bounded scanner (Step 1); prints every dropped count.
- **`scripts/record_run.py`** — stamps `lastRunMs` in `.harness-curator-state.json` (Step 6), mirrored best-effort to Codex; `--test`.
- **`scripts/disable_plugins.py`** — project-scope plugin disable (Step 5); `--test`.
