---
name: harness-curate
description: >-
  Mine session transcripts to propose or retire harness assets, reconcile overlapping instruction layers, and tidy the auto-memory store. For the conversation you are in → harness-capture.
version: 1.6.9
disable-model-invocation: true
---

# Harness Curator — analyze transcripts, manage skills/agents/hooks

Sessions reset, so "what I keep doing" lives in the transcripts, not memory. This skill mines `~/.claude/projects/<project>/*.jsonl` (full conversation, not just prompts), classifies what it finds — plus the instruction files themselves — into eight signals, and **routes each to the matching creator/optimizer**. It is thin glue: it analyzes and decides, then delegates. **Never reimplement a generator** — call `skill-creator`, `plugin-dev:agent-creator`, `hookify`, or `update-config`.

Before executing a bundled file, resolve `SKILL_DIR` as the absolute parent directory of the `SKILL.md` loaded this turn. Use that concrete directory; do not infer it from a plugin-root environment variable.

Replaces the old `/dev:task-audit` command, which mined only `history.jsonl` prompts (good for new-asset candidates, blind to triggering misses and underperforming skills).

## When to use which scope

- **current** (default) — analyze the project at cwd. Use for "audit this project's harness".
- **all** — every project. Use for "what should I build across all my work" and to detect cross-project recurrence (drives the scope decision in Step 4).
- **--project `<abs path>`** — one named project.

**Instruction-overlap-only run.** "글로벌 지침이랑 레포 지침 충돌 정리해줘" / "시스템 프롬프트랑 중복되는 레포 지침 정리해줘" / "check my global vs repo instructions" / "does my repo restate what the model is already told" asks for Signal 7 alone. Path: Step 2's third file-lens → Step 3 (Instruction-layer overlap row) → Step 7 routing. **Skip Steps 1, 2.5, 4, 5, and the entire Step 6 state write** — `lastRunMs` may only be stamped by a run that actually consumed Step 1's scan; stamping it here would permanently suppress `PROMPTS` nobody analyzed. Dismissals recorded in Step 7 are still written: they touch `dismissedOverlaps` only, never the run stamps.

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

Output sections per project: `SKILLS-ACTIVE` (skill → sessions-used), `AGENTS-USED` (subagent_type → sessions-invoked), `CORRECTION-SIGNALS` and `AGENT-CORRECTION-SIGNALS` (skill/agent active then user pushed back), `HARNESS-FRICTION` (user complaining about a recurring imposed behavior — a hook/rule over-firing), `VERIFIER-FAILURES` (machine verdicts — CI/test failures, qa-verifier rejections, hook denials; Signal 8), `PROMPTS` (cluster these). The scanner does extraction only; clustering and judgment are yours.

The scanner also folds in **Codex CLI sessions** (`~/.codex/sessions/`) for the same project, appended as a `CODEX-SOURCED` block with `CODEX-`-prefixed sections (`CODEX-SKILLS-ACTIVE`, `CODEX-AGENTS-USED`, `CODEX-CORRECTION-SIGNALS`, `CODEX-AGENT-CORRECTION-SIGNALS`, `CODEX-HARNESS-FRICTION`, `CODEX-PROMPTS`) — kept separate rather than merged because the two platforms' signals aren't directly comparable (see `references/transcript-format.md` for why). There is **no `CODEX-VERIFIER-FAILURES`** — Codex tool failures live in `function_call_output` records the scanner does not parse (documented gap), so zero Signal 8 on a Codex-heavy project is not evidence of health. Cluster `PROMPTS` and `CODEX-PROMPTS` together by intent; treat `SKILLS-ACTIVE`/`AGENTS-USED` and their `CODEX-` counterparts as separate demote-candidate evidence per platform. **Codex matching only happens for `current`/`--project` scope** — `all` scope can't reverse Claude's encoded project-directory names back into a real path to match Codex's `session_meta.cwd` against, so it skips Codex entirely (this is documented, not a bug — for cross-project Codex coverage, run `--project` per path).

