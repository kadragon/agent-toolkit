# Trigger Router Template (UserPromptSubmit hook)

**Problem this solves.** Skill auto-discovery and subagent auto-delegation rely on the model reading every skill/agent description and choosing correctly. Anthropic's own docs say this is the mechanism; field testing (Scott Spence, Anthropic Skill Creator guidance) shows it works ~50% of the time even with well-written descriptions. The model often does the work inline instead of routing.

**Fix.** A `UserPromptSubmit` hook that pattern-matches the prompt and emits an explicit `Use Skill(name)` / `Use Agent(subagent_type=name)` instruction. Explicit instructions outperform description-based discovery — "use this skill" beats "consider this skill."

Source: Anthropic Claude Code docs → "Create custom subagents" (auto-delegation is description-driven), Anthropic Skills authoring docs ("directive descriptions improved triggering on 5 of 6 public skills"), Scott Spence "Claude Code Skills Don't Auto-Activate" (2026).

---

## When to install this hook

Install when **any** of these are true after init:

- Step 4c created at least one orchestrator skill
- Step 4b created at least one `.claude/agents/{role}.md`
- AGENTS.md delegation table has any "Mandatory, blocking" row

Skip only on single-session, single-agent repos with no orchestrator or specialized roles.

---

## Architecture

```
User prompt
  -> UserPromptSubmit hook fires
  -> hook reads prompt + registered routes (.claude/trigger-routes.json)
  -> on match: hook prints "INSTRUCTION: Use Skill(...) ..." on stdout
              (stdout from UserPromptSubmit is appended to the prompt context)
  -> on no match: silent exit 0
```

The hook does **not** invoke the skill itself. It injects an instruction the model will see as part of the prompt. The model still makes the call, but with explicit direction instead of having to discover the right skill from descriptions alone.

---

## Files to create

```
.claude/
  settings.json          # registers the hook
  hooks/
    trigger-router.sh    # hook script
  trigger-routes.json    # editable route table
```

### 1. `.claude/settings.json` (add the hook)

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [{"type": "command", "command": "bash .claude/hooks/trigger-router.sh"}]
      }
    ]
  }
}
```

If `.claude/settings.json` already exists from Step 7 (golden-principle enforcement), merge this entry into the existing `hooks` object — don't overwrite.

> **Note.** `UserPromptSubmit` has no `matcher` field, unlike `PreToolUse`/`PostToolUse`. The shape above is correct as-is.

### 2. `.claude/hooks/trigger-router.sh`

```bash
#!/usr/bin/env bash
# UserPromptSubmit hook: route prompts to skills/agents via explicit instruction.
#
# stdin: JSON payload {"prompt": "...", "session_id": "..."}
# stdout: instruction appended to prompt context (or empty)
# Contract: exit 0 always — never block. Avoid `set -e` so a malformed
# payload or bad route regex cannot turn a parser slip into a blocked prompt.

set -u

ROUTES_FILE=".claude/trigger-routes.json"
[[ -f "$ROUTES_FILE" ]] || exit 0

payload=$(cat)
prompt=$(jq -r '.prompt // empty' <<<"$payload" 2>/dev/null || true)
[[ -z "$prompt" ]] && exit 0

