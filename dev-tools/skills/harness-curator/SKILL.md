---
name: harness-curator
description: This skill should be used when the user wants to analyze their Claude Code conversation history / session transcripts to manage their harness across sessions — "analyze my conversation history", "대화 기록 분석해서 뭘 스킬로 만들지 봐줘", "task audit", "어떤 스킬들이 안 뜨는지/안 쓰는지 분석해줘", "what recurring work should become a skill/agent/hook", "audit my skills and agents across sessions", "안 쓰는 스킬 정리". It mines transcripts to (1) propose new skills/agents/hooks from recurring work, (2) find existing skills that fail to trigger or underperform, (3) flag unused assets to retire — then delegates the actual create/fix to the right tool. Project-scoped, conversation-analysis-driven. NOT when the user already knows the specific skill to create, modify, or fix — for "create a skill for X", "improve skill X", "make skill X trigger", "기존 스킬 개선해줘" use skill-creator / plugin-dev:skill-development directly. NOT for bootstrapping or validating a repo's AGENTS.md/docs structure ("harness audit", "하네스 점검", "하네스 초기화") — use harness-init.
version: 1.2.1
---

# Harness Curator — analyze transcripts, manage skills/agents/hooks

Sessions reset, so "what I keep doing" and "what's failing" live in the transcripts, not memory. This skill mines `~/.claude/projects/<project>/*.jsonl` (full conversation, not just prompts), classifies what it finds into four signals, and **routes each to the matching creator/optimizer**. It is thin glue: it analyzes and decides, then delegates. **Never reimplement a generator** — call `skill-creator`, `plugin-dev:agent-creator`, `hookify`, or `update-config`.

Replaces the old `/dev-tools:task-audit` command, which mined only `history.jsonl` prompts (good for new-asset candidates, blind to triggering misses and underperforming skills).

## When to use which scope

- **current** (default) — analyze the project at cwd. Use for "audit this project's harness".
- **all** — every project. Use for "what should I build across all my work" and to detect cross-project recurrence (drives the scope decision in Step 4).
- **--project `<abs path>`** — one named project.

## Step 1 — Scan (bounded, deterministic)

Run the scanner with the scope tokens passed as real arguments (not a single combined string). It caps output and prints every dropped count (no silent truncation):

```bash
SCAN="${CLAUDE_PLUGIN_ROOT}/skills/harness-curator/scripts/scan_transcripts.py"
python3 "$SCAN"                              # current project (cwd)
python3 "$SCAN" all                          # every project
python3 "$SCAN" --project "/abs/path"        # one named project — quote paths with spaces
```

Output sections per project: `SKILLS-ACTIVE` (skill → sessions-used), `AGENTS-USED` (subagent_type → sessions-invoked), `CORRECTION-SIGNALS` and `AGENT-CORRECTION-SIGNALS` (skill/agent active then user pushed back), `HARNESS-FRICTION` (user complaining about a recurring imposed behavior — a hook/rule over-firing), `PROMPTS` (cluster these). The scanner does extraction only; clustering and judgment are yours.

If the scan volume is large (`all` scope, or thousands of prompts), do NOT read it all inline — delegate the per-project reading to `Explore` or an `Agent` and analyze the returned summaries. See `references/transcript-format.md` for the record shapes and grep patterns.

## Step 2 — Inventory existing assets

Before proposing anything, know what already exists, or candidates will duplicate it. Glob:
- `~/.claude/plugins/**/skills/*/SKILL.md`, `~/.claude/plugins/**/agents/*.md`, `~/.claude/plugins/**/commands/*.md`
- `~/.claude/skills/*/SKILL.md`, `~/.claude/commands/*.md`
- Project-local: `./.claude/skills/*/SKILL.md`, `./.claude/agents/*.md`
- Rules in `~/.claude/CLAUDE.md` and the project's `CLAUDE.md` / `AGENTS.md`

The `SKILLS-ACTIVE` and `AGENTS-USED` blocks already name which skills fired and which agents were invoked — cross-reference both against this inventory to find skills/agents that exist but rarely/never load.

Two supplementary file-lenses complement the transcript firing data (a skill can fire yet be stale code, or exist yet never parse):
- **Stale code** — `git log --follow -1 --format='%ci' <skill-path>/SKILL.md`; flag assets with no commit in 60+ days. Skip if git unavailable.
- **Unparseable** — flag any `SKILL.md` / agent `.md` whose frontmatter lacks `name` or `description` (it silently never loads — a triggering miss with a structural cause).

Feed both into Step 3: stale-but-firing → review for refresh; never-fires (≈0 in `SKILLS-ACTIVE`) → delete candidate; unparseable → fix frontmatter. This is the asset-portfolio health check moved out of `harness-init` maintenance D, which now keeps repo file-state only.