`SKILLS-ACTIVE` / `AGENTS-USED` / `CORRECTION-SIGNALS` / `HARNESS-FRICTION` are always cumulative (full lifetime history) — a demote candidate must be "~0 across all history," not "~0 since last run." Only `PROMPTS` defaults to **new-since-last-run** (using this project's own `.harness-curator-state.json` `lastRunMs`, written in Step 6) — otherwise re-running the scan re-shows the same latest-250-prompt window every time and the model re-clusters work it already reported. The header prints `new_since_last_run=` / `already_analyzed_suppressed=` so this is never silent; pass `--full` to re-review the entire history (first-ever run on a project, or a deliberate comprehensive re-audit, already behaves like `--full` since there's no prior `lastRunMs`).

If the scan volume is large (`all` scope, or thousands of prompts), do NOT read it all inline — delegate the per-project reading to `Explore` or an `Agent` and analyze the returned summaries. See `references/transcript-format.md` for the record shapes and grep patterns.

## Step 2 — Inventory existing assets

Before proposing anything, know what already exists, or candidates will duplicate it. Glob:
- `~/.claude/plugins/**/skills/*/SKILL.md`, `~/.claude/plugins/**/agents/*.md`, `~/.claude/plugins/**/commands/*.md`
- `~/.claude/skills/*/SKILL.md`, `~/.claude/commands/*.md`
- Project-local: `./.claude/skills/*/SKILL.md`, `./.claude/agents/*.md`
- Rules in `~/.claude/CLAUDE.md` and the project's `CLAUDE.md` / `AGENTS.md`

The `SKILLS-ACTIVE` and `AGENTS-USED` blocks already name which skills fired and which agents were invoked — cross-reference both against this inventory to find skills/agents that exist but rarely/never load.

