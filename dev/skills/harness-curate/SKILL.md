---
name: harness-curate
description: >-
  Mine session transcripts to propose new harness assets, fix triggering misses, prune unused
  skills/agents/hooks, and disable plugins that never fire in a repo; after a model upgrade,
  re-examine steering files and guardrails for no-ops. Retrospecting the conversation you are
  in → harness-capture. Repo structure validation → harness-init.
version: 2.3.3
disable-model-invocation: true
---

# Harness Curator — analyze transcripts, manage skills/agents/hooks

Sessions reset, so "what I keep doing" lives in the transcripts. This skill mines
`~/.claude/projects/<project>/*.jsonl` (and Codex sessions), classifies what it finds into six
signals, and **routes each to the matching creator** — `skill-creator`,
`plugin-dev:agent-creator`, `hookify`, `update-config`. It never reimplements a generator.

Resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded this turn.

**Scope:** `current` (default, the project at cwd) · `all` (every project — cross-project
recurrence drives Step 4) · `--project <abs path>` · `--session <id>` (one past session — a
painful run whose context was cleared or compacted; thresholds do not apply, every finding is a
`Watch:` row unless it matches an existing cluster). **Mode:** `upgrade` — run *Upgrade pass*
below instead of Steps 1–5, then Steps 6–7.

