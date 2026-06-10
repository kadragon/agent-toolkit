---
name: skill-dev-orchestrator
description: |
  ALWAYS invoke this skill when the user asks to implement a backlog item, fix a skill, add a skill, or do implementation work on this plugin repo. Do NOT inline-implement skill/agent/hook changes.
  Trigger phrases (Korean + English):
  - "백로그 구현", "스킬 수정", "스킬 추가", "훅 수정", "에이전트 수정"
  - "implement backlog", "fix skill", "add skill", "modify hook", "update agent"
  - "backlog item", "백로그 아이템", "이거 구현해줘", "implement this"
  Resume: "이어서", "계속", "based on previous results"
  Skip only if user explicitly says "inline" / "직접" / "without orchestrator".
---

Orchestrates backlog item implementation for the plugin repo. Explore → Implement → Verify → Bump → PR.

## Phase 0: Context Detection

```
_workspace/campaign-state.json missing → Initial run → Phase 1
_workspace/campaign-state.json exists → Resume → read next_entry_point, skip completed phases
```

Read `current_phase` and `tasks`. Report: "Resuming from Phase {N}."

**State file schema** (`_workspace/campaign-state.json`):
```json
{
  "current_phase": 1,
  "next_entry_point": "Phase 2: Explore",
  "tasks": ["<backlog item description>"],
  "completed_phases": [1]
}
```

**Write after each phase completes.** Update `current_phase` to the next phase number and `next_entry_point` to the next phase title. Add the completed phase to `completed_phases`. Without this write, resume will never trigger.

## Phase 1: Identify Backlog Item

1. Read `backlog.md` — find the item to implement (from user prompt or first `- [ ]` in `## Now`)
2. Confirm item with user if ambiguous (2+ candidates)
3. Write Sprint Contract to `_workspace/00_lead_sprint-contract.md`:
   - Scope: target files/skills
   - Acceptance criteria (concrete + testable)
   - Lint/test command
   - Plugin bump type (patch/minor/major)

## Phase 2: Explore (conditional)

**Gate:** target plugin area not explored this session AND has >3 files.

If gate fires:
```
Agent({
  subagent_type: "explorer",
  prompt: "Objective: map {plugin}/{skill} for implementing {backlog item}. Output format: Files/Flow/Constraints/Recommended reads. Tools: Read/Grep/Glob. Boundaries: no edits."
})
```

Write explorer output to `_workspace/01_explorer_map.md`. Proceed only after map is available.

If gate does not fire: skip Phase 2.

## Phase 3: Implement

```
Agent({
  subagent_type: "implementer",
  prompt: "Objective: implement {backlog item} per sprint contract at _workspace/00_lead_sprint-contract.md. Output format: diff summary + plugin.json bump. Tools: Read/Edit/Write on {files}, Grep/Glob for patterns. Boundaries: do not touch files outside {plugin}/{skill}/."
})
```

Write implementer output to `_workspace/02_implementer_diff.md`.

## Phase 4: QA Verification (mandatory)

```
Agent({
  subagent_type: "qa-verifier",
  prompt: "Objective: verify implementation at _workspace/02_implementer_diff.md against sprint contract at _workspace/00_lead_sprint-contract.md. Pass criteria: all acceptance items green. Output format: criterion/pass/fail/evidence table. Tools: Bash for lint/test, Read/Grep for verification. Boundaries: no production edits."
})
```

Write qa-verifier output to `_workspace/03_qa-verifier_report.md`.

If QA fails: present failures to user. Do NOT retry automatically — user decides whether to continue.

## Phase 5: PR + Review

Invoke `dev-tools:dev-review-cycle` for PR creation, review, and merge.

```
Use Skill(dev-tools:dev-review-cycle)
```

## Error Policy

- 1 agent fails → retry once with the same prompt
- Retry fails → preserve `_workspace/`, report to user, stop
- Majority fail → report all failures + `_workspace/` state, stop

## _workspace/ Naming

```
00_lead_sprint-contract.md
01_explorer_map.md          (if Phase 2 ran)
02_implementer_diff.md
03_qa-verifier_report.md
campaign-state.json         (resume state)
```
