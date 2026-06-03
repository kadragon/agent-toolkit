# Transcript Format — record shapes, patterns, encoding

Claude Code stores one `*.jsonl` per session under `~/.claude/projects/<encoded-project>/`. The scanner reads these; this file documents the shapes for ad-hoc grep or for a delegated subagent reading raw transcripts.

## Project-path encoding

Transcript dir name = the absolute project path with **both `/` and `.` replaced by `-`**:

```
/Users/me/Dev/toolkit   → -Users-me-Dev-toolkit
/Users/me/.claude       → -Users-me--claude   (note the doubled dash from the dot)
```

The scanner encodes via `re.sub(r"[/.]", "-", path)`. The reverse is lossy (a dash could be `/`, `.`, or a literal `-`), so `all` scope reports the **encoded dir name** as the project label, not a reconstructed path.

## Record types (`.type`)

| type | carries |
|------|---------|
| `user` | `.message.content` — a string (real prompt) OR a list of blocks. A `tool_result` block means it's tool output echoed as the user role, **not** a prompt. |
| `assistant` | `.message.content` (text + `tool_use` blocks) and `.attributionSkill` / `.attributionPlugin` when a skill was active. |
| `system`, `mode`, `permission-mode`, `file-history-snapshot`, `attachment`, `last-prompt` | metadata — ignore for analysis. |

Records with `.isMeta` or `.isSidechain` true are non-conversational (injected context, subagent side-channels) — skip them.

## Key signals

- **Skill load** — `.attributionSkill` on an `assistant` record (e.g. `"skill-creator:skill-creator"`). This is the reliable signal for *which skill was active*, far better than counting explicit `Skill` tool calls (users rarely invoke skills explicitly). One invocation spans many assistant records, so **count distinct sessions, not records** (the scanner does this).
- **Explicit skill call** — `tool_use` block with `name == "Skill"`, `input.skill == "<plugin:skill>"`. Rare.
- **Agent delegation** — `tool_use` block with `name == "Agent"` or `"Task"`.
- **Correction** — a short `user` text (< 80 chars) matching a negative pattern (`no`, `wrong`, `actually`, `revert`, `아니`, `다시`, `틀렸`, `잘못` …) immediately after a skill-active assistant turn. Heuristic, not exact — confirm by reading.
- **Tool error** — encodings vary; `.toolUseResult.is_error` / `.error`, or an `is_error` `tool_result` block. Best-effort; the correction signal is more reliable for "this asset underperformed".

## Useful grep patterns

```bash
DIR=~/.claude/projects/-Users-me-Dev-toolkit

# which skills were active, ranked
grep -ho '"attributionSkill":"[^"]*"' "$DIR"/*.jsonl | sort | uniq -c | sort -rn

# sessions that used a specific skill
grep -l '"attributionSkill":"skill-creator:skill-creator"' "$DIR"/*.jsonl

# explicit Skill tool invocations
grep -o '"name":"Skill","input":{"skill":"[^"]*"' "$DIR"/*.jsonl
```

## Bounds

`history.jsonl` (one line per prompt, all projects) is the cheap prompt-only source. Transcripts are orders of magnitude heavier (dozens of records per session × dozens of sessions × dozens of projects). For `all` scope or large projects, **delegate raw reading to a subagent** and analyze the returned summary inline — do not pull full transcripts into the main context. The scanner already bounds output (`PROMPT_CAP`, `CORRECTION_CAP`, `PROJECT_CAP`) and prints dropped counts.