## Step 1 — Scan

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
SCAN="$SKILL_DIR/scripts/scan_transcripts.py"
python3 "$SCAN"                              # current project (cwd)
python3 "$SCAN" all                          # every project
python3 "$SCAN" --project "/abs/path"        # one named project
python3 "$SCAN" --session <id-prefix>        # one transcript (filename prefix; ambiguous → exit 2)
python3 "$SCAN" --since YYYY-MM-DD           # only records on/after a date (upgrade pass)
python3 "$SCAN" --full                       # re-review the whole PROMPTS history
```

Sections per project: `SKILLS-ACTIVE` (skill → sessions used), `AGENTS-USED`,
`CORRECTION-SIGNALS` / `AGENT-CORRECTION-SIGNALS` (asset active, then the user pushed back),
`HARNESS-FRICTION` (a hook or rule the user keeps fighting), `VERIFIER-FAILURES` (CI / test /
hook denials — machine verdicts), `TOOL-COST` (oversized tool results and search churn before
the first edit, one row per call shape or target with its session count), `PROMPTS` (cluster these). `CODEX-*` blocks carry the same sections for Codex
sessions — cluster prompts together, keep usage counts separate per platform
(`current`/`--project` only; `all` cannot map Codex cwd back to a project).

Usage and correction sections are cumulative; `PROMPTS` is new-since-last-run (`lastRunMs`
from the project's `.harness-curator-state.json`, stamped in Step 6) unless `--full`. Large
output (`all`, thousands of prompts) → delegate the reading to `Explore` and analyze the returned
summaries; record shapes are in `references/transcript-format.md`.

Done when: the scan exited 0 and every `[dropped N]` count is noted for the report.

## Step 2 — Inventory

Glob what exists so candidates do not duplicate it: `~/.claude/plugins/**/skills/*/SKILL.md`,
`~/.claude/plugins/**/agents/*.md`, `~/.claude/plugins/**/commands/*.md`,
`~/.claude/skills/*/SKILL.md`, `./.claude/skills/*/SKILL.md`, `./.claude/agents/*.md`, and the
rules in `~/.claude/CLAUDE.md` plus the project's `CLAUDE.md` / `AGENTS.md`. Add the
**guardrails**: hooks (`~/.claude/plugins/**/hooks.json`, the `hooks` block of
`~/.claude/settings.json` and `./.claude/settings.json`), the repo's check commands (CI
workflows under `.github/workflows/`, `.pre-commit-config.yaml`, the `lint`/`check`/`test`
scripts of its build tool, check scripts such as `scripts/ci/*`). Cross-reference against
`SKILLS-ACTIVE` / `AGENTS-USED`.

Three lenses on the inventory:

- **Unparseable** — a `SKILL.md` or agent `.md` whose frontmatter lacks `name` or `description`
  never loads. Route to a frontmatter fix, not the description optimizer.
- **Unwired check** — a check script that no CI job, pre-commit hook, or harness hook runs, or a
  CI job that is disabled or always skipped. Wiring it is the finding, ahead of any Signal 1
  candidate that would build the same check again. A repo with no guardrail at all (no CI job
  and no pre-commit hook running its lint/test command) is one finding in its own right.
- **Contract drift** — a repo rule that contradicts a shipped plugin contract, so the agent undoes
  a bundled script by hand every cycle. Checked mechanically, read-only:

  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
  python3 "$SKILL_DIR/scripts/check_plugin_contracts.py" [--project /abs/path]   # exit 1 = conflict
  ```

  Each `CONFLICT` goes in the Step 6 table as its own row, route "repo rule fix". The plugin
  contract wins; the repo rule changes (Step 7).

Done when: every globbed path is either cross-referenced against usage or listed under a lens.

## Step 3 — Classify into six signals

Detection rules and the delegate brief per signal: `references/signal-taxonomy.md`.

| Signal | Detected from | Route |
|--------|---------------|-------|
| **1. New-asset candidate** | a prompt shape recurring ≥3 times that no inventory asset covers | `skill-creator` / `plugin-dev:agent-creator` / `update-config` (hook) |
| **2. Triggering miss** | prompts in an existing asset's domain while it is absent or low in `SKILLS-ACTIVE` / `AGENTS-USED` (≥2) | skill → `skill-creator` description optimizer; agent → `plugin-dev:agent-development` |
| **3. Underperforming or over-firing asset** | `CORRECTION-SIGNALS`, `HARNESS-FRICTION`, or ≥2 same-cause `VERIFIER-FAILURES` on one asset | skill → `skill-creator` modify; agent → `plugin-dev:agent-development`; hook → loosen via `hookify` / `update-config`; a `CLAUDE.md`/`AGENTS.md` line → classify, below |
| **4. Unused asset** | ~0 across lifetime in `SKILLS-ACTIVE` / `AGENTS-USED` | delete, after the adversarial check in Step 7 |
| **5. Domain knowledge candidate** | a fact or constraint restated in ≥2 sessions, not a workflow | classify, below; a plain fact → `docs/<topic>.md`, `AGENTS.md` gets the index row only |
| **6. Tool cost** | `TOOL-COST` — the same oversized call or the same search-churn target in ≥2 sessions | oversized → a bounded command or script (`--jq`, a line range, a summary flag); churn → a **navigation pointer** from a file the agent already reads |

**Classify before routing a rule or a constraint** (Signals 3 and 5, and any `CLAUDE.md` /
`AGENTS.md` line): a **mechanical** violation — a fixed pattern, a banned API, a file-location
rule, anything an exit code can decide — routes to a deterministic check (a hook, a lint rule, a
CI job), whichever the repo's existing guardrail makes cheapest. A **judgement call** routes to
the review-time asset (a `code-review` rule, the reviewer agent), where a diff is all the
context it needs. Only a fact the agent must hold before anything asks stays an instruction-file
line. Default to building the check over writing the sentence.

Ignore one-offs. A deterministic repeat (the same mechanical step every session) promotes to a
hook rather than a skill. **Permission-prompt tuning is out of scope** — never touch the
`permissions` block. Agent roles are created here, not at init: a triggering miss where work an
absent role should own is repeatedly done inline is the evidence; when a role lands, the repo's
`docs/delegation.md` gains its routing row then, with no model pinned.

Done when: every `PROMPTS` cluster and every non-empty signal section is either a candidate, a
`Watch:` near-miss, or named as a one-off — none left unread.

## Step 4 — Decide asset scope

Seen in one project → project-local `./.claude/skills/` or `./.claude/agents/`. Recurs across
projects (`all` scope) → recommend a plugin asset (`dev/` or `prod/`), flagged ⚠ cross-project.
Never silently create a project-local asset for a cross-project pattern.

Done when: every candidate row carries a scope.

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

Done when: each candidate plugin is confirmed and disabled, declined, or absent.

## Upgrade pass (mode `upgrade`)

A new model moves the default, so a line that once changed behavior may now restate it — a
**no-op**, paying context load on every turn for nothing. Scope: the always-loaded **steering**
files (`~/.claude/CLAUDE.md`, the project's `CLAUDE.md` / `AGENTS.md`, every in-scope `SKILL.md`
`description:`), then each skill body, then each hook.

1. **Sentence by sentence**, ask: does this change behavior versus what the current model does
   by default? A sentence that fails is deleted whole, never trimmed to a shorter no-op. A word
   too weak to beat the default (*be thorough*) fails too; its fix is a stronger word. Longer
   treatment where present: `docs/writing-for-agents.md` → *Pruning*.
2. **Settle a disputed line by running it**, not by debate: re-run one prompt the line was
   written for with and without it (a `skill-creator` eval pair, or two fresh sessions). No
   behavior difference → no-op.
3. **Guardrails:** scan twice — `--since <upgrade date>` and the lifetime default — and compare
   `VERIFIER-FAILURES`. A hook or check whose failure mode the `--since` window shows zero times is a `Watch:` row, never a deletion on this evidence alone — a quiet guardrail may be
   the reason the failure is absent. Delete only through the Signal 4 adversarial check.

Done when: every in-scope sentence is marked keep, delete, or disputed (with its run result),
and every row lands in the Step 6 table with Signal `upgrade: no-op` — a mode row, not a
seventh signal; its routes are Signal 3's.

## Step 6 — Report and record

One ranked table, candidates only — `| Signal | Cluster / Asset | Freq | Evidence | → Route |
Scope | Why |` — then a `Watch:` line for near-misses (2×). Every row's Evidence quotes a
specific session moment or file line; a candidate that cannot point at one is generic advice
and is dropped. Then stamp the run so the next scan's `PROMPTS` window starts here — only after
Steps 1–5 read that window; an `upgrade`, `--session`, or `--since` run skips the stamp, or the
next regular run would treat prompts it never clustered as already analyzed:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
RECORD="$SKILL_DIR/scripts/record_run.py"
python3 "$RECORD"                               # cwd
python3 "$RECORD" --project /abs/path/to/repo   # another repo
```

Done when: the table is shown and `record_run.py` exited 0, or was skipped for one of those modes.

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
- **Contract drift** — edit the repo rules and gates the check lists, per its proposed fix. Show
  the diff and confirm before any deletion of existing lines (for example `[x]` backlog history).
  The accepting check: `check_plugin_contracts.py` exits 0 on the repo, and the repo's own
  validation still passes. Retire a repo gate only when it exists solely for the conflicting rule.
- **A global `~/.claude/CLAUDE.md` line** is never edited here — surface it, the user decides.

Done when: the user picked an action, and its accepting check passed or the edit is disclosed as
unverified.

## Additional Resources

- **`references/signal-taxonomy.md`** — detection rules, thresholds, and delegate brief per signal.
- **`references/transcript-format.md`** — `*.jsonl` record shapes, grep patterns, project-path encoding.
- **`scripts/scan_transcripts.py`** — bounded scanner (Step 1); prints every dropped count. Over 1,100 lines — to edit it, read its `SECTION MAP` comment block and then only the function you need.
- **`scripts/record_run.py`** — stamps `lastRunMs` in `.harness-curator-state.json` (Step 6), mirrored best-effort to Codex; `--check-due` is the read side the SessionStart maintenance hook calls (>14d AND >=10 new sessions); `--test`.
- **`scripts/check_plugin_contracts.py`** — repo rules that contradict a plugin contract (Step 2 contract drift); read-only; `--test`.
- **`scripts/disable_plugins.py`** — project-scope plugin disable (Step 5); `--test`.

---

Unwired-check lens, mechanical-vs-judgement classification, Signal 6, `--session`, and the
evidence rule in Step 6 adapted from mattpocock/skills@d81f3a1 `skills/engineering/retro`; the
upgrade pass's no-op test from `skills/productivity/writing-for-agents`.