# Parse all routes in one jq fork — avoids 3N forks per prompt.
# Schema per route:
#   .pattern                  — extended regex, matched case-insensitively
#   .instruction              — directive injected on match
#   .skip_if_prompt_matches   — optional regex; abort route if prompt also matches
#
# Fields are joined with ASCII Unit Separator (). Do NOT use TAB —
# `IFS=$'\t' read` collapses consecutive tabs (whitespace IFS rule), which
# eats empty `.skip_if_prompt_matches` values and shifts later columns left.
US=$'\x1f'
routes=$(jq -r --arg us "$US" '
    .[] | [
      (.pattern // ""),
      (.skip_if_prompt_matches // ""),
      (.instruction // "")
    ] | join($us)
' "$ROUTES_FILE" 2>/dev/null || true)
[[ -z "$routes" ]] && exit 0

# First match wins (route order = priority). nocasematch set once, outside loop —
# the heredoc `done <<< "$routes"` runs the loop body in the current shell,
# so shopt scope and `break` semantics are meaningful.
shopt -s nocasematch
matched=""
while IFS="$US" read -r pattern skip instr; do
    [[ -z "$pattern" ]] && continue
    # Untrusted regex from JSON: a malformed pattern fails the test silently.
    # No `set -e`, so a single bad route never blocks the prompt.
    if [[ "$prompt" =~ $pattern ]] 2>/dev/null; then
        if [[ -n "$skip" ]] && [[ "$prompt" =~ $skip ]] 2>/dev/null; then
            continue
        fi
        matched="$instr"
        break
    fi
done <<< "$routes"
shopt -u nocasematch

[[ -n "$matched" ]] && echo "INSTRUCTION (auto-delegation router): $matched"
exit 0
```

### 3. `.claude/trigger-routes.json` (project-specific)

Populate during Step 7b with one route per orchestrator skill and per high-leverage agent role. **Routes must be specific** — overly broad patterns hijack normal conversation.

```json
[
  {
    "pattern": "(review.*pr|pr.*review|리뷰.*pr|코드.*리뷰)",
    "instruction": "Use Skill(pr-review-toolkit:review-pr) to run the multi-agent review. Do NOT inline-review.",
    "skip_if_prompt_matches": "(don't|no orchestrat|skip)"
  },
  {
    "pattern": "(deploy|배포|ship.*prod)",
    "instruction": "Use Skill(deploy-orchestrator). Confirm with user before any irreversible action.",
    "skip_if_prompt_matches": "(dry.?run|preview)"
  },
  {
    "pattern": "(explore.*module|first.*edit|새.*디렉토리)",
    "instruction": "Spawn Agent(subagent_type=explorer) before editing — first-touch discovery rule.",
    "skip_if_prompt_matches": ""
  }
]
```

---

## Authoring routes

For each route ask:

1. **What phrase reliably indicates this skill/agent should run?** (Korean + English variants if bilingual repo.)
2. **What false-positive prompts share that phrase?** (List in `skip_if_prompt_matches`.)
3. **Is the instruction directive?** ("Use Skill(X) — do NOT inline" beats "consider Skill(X)".)
4. **Does the route name a single concrete target?** Routes that say "use one of A, B, C" defeat the purpose; the model picks A every time. Add three routes instead.
5. **Did you run the test command below before merging the route?** Required, not optional — an untested pattern with a bash-regex syntax error will silently never match. The hook handles bad regex defensively but a route that never fires is still dead weight.

**Anti-patterns:**

| Anti-pattern | Why it fails | Fix |
|---|---|---|
| Pattern: `"."` (matches everything) | Hook fires every turn, pollutes context | Use specific trigger phrases |
| Instruction: "Consider using X" | Same problem as a vague description | Use "Use X" or "Spawn X" |
| Routes overlap silently | Model gets two conflicting instructions | First-match-wins via route order |
| Korean-only patterns on English repo | Triggers never fire | Include both languages or drop one |

---

## Testing the router

After creating routes:

```bash
# Simulate the hook payload
echo '{"prompt": "리뷰해줘 PR-42", "session_id": "test"}' | bash .claude/hooks/trigger-router.sh
# Expected stdout: "INSTRUCTION (auto-delegation router): Use Skill(...) ..."

echo '{"prompt": "just print hello world", "session_id": "test"}' | bash .claude/hooks/trigger-router.sh
# Expected stdout: (empty)
```

Add 3–5 test cases per route to a `tools/test-trigger-router.sh` script so the routes don't silently break on future edits.

---

## Maintenance

When the hook fires too often or never:

- **Fires on unrelated prompts** → tighten `pattern` (add word boundaries, narrow keywords) or add to `skip_if_prompt_matches`.
- **Never fires when it should** → run the prompt verbatim through the test command above; usually the pattern is too narrow or in wrong language.
- **Two routes conflict** → reorder routes (top wins) or split the second route's pattern.

Record changes in `references/harness-invariants.md` → "Trigger Router Routes" so future sessions don't reintroduce removed routes.

---

## Why not just rely on descriptions?

Descriptions are the *default* discovery mechanism and they should still be written directively (`ALWAYS invoke when ...`). The router is the **belt** to the description's *suspenders*:

- **Description-only**: ~50% trigger rate reported in Scott Spence's testing (2026).
- **Description + router**: deterministic for prompts that match a route pattern (the model still has to honor the instruction, but the instruction is now in the prompt context rather than buried in a skill description). Exact lift depends on route specificity; descriptions still handle the long tail.

The cost is small — one hook script, one JSON file, runs once per turn in <50ms.
