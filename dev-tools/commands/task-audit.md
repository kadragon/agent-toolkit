---
description: Mine history.jsonl across sessions to surface recurring task shapes and propose agent/skill/hook candidates
argument-hint: "[all | --project <path>] (default: current project)"
allowed-tools: Bash, Read, Glob, Grep, Skill
---

# Task Audit — surface recurring work across sessions

Sessions reset, so "what do I do often" is not in memory — it is in the log. `~/.claude/history.jsonl` accumulates every prompt across all sessions (`display` + `project` + `timestamp`). This command mines that log, semantically clusters recurring **task shapes**, and proposes which ones should become an **agent / skill / hook** per the CLAUDE.md Subagent-factory rule (3× repeat → candidate).

Why semantic clustering (not a counter): the work that *should* become an agent is inline-repeated work — by definition not yet a delegation call, so tool-call counting misses it. The recurring intent lives in the prompt text. You (the model) cluster by meaning.

`$ARGUMENTS` controls scope: empty = current cwd project · `all` = every project · `--project <path>` = one named project.

## Step 1 — Pre-aggregate (cheap, bounded)

Run this to extract a compact, noise-filtered prompt list for the chosen scope. It caps at the 400 most-recent prompts per project and **prints how many were dropped** (no silent truncation).

```bash
python3 - "$ARGUMENTS" <<'PY'
import json, sys, os, collections, re
args = (sys.argv[1] if len(sys.argv) > 1 else "").split()
scope = "current"
named = None
if "all" in args: scope = "all"
if "--project" in args:
    i = args.index("--project")
    named = args[i+1] if i+1 < len(args) else None
    scope = "named"
cwd = os.getcwd()

NOISE = {"hi","ok","okay","yes","no","go","go on","continue","next","thanks","ty",
         "y","n","do it","yep","nope","sure","stop","wait","done","more","again"}
def keep(d):
    d = (d or "").strip()
    if not d: return False
    if d.startswith("/"): return False          # slash command, not a task
    if d.startswith("!"): return False          # shell passthrough
    low = d.lower()
    if low in NOISE: return False
    if len(d) < 12 and len(d.split()) < 3: return False
    return True

rows = collections.defaultdict(list)            # project -> [(ts, display)]
for line in open(os.path.expanduser("~/.claude/history.jsonl"), encoding="utf-8"):
    try: r = json.loads(line)
    except: continue
    p, disp, ts = r.get("project"), r.get("display"), r.get("timestamp", 0)
    if not keep(disp): continue
    if scope == "current" and p != cwd: continue
    if scope == "named"  and p != named: continue
    rows[p].append((ts, disp.replace("\n", " ").strip()))

if not rows:
    print(f"NO DATA for scope={scope} (cwd={cwd}, named={named}).")
    print("Try: /dev-tools:task-audit all")
    sys.exit(0)

CAP = 400
for p in sorted(rows, key=lambda k: -len(rows[k])):
    items = sorted(rows[p], key=lambda x: x[0])
    total = len(items)
    shown = items[-CAP:]
    dropped = total - len(shown)
    print(f"\n### PROJECT {p}  (kept {total} prompts" +
          (f", showing latest {CAP}, dropped {dropped} older" if dropped else "") + ")")
    for ts, disp in shown:
        print("- " + (disp[:200]))
PY
```

## Step 2 — Cluster by meaning

Read the printed list. Group prompts into **recurring task shapes** by *intent*, not exact string (e.g. "add a test for X" + "write tests for Y" + "cover Z with tests" → one cluster "write tests"). Rank clusters by frequency. Ignore one-offs.

## Step 3 — Cross-check existing assets

For each cluster with **≥3** occurrences, check it is not already covered:
- Installed agents/skills/commands: glob `~/.claude/plugins/**/agents/*.md`, `~/.claude/plugins/**/skills/*/SKILL.md`, `~/.claude/skills/*/SKILL.md`, `~/.claude/commands/*.md`.
- Rules already in `~/.claude/CLAUDE.md`.
Drop clusters already served by an existing asset.

## Step 4 — Classify each surviving candidate

Apply the CLAUDE.md promote/demote logic:
- Deterministic single action → **hook** (configure via `update-config` skill).
- Domain knowledge / reusable workflow → **skill** (`skill-creator:skill-creator`).
- Delegatable multi-step task → **agent** (`plugin-dev:agent-creator`).

## Step 5 — Report

Output a ranked table, candidates only (≥3, uncovered):

```
| Cluster | Freq | Example prompts | → Target | Why |
|---------|------|-----------------|----------|-----|
```

Then list near-misses (2×) under a "Watch" line so they are not silently dropped.

Record this run so the SessionStart staleness reminder resets (idempotent):

```bash
python3 - <<'PY'
import json, os, time
p = os.path.expanduser("~/.claude/.task-audit-state.json")
s = {}
try: s = json.load(open(p))
except: pass
s["lastRunMs"] = int(time.time() * 1000)
json.dump(s, open(p, "w"))
print("task-audit run recorded")
PY
```

## Step 6 — Offer to scaffold

Ask whether to scaffold the **top** candidate now. If yes, invoke the matching creator skill (`plugin-dev:agent-creator` / `skill-creator:skill-creator` / `update-config`) with a brief: goal · constraint · exit criterion. Do **not** auto-create without confirmation. Never reimplement a generator — call the skill.