## Step 3 — Classify into five signals

Read `references/signal-taxonomy.md` for detection rules and the delegate brief per signal. Summary:

| Signal | Detected from | Route to |
|--------|---------------|----------|
| **New-asset candidate** | recurring prompt shape (≥3), no inventory asset covers it | promote/demote rule → `agent-creator` / `skill-creator` / `update-config` |
| **Triggering miss** | prompts in an existing skill's domain, skill absent/low in `SKILLS-ACTIVE`; or work done inline that a fitting agent absent from `AGENTS-USED` should own | skill → `skill-creator` description optimizer; agent → `plugin-dev:agent-development` |
| **Underperforming asset** | skill in `CORRECTION-SIGNALS` / agent in `AGENT-CORRECTION-SIGNALS` (loaded/invoked, then user corrected) | skill → `skill-creator` modify; agent → `plugin-dev:agent-development` modify |
| **Harness friction** | `HARNESS-FRICTION` — user repeatedly complains about an imposed behavior (hook/rule over-firing) | loosen/narrow → `update-config`; bloated rule → surface CLAUDE.md/AGENTS.md line for user edit |
| **Promote / demote** | deterministic repeat → **hook**; skill ~0 in `SKILLS-ACTIVE` or agent ~0 in `AGENTS-USED` → **delete** (adversarial check first) | `update-config` / `hookify` / manual removal |

Ignore one-offs. A cluster needs ≥3 occurrences (CLAUDE.md subagent-factory rule) to be a new-asset candidate; triggering-miss, underperform, and harness-friction need ≥2. Before any **delete**, run the adversarial check (Step 6).

## Step 4 — Decide asset scope (per candidate)

For each **new-asset** candidate, decide where it lives:
- Pattern seen in **one project only** → project-local `./.claude/skills/` (or `./.claude/agents/`).
- Pattern recurs **across multiple projects** (visible only in `all` scope) → recommend a **global plugin** asset (`dev-tools/` or `productivity/`), flagged ⚠ cross-project.

Never silently create a project-local asset for a cross-project pattern — it won't fire where the pattern actually lives. Surface the scope with its evidence and let the user confirm per candidate.

## Step 5 — Report

Output one ranked table, candidates only:

```
| Signal | Cluster / Asset | Freq | Evidence | → Route | Scope | Why |
|--------|-----------------|------|----------|---------|-------|-----|
```

Then a `Watch:` line for near-misses (2×) so nothing is silently dropped.

Record the run so the staleness nudge resets (idempotent, shared state file):

```bash
python3 - <<'PY'
import json, os, re, time
config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
state_dir = os.path.join(config_dir, "projects", re.sub(r"[/.]", "-", os.getcwd()))
os.makedirs(state_dir, exist_ok=True)
p = os.path.join(state_dir, ".harness-curator-state.json")
s = {}
try:
    with open(p) as f: s = json.load(f)
except Exception: pass
s["lastRunMs"] = int(time.time() * 1000)
with open(p, "w") as f: json.dump(s, f)
print("harness-curator run recorded")
PY
```

## Step 6 — Route to the creator (on confirmation)

Ask whether to act on the **top** candidate now. Do not auto-create. On yes, invoke the matching skill with a brief (goal · constraint · exit criterion):
- New skill / upgrade existing skill / fix triggering → `skill-creator:skill-creator` (it owns create, modify, and description-optimization/eval — do not build a parallel eval harness).
- New agent → `plugin-dev:agent-creator`. Fix an agent's triggering description or instructions (triggering-miss / underperform) → `plugin-dev:agent-development`.
- New deterministic hook, or loosen an over-firing hook/permission gate (harness-friction) → `hookify` or `update-config`. For a CLAUDE.md/AGENTS.md rule the user keeps overriding, surface the exact line and let the user decide — never auto-edit global instructions.
- Delete an unused asset → **adversarial check first**: spawn one independent reviewer (`Explore` / `general-purpose`) to argue why removing it is unsafe (guards a rare-but-critical path, fires only via slash-command/hook/sidechain the scanner can't see, or backstops a not-yet-recurred failure). If the reviewer surfaces a real reason, downgrade to `Watch:`. Otherwise confirm, remove the file, and bump the owning plugin version. Self-judgment ≠ verification (CLAUDE.md).

When the asset lands in a `dev-tools/` or `productivity/` plugin, remind the user to bump that plugin's `.claude-plugin/plugin.json` version (project CLAUDE.md rule).

## Additional Resources

- **`references/signal-taxonomy.md`** — detection rules, thresholds, and per-signal delegate brief.
- **`references/transcript-format.md`** — `*.jsonl` record shapes (`attributionSkill`, tool_use, corrections), grep patterns, project-path encoding.
- **`scripts/scan_transcripts.py`** — bounded scanner (run in Step 1).
