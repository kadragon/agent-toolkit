---
name: harness-curator
description: This skill should be used when the user wants to analyze their Claude Code conversation history / session transcripts to manage their harness across sessions — "analyze my conversation history", "대화 기록 분석해서 뭘 스킬로 만들지 봐줘", "task audit", "어떤 스킬들이 안 뜨는지/안 쓰는지 분석해줘", "what recurring work should become a skill/agent/hook", "audit my skills and agents across sessions", "안 쓰는 스킬 정리". It mines transcripts to (1) propose new skills/agents/hooks from recurring work, (2) find existing skills that fail to trigger or underperform, (3) flag unused assets to retire — then delegates the actual create/fix to the right tool. Project-scoped, conversation-analysis-driven. NOT when the user already knows the specific skill to create, modify, or fix — for "create a skill for X", "improve skill X", "make skill X trigger", "기존 스킬 개선해줘" use skill-creator / plugin-dev:skill-development directly. NOT for bootstrapping or validating a repo's AGENTS.md/docs structure ("harness audit", "하네스 점검", "하네스 초기화") — use harness-init.
version: 1.0.0
---

# Harness Curator — analyze transcripts, manage skills/agents/hooks

Sessions reset, so "what I keep doing" and "what's failing" live in the transcripts, not memory. This skill mines `~/.claude/projects/<project>/*.jsonl` (full conversation, not just prompts), classifies what it finds into four signals, and **routes each to the matching creator/optimizer**. It is thin glue: it analyzes and decides, then delegates. **Never reimplement a generator** — call `skill-creator`, `plugin-dev:agent-creator`, `hookify`, or `update-config`.

Replaces the old `/dev-tools:task-audit` command, which mined only `history.jsonl` prompts (good for new-asset candidates, blind to triggering misses and underperforming skills).

## When to use which scope

- **current** (default) — analyze the project at cwd. Use for "audit this project's harness".
- **all** — every project. Use for "what should I build across all my work" and to detect cross-project recurrence (drives the scope decision in Step 4).
- **--project `<abs path>`** — one named project.

## Step 1 — Scan (bounded, deterministic)

Run the scanner. It caps output and prints every dropped count (no silent truncation):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/skills/harness-curator/scripts/scan_transcripts.py" "$SCOPE"
```

`$SCOPE` is empty (current), `all`, or `--project /abs/path`. Output sections per project: `SKILLS-ACTIVE` (skill → sessions-used), `CORRECTION-SIGNALS` (skill-active then user pushed back), `PROMPTS` (cluster these). The scanner does extraction only; clustering and judgment are yours.

If the scan volume is large (`all` scope, or thousands of prompts), do NOT read it all inline — delegate the per-project reading to `Explore` or an `Agent` and analyze the returned summaries. See `references/transcript-format.md` for the record shapes and grep patterns.

## Step 2 — Inventory existing assets

Before proposing anything, know what already exists, or candidates will duplicate it. Glob:
- `~/.claude/plugins/**/skills/*/SKILL.md`, `~/.claude/plugins/**/agents/*.md`, `~/.claude/plugins/**/commands/*.md`
- `~/.claude/skills/*/SKILL.md`, `~/.claude/commands/*.md`
- Project-local: `./.claude/skills/*/SKILL.md`, `./.claude/agents/*.md`
- Rules in `~/.claude/CLAUDE.md` and the project's `CLAUDE.md` / `AGENTS.md`

The `SKILLS-ACTIVE` block already names which skills fired — cross-reference it against this inventory to find assets that exist but rarely/never load.

## Step 3 — Classify into four signals

Read `references/signal-taxonomy.md` for detection rules and the delegate brief per signal. Summary:

| Signal | Detected from | Route to |
|--------|---------------|----------|
| **New-asset candidate** | recurring prompt shape (≥3), no inventory asset covers it | promote/demote rule → `agent-creator` / `skill-creator` / `update-config` |
| **Triggering miss** | prompts in an existing skill's domain, but that skill is absent / low in `SKILLS-ACTIVE` | `skill-creator` description optimizer |
| **Underperforming asset** | skill present in `CORRECTION-SIGNALS` (loaded, then user corrected) | `skill-creator` modify mode |
| **Promote / demote** | deterministic repeat → **hook**; asset with ~0 sessions-used → **delete** | `update-config` / `hookify` / manual removal |

Ignore one-offs. A cluster needs ≥3 occurrences (CLAUDE.md subagent-factory rule) to be a new-asset candidate; triggering-miss and underperform need ≥2.

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
import json, os, time
config_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
p = os.path.join(config_dir, ".task-audit-state.json")
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
- New agent → `plugin-dev:agent-creator`.
- New deterministic hook → `hookify` or `update-config`.
- Delete an unused asset → confirm, then remove the file and bump the owning plugin version.

When the asset lands in a `dev-tools/` or `productivity/` plugin, remind the user to bump that plugin's `.claude-plugin/plugin.json` version (project CLAUDE.md rule).

## Additional Resources

- **`references/signal-taxonomy.md`** — detection rules, thresholds, and per-signal delegate brief.
- **`references/transcript-format.md`** — `*.jsonl` record shapes (`attributionSkill`, tool_use, corrections), grep patterns, project-path encoding.
- **`scripts/scan_transcripts.py`** — bounded scanner (run in Step 1).