Four supplementary file-lenses complement the transcript firing data (a skill can fire yet be stale code, exist yet never parse, or be contradicted by a rule one layer up — and a repo fact can sit in auto-memory where no other tool can read it):
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

  A pair is a finding only when it is a **duplicate** (same rule, no scope or strictness delta), a **conflict** (incompatible instructions for the same situation), or **base-redundant** (a repo-side rule whose entire content is behavior the base instructions already impose every turn) — see `references/signal-taxonomy.md` §7 for the three subtypes, the non-findings list (starting with cross-tool reach, the main false positive) and the ownership-based routing. Every finding must carry both sides quoted verbatim with `file:line` — the base-instruction side excepted, where the verbatim quote carries a `[base instructions — {model id}, this session]` label instead. Unquotable pairs are dropped, not reported. Then filter the surviving pairs through the dismissal state so resolved-or-kept pairs don't re-fire every run:

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
- **Memory-store promotion** — the auto-memory store (`<config>/projects/<encoded>/memory/*.md` + its `MEMORY.md` index) is a fifth instruction layer, and the only one that is **Claude-only and per-project**. A repo-specific fact written there is invisible to Codex and every other tool that reads `AGENTS.md`/`docs/` — exactly the loss the global routing rule ("repo facts → owning repo's `docs/`, indexed by `AGENTS.md`") exists to prevent. `harness-capture` tidies this store from inside one session; nobody audits it across sessions, which is this lens. Resolve the directory with the scanner's own path helpers rather than re-deriving the encoding by hand — but check the **exact** encoded path before the resolver's fuzzy pick, for the reason spelled out under the snippet:

  ```bash
  SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
  [[ -d "$SKILL_DIR/scripts" ]] || { echo "Bundled scripts unavailable: $SKILL_DIR/scripts" >&2; exit 1; }
  TARGET_REPO="<the --project path, or cwd on `current` scope>"
  MEMDIRS=$(TARGET_REPO="$TARGET_REPO" SKILL_DIR="$SKILL_DIR" python3 -c 'import os, sys; sys.path.insert(0, os.path.join(os.environ["SKILL_DIR"], "scripts")); from scan_transcripts import encode_project, resolve_project_dir; cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude"); root = os.path.join(cfg, "projects"); repo = os.environ["TARGET_REPO"]; cands = [os.path.join(root, encode_project(repo)), resolve_project_dir(repo, root)]; [print(os.path.join(d, "memory")) for d in dict.fromkeys(cands)]')
  echo "$MEMDIRS" | while read -r d; do [ -d "$d" ] && echo "store: $d"; done
  # nothing printed → no auto-memory store for this project; the lens is a no-op
  ```

  **`TARGET_REPO`, never `os.getcwd()`.** The resolver defaults to the current directory, so a `--project /other/repo` run launched from anywhere else would read *this* repo's memory store while proposing promotions into the other repo's `docs/` and writing dismissals under the other repo's key — the same hazard the overlap lens documents one bullet above, in the same direction. Pass the audited repo in explicitly. The one-liner is `python3 -c`, not a heredoc, on purpose: this snippet is nested in a list item, and an indented `PY` terminator would never close a `<<'PY'` heredoc.

  **Why two candidate paths, exact one first.** `resolve_project_dir` picks the encoded sibling holding the most `*.jsonl` — the right rule for transcripts, the wrong one for memory. The two directories have different producers: transcripts are written per session, the memory store by the memory writer under the project's own encoded path, and nothing ties "most transcripts" to "holds `memory/`". Under the case/underscore drift `_loose_key` exists to absorb, the jsonl-heavy winner can even be a **different repo**, so the fuzzy pick is a fallback, never the primary — check `encode_project(TARGET_REPO)` first and treat a match there as authoritative. Auditing only the resolver's pick returns a clean "no candidates" over a store that exists, which is indistinguishable from a real no-op. If both paths exist and disagree, report it rather than merging them: one of them belongs to another project.

  Read `MEMORY.md` and every memory file in that directory. A memory is a **promotion candidate** only when its frontmatter `metadata.type` is `project` or `reference` **and** its content is scoped to this one repo. `user` and `feedback` memories are cross-repo by definition — promoting them into a single repo's `docs/` would silently drop them everywhere else, so they stay. Full detection rules, non-findings, and the `already-promoted` subtype: `references/signal-taxonomy.md` §6.

  **Evidence requirement (hard, same as the overlap lens):** every candidate quotes the memory body verbatim with `file:line` and names a concrete target `docs/<topic>.md`. Cannot quote it → drop it entirely, not even `Watch:`. Before proposing, confirm the fact is not already in `AGENTS.md` / `CLAUDE.md` / an existing `docs/*.md`.

  Filter candidates through the same `overlap_state.py` suppression so a declined promotion does not re-fire every run. The script is unchanged and its two keys are **positional** (see the Step 2 overlap snippet): for this lens `"global"` is the memory side, `"repo"` is the proposed docs target.

  ```bash
  OSTATE="$SKILL_DIR/scripts/overlap_state.py"
  REPO_ROOT=$(git -C "$TARGET_REPO" rev-parse --show-toplevel)   # TARGET_REPO from the MEMDIR snippet above — the same repo, or the two sides disagree
  # pairs.json for this lens — one entry per promotion candidate:
  #   [{"global": "memory/<file>.md: <verbatim body line>",
  #     "repo":   "docs/<topic>.md (proposed)"}, ...]
  python3 "$OSTATE" --check --project "$REPO_ROOT" < pairs.json
  ```

  Same `--project "$REPO_ROOT"` requirement, same `NEW`-rows-only reporting, same `suppressed=` count carried into the report. `current` / `--project` scope only — `all` cannot resolve the owning repo path to promote *into*.

Feed all four into Step 3: stale-but-firing → review for refresh; never-fires (≈0 in `SKILLS-ACTIVE`) → delete candidate (adversarial check required — see Step 7); unparseable → fix frontmatter; overlap → Signal 7; memory promotion → Signal 6. This is the asset-portfolio health check moved out of `harness-init` maintenance D, which now keeps repo file-state only.

## Step 2.5 — Prediction re-audit (current / --project scope only)

