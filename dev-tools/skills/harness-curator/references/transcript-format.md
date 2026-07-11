# Transcript Format — record shapes, patterns, encoding

Claude Code stores one `*.jsonl` per session under `~/.claude/projects/<encoded-project>/`. The scanner reads these; this file documents the shapes for ad-hoc grep or for a delegated subagent reading raw transcripts.

## Project-path encoding

Transcript dir name = the absolute project path with **both `/` and `.` replaced by `-`**:

```
/Users/me/Dev/toolkit   → -Users-me-Dev-toolkit
/Users/me/.claude       → -Users-me--claude   (note the doubled dash from the dot)
```

The scanner encodes via `re.sub(r"[/.:\\]", "-", os.path.normcase(os.path.abspath(path)))` — normalizing to an absolute, case-folded path first avoids Windows drive-letter case (`C:` vs `c:`) fragmenting state across sessions. The reverse is lossy (a dash could be `/`, `.`, `\`, `:`, or a literal `-`), so `all` scope reports the **encoded dir name** as the project label, not a reconstructed path.

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
- **Harness friction** — a `user` text matching a recurring-behavior complaint (`you keep`, `every time`, `자꾸`, `매번`, `disable …` …) anywhere in the session. Targets a hook/rule, not the answer, so it carries no `attributionSkill` — collected standalone. Deliberately over-collects (a task complaint shares the phrasing); read before treating as over-protection.
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

# harness-friction candidates (over-collects task complaints — read before routing)
grep -h '"type":"user"' "$DIR"/*.jsonl | grep -i 'you keep\|every.time\|자꾸\|매번\|disable'
```

## Bounds

`history.jsonl` (one line per prompt, all projects) is the cheap prompt-only source. Transcripts are orders of magnitude heavier (dozens of records per session × dozens of sessions × dozens of projects). For `all` scope or large projects, **delegate raw reading to a subagent** and analyze the returned summary inline — do not pull full transcripts into the main context. The scanner already bounds output (`PROMPT_CAP`, `CORRECTION_CAP`, `PROJECT_CAP`) and prints dropped counts.

## Codex CLI sessions

Codex stores one `*.jsonl` per session too, but under a completely different scheme —
**date-partitioned**, not project-partitioned: `~/.codex/sessions/<yyyy>/<mm>/<dd>/rollout-<timestamp>-<uuid>.jsonl`. `~/.codex/archived_sessions/` also exists (retention overflow) and is deliberately excluded from scanning.

There is no project-encoded directory name to key on — the project path lives *inside*
each file, in its first record. The scanner reads only the leading few lines of every
Codex session file to check this before deciding whether to parse the rest (benchmarked
at ~0.1s for 1400+ files on a real machine).

### Record types (`.type` / `.payload.type`)

| `.type` | `.payload.type` | carries |
|---|---|---|
| `session_meta` | — | `.payload.cwd` — the project path. Always (in practice) the first line of the file. |
| `turn_context` | — | turn-level metadata — ignore for analysis. |
| `event_msg` | `sub_agent_activity` | Codex's closest analog to Claude's Agent/Task delegation. `.payload.agent_path` identifies the sub-task (a slug or thread id, NOT a named `subagent_type` like Claude's), `.payload.kind` is `started` / `interacted` (only `started` is counted, to mirror "was this agent invoked in this session"). |
| `event_msg` | `token_count`, `task_started`, `task_complete`, `patch_apply_end`, `entered_review_mode`, `exited_review_mode`, `web_search_end`, `mcp_tool_call_end`, `turn_aborted`, `thread_settings_applied`, `thread_rolled_back` | other lifecycle/telemetry events — not currently mined. |
| `response_item` | `message` | `.payload.role` (`user` / `assistant` / `developer`), `.payload.content[]` — blocks of `type: input_text` (user) or `output_text` (assistant). |
| `response_item` | `function_call` / `function_call_output` | tool calls (`exec_command`, `write_stdin`, MCP tool names) and their output — not currently mined for signals. |
| `response_item` | `custom_tool_call` / `custom_tool_call_output` | e.g. `apply_patch` — not currently mined. |
| `inter_agent_communication_metadata` | — | seen alongside `sub_agent_activity`; not currently mined. |

### Key signals

- **Skill load** — Codex has no dedicated attribution field. Instead, loading a skill
  injects a *synthetic* `role: "user"` message shaped like:
  ```
  <skill>
  <name>dev-tools:next-tasks</name>
  <path>/Users/.../SKILL.md</path>
  ---
  name: next-tasks
  ...
  ```
  Confirmed by reading real session files (found `caveman`, `vault-cleanup`,
  `dev-tools:next-tasks` loads on this machine) — re-verify against real files if this
  format stops matching after a Codex CLI upgrade. Parsed by `_CODEX_SKILL_LOAD_RE`.
- **Harness-injected noise** — several other things also arrive as synthetic `role: "user"`
  messages instead of a separate field: `<environment_context>`, `<user_action>` (e.g.
  review-request scaffolding with the reviewer's output embedded), `<turn_aborted>`,
  `<recommended_plugins>`, `<image>`, `<user_shell_command>`, `<hook_prompt ...>` (Stop-hook
  feedback), `<subagent_notification>` (redundant with `sub_agent_activity`), and a
  repeated `# AGENTS.md instructions for <path>` reinjection every session. None of these
  are free-text human intent — filtered by `_CODEX_NOISE_RE`, mirroring how `keep_prompt()`
  already filters Claude's `<command-message>`/`<system-reminder>`/etc. Found by sampling
  ~400 real session files; re-verify if new tag names appear.
- **Correction / harness-friction** — same `CORRECTION_RE` / `FRICTION_RE` patterns as
  Claude (platform-agnostic, since they just match free text), applied to genuine
  (non-synthetic) `role: "user"` turns.

### Per-project state

Codex has no project directory to hold `.harness-curator-state.json` in, so the scanner
mints one under the same `encode_project()` scheme Claude's side uses, rooted at
`<codex_home>/projects/<encoded>/` — this directory holds only this skill's own
bookkeeping, never real Codex session data (that stays under `sessions/`).
