---
name: harness-curate
description: >-
  Mine session transcripts across projects to propose or prune harness assets
  (skills/agents/hooks), and audit instruction layers — the model's own base
  instructions, global CLAUDE.md, repo CLAUDE.md/AGENTS.md, and the repo's
  indexed docs/ — for duplicate or conflicting rules. Routes to the owning
  creator — never generates itself. Repo structure validation → harness-init.
version: 1.5.2
---

# Harness Curator — analyze transcripts, manage skills/agents/hooks

Sessions reset, so "what I keep doing" lives in the transcripts, not memory. This skill mines `~/.claude/projects/<project>/*.jsonl` (full conversation, not just prompts), classifies what it finds — plus the instruction files themselves — into seven signals, and **routes each to the matching creator/optimizer**. It is thin glue: it analyzes and decides, then delegates. **Never reimplement a generator** — call `skill-creator`, `plugin-dev:agent-creator`, `hookify`, or `update-config`.

Before executing a bundled file, resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded this turn. Use that concrete directory; do not infer it from a plugin-root environment variable.

Replaces the old `/dev:task-audit` command, which mined only `history.jsonl` prompts (good for new-asset candidates, blind to triggering misses and underperforming skills).

## When to use which scope

- **current** (default) — analyze the project at cwd. Use for "audit this project's harness".
- **all** — every project. Use for "what should I build across all my work" and to detect cross-project recurrence (drives the scope decision in Step 4).
- **--project `<abs path>`** — one named project.

**Instruction-overlap-only run.** "글로벌 지침이랑 레포 지침 충돌 정리해줘" / "시스템 프롬프트랑 중복되는 레포 지침 정리해줘" / "check my global vs repo instructions" / "does my repo restate what the model is already told" asks for Signal 7 alone. Path: Step 2's third file-lens → Step 3 (Instruction-layer overlap row) → Step 7 routing. **Skip Steps 1, 4, 5, and the entire Step 6 state write** — `lastRunMs` may only be stamped by a run that actually consumed Step 1's scan; stamping it here would permanently suppress `PROMPTS` nobody analyzed. Dismissals recorded in Step 7 are still written: they touch `dismissedOverlaps` only, never the run stamps.

## Step 1 — Scan (bounded, deterministic)