Past harness edits carry falsifiable predictions (`dev:harness-init` → `references/harness-evolution.md` §3 — the loop contract's change record; the file ships with harness-init, not this skill). This step is what falsifies them, using the scan output Step 1 just produced.

1. Resolve the target repo root — `REPO_ROOT=$(git -C "$TARGET_REPO" rev-parse --show-toplevel)` with `TARGET_REPO` = the `--project` path, or cwd on `current` scope (the same two-line resolution Step 2's overlap lens and Step 7 use; the log lives at the repo root, so a run started in a subdirectory must not read `<cwd>/docs/`) — and read `<REPO_ROOT>/docs/harness-log.md`. **Absent file = no pending rows — skip this step silently, it is not an error** (a repo with zero loop-originated edits is the normal case). `all` scope skips too: no resolvable repo path (same limitation as Signal 7 and the Codex fold-in).
2. Load change-history rows whose `Verified` is `pending`, `unverified` (first — they landed without a check), or a bare `failed` with no resolution note — a failure the operator has not yet acted on must keep re-surfacing, not vanish after one declined report.
3. Judge each `Predicted impact` **only against evidence datable after the row's `Date`** — new-since-last-run `PROMPTS`, `VERIFIER-FAILURES` samples from sessions after the edit, or a direct read/command run now. Step 1's cumulative blocks (`SKILLS-ACTIVE`, `CORRECTION-SIGNALS`, … — lifetime aggregates by design) cannot be dated and so can neither hold nor fail a row on their own; when the prediction's window has not elapsed or no post-edit evidence is in view, leave the row untouched.
4. **Held** → stamp the row in place: replace `pending`/`unverified` with the date + one-line evidence (this is loop bookkeeping, the log is its state file — no separate confirmation needed for the stamp itself).
5. **Failed** (the predicted change observably did not happen, or the mistake recurred — post-edit evidence only, per 3) → write `failed` and surface the edit as a **prune/rework candidate** row in the Step 6 report. Any resulting delete goes through the Step 7 adversarial check like every other demote. When the operator resolves it, append the outcome to the cell (`failed — reworked YYYY-MM-DD` / `failed — accepted YYYY-MM-DD`) so step 2 stops reloading it; a bare `failed` means still open.

**Skip on an instruction-overlap-only run** — this step consumes Step 1's scan, which that path never runs (see "When to use which scope").

## Step 3 — Classify into eight signals

Read `references/signal-taxonomy.md` for detection rules and the delegate brief per signal. Summary:

| Signal | Detected from | Route to |
|--------|---------------|----------|
| **New-asset candidate** | recurring prompt shape (≥3), no inventory asset covers it | promote/demote rule → `agent-creator` / `skill-creator` / `update-config` |
| **Triggering miss** | prompts in an existing skill's domain, skill absent/low in `SKILLS-ACTIVE`; or work done inline that a fitting agent absent from `AGENTS-USED` should own | skill → `skill-creator` description optimizer; agent → `plugin-dev:agent-development` |
| **Underperforming asset** | skill in `CORRECTION-SIGNALS` / agent in `AGENT-CORRECTION-SIGNALS` (loaded/invoked, then user corrected) | skill → `skill-creator` modify; agent → `plugin-dev:agent-development` modify |
| **Harness friction** | `HARNESS-FRICTION` — user repeatedly complains about an imposed behavior (hook/rule over-firing; **permission-prompt friction is out of scope**) | loosen/narrow the hook → `update-config`; bloated rule → surface CLAUDE.md/AGENTS.md line for user edit |
| **Promote / demote** | deterministic repeat → **hook**; skill ~0 in `SKILLS-ACTIVE` or agent ~0 in `AGENTS-USED` → **delete** (adversarial check first, Step 7) | `update-config` / `hookify` / manual removal |
| **Domain knowledge candidate** | two inputs: recurring fact/constraint from PROMPTS (≥2 sessions, not a workflow), **and** Step 2's memory-store lens (a `project`/`reference` memory holding a repo-scoped fact) | write to `docs/<topic>.md`; AGENTS.md/CLAUDE.md get index pointer only, not raw fact. Memory-sourced: also route the memory file's deletion to `harness-capture` (Step 7) |
| **Verifier-grounded failure** | `VERIFIER-FAILURES` — ci-fail / qa-reject / hook-deny machine verdicts; ≥2 same-cause after the causal-status read (`references/signal-taxonomy.md` §8; over-collects — read before routing) | same creators as Signals 3/5, evidence = quoted verifier verdicts; verifiers themselves are read-only |
| **Instruction-layer overlap** | Step 2's overlap lens — a rule duplicated in, contradicted between, or already imposed by a higher layer: base instructions → global `~/.claude/CLAUDE.md` → repo `CLAUDE.md`/`AGENTS.md`/`.claude/rules/` → indexed `docs/*.md` | duplicate / base-redundant → **report by default** (the repo copy is a rule's only reach on non-Claude tools); propose deletion only for the non-owning layer, and only in a verified single-tool repo; conflict → surface both quoted lines, ask which is authoritative. Repo edits only on confirmation; **never auto-edit the global file, and never edit base instructions (not editable)** |

**Agent roles are created here, not at init.** `dev:harness-init` deliberately ships an empty `.claude/agents/` roster and no orchestrator skill (its Steps 4b/4c) — before a repo has working history there is no evidence about which delegations recur, so any roster is a guess. That makes this skill the only path by which a repo acquires its first role: a **triggering miss** where work was repeatedly done inline that a missing agent should have owned, or a **new-asset candidate** whose recurring shape is a delegation. Route those to `plugin-dev:agent-creator` (new) or `plugin-dev:agent-development` (fix), and remember the corollary — an empty roster in a young repo is the designed state, never a finding.

Two follow-ups when a role is actually created: the repo's `docs/delegation.md` routing table gains its row **only then** (init leaves it header-only), and an orchestrator becomes worth proposing once ≥1 role exists *and* the same multi-step domain workflow recurs in the transcripts — that one routes to `skill-creator`. Do not pin a model on a role you create; spawns inherit the session model and the caller overrides per spawn.

Ignore one-offs. A cluster needs ≥3 occurrences (CLAUDE.md subagent-factory rule) to be a new-asset candidate; triggering-miss, underperform, harness-friction, and verifier-grounded failure need ≥2. Instruction-layer overlap needs 1 — it's a static defect, not a frequency pattern — but only with both sides quoted. A memory-sourced Signal 6 candidate also needs 1: a memory is by construction a fact someone already judged durable, so the frequency bar was cleared when it was written — the quoting requirement still holds. Before any **delete**, run the adversarial check (Step 7).

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

Step 2.5's outcome rides in the same report: failed-prediction edits appear as prune/rework candidate rows (route → Step 7, adversarial check before delete), and a one-line `Re-audit:` footer states how many predictions were stamped / left pending / failed — so the log's state is visible even when nothing failed.

Instruction-layer overlap rows, memory-promotion rows, and failed-prediction rows (Step 2.5) are static defects, not clusters: write `Freq` as `n/a (static)` — a bare `1` reads as "below the 2× Watch threshold" to anyone scanning the table. Append the `suppressed=` count from each `overlap_state.py --check` run under the `Watch:` line so previously-dismissed pairs are accounted for rather than invisible.

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

Ask whether to act on the **top** candidate now. Do not auto-create. On yes, invoke the matching skill with a brief (goal · constraint · exit criterion).

**Validation gate — the exit criterion is an objective check, not plausibility.** Every routed brief names its acceptance check up front, from the loop contract's per-route table: `dev:harness-init` → `references/harness-evolution.md` §2 — read the table there, do not restate it. The check passing is what makes the edit land; **failing it means revert, not retry-until-green**. When no verifier exists for an edit, it may still land on user confirmation, but its change record is written `unverified` and it is first in line at the next re-audit (Step 2.5). Record every landed edit per the contract's §3 schema — `Predicted impact` + `Verified` columns in **the edited repo's** `docs/harness-log.md` (the `--project` path, or cwd on `current` scope, same resolution as `TARGET_REPO` above; no resolvable repo path → surface the record for the user instead of writing).
- New skill / upgrade existing skill / fix triggering → `skill-creator:skill-creator` (it owns create, modify, and description-optimization/eval — do not build a parallel eval harness).
- New agent → `plugin-dev:agent-creator`. Fix an agent's triggering description or instructions (triggering-miss / underperform) → `plugin-dev:agent-development`.
- New deterministic hook, or loosen an over-firing hook (harness-friction) → `hookify` or `update-config`. **Never touch the `permissions` block** — tool-approval tuning is not this skill's job (see `references/signal-taxonomy.md` §5). For a CLAUDE.md/AGENTS.md rule the user keeps overriding, surface the exact line and let the user decide — never auto-edit global instructions.
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
- Memory → `docs/` promotion (memory-sourced Signal 6) → show the memory quoted with `file:line` and the proposed `docs/<topic>.md`. On confirmation, write the fact to `docs/<topic>.md` and add the one-line pointer to the AGENTS.md Docs Index — the fact itself never goes into AGENTS.md/CLAUDE.md. Then **call the Skill tool with "dev:harness-capture" (Memory hygiene) to delete the promoted memory file and repair the `MEMORY.md` index**: capture owns destructive memory prunes, and this skill does not reimplement an owner's job any more than it reimplements `skill-creator`. An `already-promoted` candidate skips the docs write and goes straight to that deletion route. Record the decision — promoted *or* consciously kept — with `--dismiss` using the same pairs.json shape as the Step 2 check, or it re-fires next run.
- Delete an unused asset → **adversarial check first**: spawn one independent reviewer (`Explore` / `general-purpose`) to argue why removing it is unsafe (guards a rare-but-critical path, fires only via slash-command/hook/sidechain the scanner can't see, or backstops a not-yet-recurred failure). If the reviewer surfaces a real reason, downgrade to `Watch:`. Otherwise confirm, remove the file, and bump the owning plugin version. Self-judgment ≠ verification (CLAUDE.md).

When the asset lands in a `dev/` or `prod/` plugin, remind the user to bump that plugin's `.claude-plugin/plugin.json` version (project CLAUDE.md rule).

## Additional Resources

- **`references/signal-taxonomy.md`** — detection rules, thresholds, and per-signal delegate brief.
- **`references/transcript-format.md`** — `*.jsonl` record shapes (`attributionSkill`, tool_use, corrections), grep patterns, project-path encoding.

**Delegation-asset templates.** These moved here from `harness-init` when init stopped creating agents: they describe how to build a delegation surface, and this skill is the only path that decides one is warranted. Read the relevant one when a signal routes to `plugin-dev:agent-creator` or `skill-creator` — they are the brief material for that handoff, not something this skill executes itself.

- **`references/teammate-role-template.md`** — role-file schema (frontmatter, four spine sections), description anti-patterns, per-role starting templates, the `spine-exempt` escape hatch.
- **`references/delegation-template.md`** — pattern selection, Spawn Prompt Contract, effort tiers, routing-table structure and objective-trigger design, data-transfer protocols, model-inheritance rule.
- **`references/orchestrator-template.md`** — 3-mode orchestrator templates (team/sub-agent/hybrid), scratchpad convention, `docs/harness-log.md` pointer block, directive-description rule, skill frontmatter reference.
- **`references/coordination-patterns.md`** — multi-agent coordination shapes to pick between before writing an orchestrator.
- **`references/agent-teams-onboarding.md`** — Agent Teams prerequisites and environment check; needed only for a team-mode orchestrator (3–5× token cost).
- **`references/competing-hypotheses-playbook.md`** — adversarial root-cause investigation; maps to the `debate` workflow.
- **`references/trigger-router-template.md`** — UserPromptSubmit hook mapping prompt phrases → explicit `Use Skill(X)` / `Spawn Agent(X)`. **Fallback only**, installed on a measured miss-rate ([Scott Spence 2025-11-06](https://scottspence.com/posts/claude-code-skills-dont-auto-activate)).
- **`scripts/scan_transcripts.py`** — bounded scanner (run in Step 1).
- **`scripts/overlap_state.py`** — Signal 7 cross-run suppression: `--check` classifies candidate pairs NEW/DISMISSED (Step 2), `--dismiss` records a resolved-or-kept pair (Step 7), `--list` prints stored keys. Keyed by a hash of both quoted lines, stored as `dismissedOverlaps` in the same `.harness-curator-state.json`; `--test` covers key normalization, the cap, and preservation of `lastRunMs`.
- **`scripts/disable_plugins.py`** — resolves bare plugin names to `plugin@market` keys and atomically writes project-scope disable entries (run in Step 5). `--test` flag exercises all guarantees.