Run the scanner with the scope tokens passed as real arguments (not a single combined string). It caps output and prints every dropped count (no silent truncation):

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
SCAN="$SKILL_DIR/scripts/scan_transcripts.py"
python3 "$SCAN"                              # current project (cwd)
python3 "$SCAN" all                          # every project
python3 "$SCAN" --project "/abs/path"        # one named project — quote paths with spaces
python3 "$SCAN" --full                       # force full historical PROMPTS window (see below)
```

Output sections per project: `SKILLS-ACTIVE` (skill → sessions-used), `AGENTS-USED` (subagent_type → sessions-invoked), `CORRECTION-SIGNALS` and `AGENT-CORRECTION-SIGNALS` (skill/agent active then user pushed back), `HARNESS-FRICTION` (user complaining about a recurring imposed behavior — a hook/rule over-firing), `PROMPTS` (cluster these). The scanner does extraction only; clustering and judgment are yours.

The scanner also folds in **Codex CLI sessions** (`~/.codex/sessions/`) for the same project, appended as a `CODEX-SOURCED` block with `CODEX-`-prefixed sections (`CODEX-SKILLS-ACTIVE`, `CODEX-AGENTS-USED`, `CODEX-CORRECTION-SIGNALS`, `CODEX-AGENT-CORRECTION-SIGNALS`, `CODEX-HARNESS-FRICTION`, `CODEX-PROMPTS`) — kept separate rather than merged because the two platforms' signals aren't directly comparable (see `references/transcript-format.md` for why). Cluster `PROMPTS` and `CODEX-PROMPTS` together by intent; treat `SKILLS-ACTIVE`/`AGENTS-USED` and their `CODEX-` counterparts as separate demote-candidate evidence per platform. **Codex matching only happens for `current`/`--project` scope** — `all` scope can't reverse Claude's encoded project-directory names back into a real path to match Codex's `session_meta.cwd` against, so it skips Codex entirely (this is documented, not a bug — for cross-project Codex coverage, run `--project` per path).

`SKILLS-ACTIVE` / `AGENTS-USED` / `CORRECTION-SIGNALS` / `HARNESS-FRICTION` are always cumulative (full lifetime history) — a demote candidate must be "~0 across all history," not "~0 since last run." Only `PROMPTS` defaults to **new-since-last-run** (using this project's own `.harness-curator-state.json` `lastRunMs`, written in Step 6) — otherwise re-running the scan re-shows the same latest-250-prompt window every time and the model re-clusters work it already reported. The header prints `new_since_last_run=` / `already_analyzed_suppressed=` so this is never silent; pass `--full` to re-review the entire history (first-ever run on a project, or a deliberate comprehensive re-audit, already behaves like `--full` since there's no prior `lastRunMs`).

If the scan volume is large (`all` scope, or thousands of prompts), do NOT read it all inline — delegate the per-project reading to `Explore` or an `Agent` and analyze the returned summaries. See `references/transcript-format.md` for the record shapes and grep patterns.

## Step 2 — Inventory existing assets

Before proposing anything, know what already exists, or candidates will duplicate it. Glob:
- `~/.claude/plugins/**/skills/*/SKILL.md`, `~/.claude/plugins/**/agents/*.md`, `~/.claude/plugins/**/commands/*.md`
- `~/.claude/skills/*/SKILL.md`, `~/.claude/commands/*.md`
- Project-local: `./.claude/skills/*/SKILL.md`, `./.claude/agents/*.md`
- Rules in `~/.claude/CLAUDE.md` and the project's `CLAUDE.md` / `AGENTS.md`

The `SKILLS-ACTIVE` and `AGENTS-USED` blocks already name which skills fired and which agents were invoked — cross-reference both against this inventory to find skills/agents that exist but rarely/never load.

Three supplementary file-lenses complement the transcript firing data (a skill can fire yet be stale code, exist yet never parse, or be contradicted by a rule one layer up):
- **Stale code** — resolve each asset's repo before checking history. For every inventoried `SKILL.md` / agent `.md` / command `.md`, run the loop below: new/untracked files (empty `git log` output) skip the age check; assets with a commit date 60+ days ago are flagged; if repo detection fails, mark the asset `non-git` and skip the age check rather than running `git log` from the current project.

  ```bash
  assets=("path/to/skill/SKILL.md" "path/to/agent.md")  # populate from Step 2 Glob results
  for asset in "${assets[@]}"; do
    repo_root=$(git -C "$(dirname "$asset")" rev-parse --show-toplevel 2>/dev/null)
    if [ -z "$repo_root" ]; then
      echo "non-git: $asset"  # skip stale-code age check
      continue
    fi
    last_commit=$(git -C "$repo_root" log --follow -1 --format='%ci' -- "$asset")
    if [ -z "$last_commit" ]; then
      echo "new/untracked, skip age check: $asset"
      continue
    fi
    # flag if $last_commit is 60+ days ago
  done
  ```
- **Unparseable** — flag any `SKILL.md` / agent `.md` whose frontmatter lacks `name` or `description` (it silently never loads — a triggering miss with a structural cause).
- **Instruction-layer overlap** — read these layers in full, then pair rules that govern the same behavior. **Read set (bounded), highest layer first:**
  - **The platform's base instructions** — the model's own system prompt for this session. No file to open: it is already in front of you, and it is the *only* layer you cannot cite by `file:line` (see the evidence rule below).
  - Global `~/.claude/CLAUDE.md`; `~/.codex/AGENTS.md` if present (Codex's global layer).
  - The repo's `CLAUDE.md` / `AGENTS.md` at the repo root and any `AGENTS.md` in directories between cwd and that root — **stop at `git rev-parse --show-toplevel`, never walk into `$HOME` or `/`**.
  - `<repo root>/.claude/rules/*.md` (Claude-only path-scoped rules — resolve from that same repo root, not from cwd, or a run started in a subdirectory silently drops them).
  - **The `docs/*.md` files the repo's AGENTS.md Docs Index actually points to**, resolved from the same repo root. `docs/` is where `harness-init` deliberately routes procedure and delegation detail, so a rule that duplicates or contradicts an upper layer lands there just as often as in AGENTS.md — and never got read before. Bound the read to indexed files (an unindexed `docs/` file is a separate `harness-init` finding, not an overlap one); if that set is large, delegate the reading to `Explore` / an `Agent` and pair from the returned quotes, same as Step 1.

  A pair is a finding only when it is a **duplicate** (same rule, no scope or strictness delta), a **conflict** (incompatible instructions for the same situation), or **base-redundant** (a repo-side rule whose entire content is behavior the base instructions already impose every turn) — see `references/signal-taxonomy.md` §8 for the three subtypes, the non-findings list (starting with cross-tool reach, the main false positive) and the ownership-based routing. Every finding must carry both sides quoted verbatim with `file:line` — the base-instruction side excepted, where the verbatim quote carries a `[base instructions — {model id}, this session]` label instead. Unquotable pairs are dropped, not reported. Then filter the surviving pairs through the dismissal state so resolved-or-kept pairs don't re-fire every run:

  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
  OSTATE="$SKILL_DIR/scripts/overlap_state.py"
  TARGET_REPO="<the --project path, or cwd on `current` scope>"
  REPO_ROOT=$(git -C "$TARGET_REPO" rev-parse --show-toplevel)
  # Write pairs.json first — one entry per candidate pair. The two keys are positional,
  # not literal file names: "global" is the UPPER layer's side (base instructions,
  # ~/.claude/CLAUDE.md, or ~/.codex/AGENTS.md) and "repo" is the repo-side one
  # (CLAUDE.md / AGENTS.md / .claude/rules/ / docs/).
  # Each value = the source, then the verbatim line you quoted above:
  #   [{"global": "~/.claude/CLAUDE.md: <verbatim line>",
  #     "repo":   "docs/delegation.md: <verbatim line>"}, ...]
  # For a base-instruction side, the source is the label: "[base instructions — {model id}]".
  # The key is a hash of the two *values*, so the source prefix is load-bearing: without it,
  # the same duplicated sentence appearing in two indexed files collapses to one key, and
  # dismissing one pair silently suppresses the other. Use the path, NOT path:line — line
  # numbers shift on unrelated edits and would resurface settled pairs as noise. Including
  # the model id in the base label is what makes a model upgrade invalidate that dismissal.
  # Pairs dismissed before this rule existed were keyed on the bare lines; they resurface
  # once, then re-dismiss under the new key.
  python3 "$OSTATE" --check --project "$REPO_ROOT" < pairs.json   # NEW / DISMISSED per pair + counts
  ```

  `--project` is required, not optional: the script defaults to `os.getcwd()`, so a `--project /other/repo` run launched from anywhere else would read the *current* repo's dismissals. `REPO_ROOT` is the same root the read set above is bounded by — reuse it for both.

  Report only `NEW` rows, and carry the printed `suppressed=` count into the report. Runs on `current` / `--project` scope only — `all` scope has no resolvable repo path per project (same limitation as the Codex fold-in), so run `--project` per repo for cross-repo coverage.

Feed all three into Step 3: stale-but-firing → review for refresh; never-fires (≈0 in `SKILLS-ACTIVE`) → delete candidate (adversarial check required — see Step 7); unparseable → fix frontmatter; overlap → Signal 7. This is the asset-portfolio health check moved out of `harness-init` maintenance D, which now keeps repo file-state only.

## Step 3 — Classify into seven signals

Read `references/signal-taxonomy.md` for detection rules and the delegate brief per signal. Summary:

| Signal | Detected from | Route to |
|--------|---------------|----------|
| **New-asset candidate** | recurring prompt shape (≥3), no inventory asset covers it | promote/demote rule → `agent-creator` / `skill-creator` / `update-config` |
| **Triggering miss** | prompts in an existing skill's domain, skill absent/low in `SKILLS-ACTIVE`; or work done inline that a fitting agent absent from `AGENTS-USED` should own | skill → `skill-creator` description optimizer; agent → `plugin-dev:agent-development` |
| **Underperforming asset** | skill in `CORRECTION-SIGNALS` / agent in `AGENT-CORRECTION-SIGNALS` (loaded/invoked, then user corrected) | skill → `skill-creator` modify; agent → `plugin-dev:agent-development` modify |
| **Harness friction** | `HARNESS-FRICTION` — user repeatedly complains about an imposed behavior (hook/rule over-firing) | loosen/narrow → `update-config`; bloated rule → surface CLAUDE.md/AGENTS.md line for user edit |
| **Promote / demote** | deterministic repeat → **hook**; skill ~0 in `SKILLS-ACTIVE` or agent ~0 in `AGENTS-USED` → **delete** (adversarial check first, Step 7) | `update-config` / `hookify` / manual removal |
| **Domain knowledge candidate** | recurring fact/constraint from PROMPTS (≥2 sessions, not a workflow) — model judgment same as Signal 1 | write to `docs/<topic>.md`; AGENTS.md/CLAUDE.md get index pointer only, not raw fact |
| **Instruction-layer overlap** | Step 2's overlap lens — a rule duplicated in, contradicted between, or already imposed by a higher layer: base instructions → global `~/.claude/CLAUDE.md` → repo `CLAUDE.md`/`AGENTS.md`/`.claude/rules/` → indexed `docs/*.md` | duplicate / base-redundant → **report by default** (the repo copy is a rule's only reach on non-Claude tools); propose deletion only for the non-owning layer, and only in a verified single-tool repo; conflict → surface both quoted lines, ask which is authoritative. Repo edits only on confirmation; **never auto-edit the global file, and never edit base instructions (not editable)** |

Ignore one-offs. A cluster needs ≥3 occurrences (CLAUDE.md subagent-factory rule) to be a new-asset candidate; triggering-miss, underperform, and harness-friction need ≥2. Instruction-layer overlap needs 1 — it's a static defect, not a frequency pattern — but only with both sides quoted. Before any **delete**, run the adversarial check (Step 7).

## Step 4 — Decide asset scope (per candidate)

For each **new-asset** candidate, decide where it lives:
- Pattern seen in **one project only** → project-local `./.claude/skills/` (or `./.claude/agents/`).
- Pattern recurs **across multiple projects** (visible only in `all` scope) → recommend a **global plugin** asset (`dev/` or `prod/`), flagged ⚠ cross-project.

Never silently create a project-local asset for a cross-project pattern — it won't fire where the pattern actually lives. Surface the scope with its evidence and let the user confirm per candidate.

## Step 5 — Repo-fit plugin disable

Identify globally-enabled plugins that don't belong in this repo and disable them at project scope.

### Precondition: enabled-only candidates

Only plugins currently `true` in the global `enabledPlugins` dict are candidates. Because they're already enabled in user scope their key exists there — so a project-scope `false` override takes effect. Plugins already `false` or absent in global settings are skipped (a project `false` on a globally-`false` plugin has no visible effect and indicates a logic error).

### Combined signal — both required

**1. Primary (empirical):** The plugin's skills/agents fired ~0× in this repo's `SKILLS-ACTIVE` / `AGENTS-USED` output from Step 1. Split `plugin:skill` on the first `:` to get the bare plugin name; for bare (unprefixed) `AGENTS-USED` keys that carry no plugin prefix, handle gracefully (check name match or skip).

**2. Corroborating:** Repo characteristics (languages, frameworks, file patterns) confirm the plugin is irrelevant to this codebase.

**Characteristics-alone disabling is FORBIDDEN.** Heuristic guessing from language/framework without empirical usage evidence must never trigger a disable.

### Per-plugin confirm gate

Present the candidate list (plugin key + evidence summary) and ask the user to confirm each individually. Do not disable any plugin silently or in bulk. Only write confirmed entries.

### Write: call the helper script

After per-plugin confirmation, call the helper once with all confirmed bare plugin names:

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
DISABLE="$SKILL_DIR/scripts/disable_plugins.py"
python3 "$DISABLE" dev frontend-design   # example — use confirmed names
# auditing a repo other than cwd (`all` / `--project` scope)? name it explicitly:
python3 "$DISABLE" --project=/abs/path/to/repo dev
```

The script resolves each bare name to its `plugin@market` key in the global `enabledPlugins` (scanning **all** matching marketplaces so a stale `false` key never masks the enabled one), then atomically writes `false` entries into the target project's `.claude/settings.json` (defaults to `<cwd>`, or `--project=PATH`):
- Reads global settings from `$CLAUDE_CONFIG_DIR/settings.json` (fallback `~/.claude/settings.json`).
- Writes only to the **project** `.claude/settings.json` — never the global file.
- Preserves all existing keys and sections; creates `enabledPlugins` if absent.
- Guarantees are checked by `scripts/disable_plugins.py --test` — disable-only behavior and write correctness; the test does not inject a mid-write crash, so it does not itself prove atomicity under failure. See Additional Resources.

### Post-write note

Print to the user: _"Project-scope disable written. Effect is visible after `/plugin` reload or session restart. Merge behavior between project and global settings may be environment-dependent."_

## Step 6 — Report

Output one ranked table, candidates only:

```
| Signal | Cluster / Asset | Freq | Evidence | → Route | Scope | Why |
|--------|-----------------|------|----------|---------|-------|-----|
```

Then a `Watch:` line for near-misses (2×) so nothing is silently dropped.

Instruction-layer overlap rows are static defects, not clusters: write `Freq` as `n/a (static)` — a bare `1` reads as "below the 2× Watch threshold" to anyone scanning the table. Append the `suppressed=` count from `overlap_state.py --check` under the `Watch:` line so previously-dismissed pairs are accounted for rather than invisible.

Record the run and candidate state so the staleness nudge stays accurate. **Skip this entire write on an instruction-overlap-only run** (see "When to use which scope") — Step 1's scan never ran, so stamping `lastRunMs` would suppress prompts nobody analyzed. Set `HARNESS_PENDING=1` if the report had ≥1 non-Watch candidate row; omit or set to `0` if the report was empty or Watch-only. The nudge emits a distinct "pending candidates" message when `lastCandidateMs` is stale (self-corrects on next run even if user acted without re-running):

```bash
# Choose the prefix: HARNESS_PENDING=1 if ≥1 non-Watch candidate was produced;
# HARNESS_PENDING=0 (or omit the prefix entirely) if the report was empty or Watch-only.
# Do NOT blindly copy HARNESS_PENDING=1 — an empty-report run must clear lastCandidateMs.
HARNESS_PENDING=1 python3 - <<'PY'   # ← replace 1 with 0 for empty/Watch-only reports
import glob, json, os, re, time
config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
proj_root = os.path.join(config_dir, "projects")
# Must land in the SAME dir Step 1's scanner reads for this cwd (see scan_transcripts.py
# resolve_project_dir) — a raw, non-normcased substitution here can mint a case/underscore
# sibling directory that then poisons that resolver's exact-match short-circuit on a future
# run, silently hiding real transcript data under a different-cased sibling.
def encode_project(path):
    return re.sub(r"[/.:\\]", "-", os.path.normcase(os.path.abspath(path)))
def loose_key(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())
exact = os.path.join(proj_root, encode_project(os.getcwd()))
state_dir = exact
if os.path.isdir(proj_root) and len(glob.glob(os.path.join(exact, "*.jsonl"))) == 0:
    target_key = loose_key(encode_project(os.getcwd()))
    best, best_count = None, -1
    for n in os.listdir(proj_root):
        d = os.path.join(proj_root, n)
        if os.path.isdir(d) and loose_key(n) == target_key:
            count = len(glob.glob(os.path.join(d, "*.jsonl")))
            if count > best_count:
                best, best_count = d, count
    if best is not None:
        state_dir = best
os.makedirs(state_dir, exist_ok=True)
p = os.path.join(state_dir, ".harness-curator-state.json")
now = int(time.time() * 1000)
s = {}
try:
    with open(p) as f: s = json.load(f)
except Exception: pass
s["lastRunMs"] = now
if os.environ.get("HARNESS_PENDING") == "1":
    s["lastCandidateMs"] = now
else:
    s.pop("lastCandidateMs", None)
with open(p, "w") as f: json.dump(s, f)
print("harness-curate run recorded")

# Mirror the same stamp into Codex's side (see scan_transcripts.py codex_state_dir) so its
# incremental PROMPTS filter and the staleness nudge stay accurate too. Best-effort: Codex
# may not be installed on this machine, and this scope may not have had Codex data at all —
# either way, a failure here must never affect the Claude-side write above.
try:
    codex_home = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    codex_state_dir = os.path.join(codex_home, "projects", encode_project(os.getcwd()))
    os.makedirs(codex_state_dir, exist_ok=True)
    cp = os.path.join(codex_state_dir, ".harness-curator-state.json")
    cs = {}
    try:
        with open(cp) as f: cs = json.load(f)
    except Exception: pass
    cs["lastRunMs"] = now
    if os.environ.get("HARNESS_PENDING") == "1":
        cs["lastCandidateMs"] = now
    else:
        cs.pop("lastCandidateMs", None)
    with open(cp, "w") as f: json.dump(cs, f)
except Exception:
    pass
PY
```

This snippet only stamps the CURRENT project's Codex state (matching `os.getcwd()`, i.e. `current` scope) — `all`/`--project` runs still only update the cwd's own bookkeeping, same simplification the pre-existing Claude-side write already made (see the comment on Step 6's original design — this was never scope-complete, only cwd-complete).

## Step 7 — Route to the creator (on confirmation)

Ask whether to act on the **top** candidate now. Do not auto-create. On yes, invoke the matching skill with a brief (goal · constraint · exit criterion):
- New skill / upgrade existing skill / fix triggering → `skill-creator:skill-creator` (it owns create, modify, and description-optimization/eval — do not build a parallel eval harness).
- New agent → `plugin-dev:agent-creator`. Fix an agent's triggering description or instructions (triggering-miss / underperform) → `plugin-dev:agent-development`.
- New deterministic hook, or loosen an over-firing hook/permission gate (harness-friction) → `hookify` or `update-config`. For a CLAUDE.md/AGENTS.md rule the user keeps overriding, surface the exact line and let the user decide — never auto-edit global instructions.
- Instruction-layer overlap → show the quoted pair (`file:line` both sides, or the `[base instructions — {model id}, this session]` label on the base side) and the ownership call. A repo-side edit (deleting a duplicate from `CLAUDE.md`/`AGENTS.md`/`.claude/rules/`/`docs/`, trimming a base-redundant line, or labeling a deliberate override) is applied only on confirmation; a global-side edit is never applied — surface the line and let the user change `~/.claude/CLAUDE.md` themselves. Base instructions are not editable at all — the only actionable side of a base-redundant pair is the repo one. Once the user has resolved a pair **or decided to keep it as-is**, record the dismissal so it stops re-firing:

  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
  OSTATE="$SKILL_DIR/scripts/overlap_state.py"
  TARGET_REPO="<the --project path, or cwd on `current` scope>"
  REPO_ROOT=$(git -C "$TARGET_REPO" rev-parse --show-toplevel)
  # Reuse (or rewrite) the same pairs.json from Step 2 — dismiss only the decided pairs.
  # Same --project as the Step 2 --check, or the dismissal lands under the wrong project
  # and the pair re-fires next run.
  python3 "$OSTATE" --dismiss --project "$REPO_ROOT" < pairs.json
  ```
- Delete an unused asset → **adversarial check first**: spawn one independent reviewer (`Explore` / `general-purpose`) to argue why removing it is unsafe (guards a rare-but-critical path, fires only via slash-command/hook/sidechain the scanner can't see, or backstops a not-yet-recurred failure). If the reviewer surfaces a real reason, downgrade to `Watch:`. Otherwise confirm, remove the file, and bump the owning plugin version. Self-judgment ≠ verification (CLAUDE.md).

When the asset lands in a `dev/` or `prod/` plugin, remind the user to bump that plugin's `.claude-plugin/plugin.json` version (project CLAUDE.md rule).

## Additional Resources

- **`references/signal-taxonomy.md`** — detection rules, thresholds, and per-signal delegate brief.
- **`references/transcript-format.md`** — `*.jsonl` record shapes (`attributionSkill`, tool_use, corrections), grep patterns, project-path encoding.
- **`scripts/scan_transcripts.py`** — bounded scanner (run in Step 1).
- **`scripts/overlap_state.py`** — Signal 7 cross-run suppression: `--check` classifies candidate pairs NEW/DISMISSED (Step 2), `--dismiss` records a resolved-or-kept pair (Step 7), `--list` prints stored keys. Keyed by a hash of both quoted lines, stored as `dismissedOverlaps` in the same `.harness-curator-state.json`; `--test` covers key normalization, the cap, and preservation of `lastRunMs`.
- **`scripts/disable_plugins.py`** — resolves bare plugin names to `plugin@market` keys and atomically writes project-scope disable entries (run in Step 5). `--test` flag exercises all guarantees.
