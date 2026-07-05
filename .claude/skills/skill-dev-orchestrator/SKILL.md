---
name: skill-dev-orchestrator
description: |
  ALWAYS invoke this skill when the user asks to implement a backlog item, fix a skill, add a skill, or do implementation work on this plugin repo. Do NOT inline-implement skill/agent/hook changes.
  Trigger phrases (Korean + English):
  - "백로그 구현", "스킬 수정", "스킬 추가", "훅 수정", "에이전트 수정"
  - "implement backlog", "fix skill", "add skill", "modify hook", "update agent"
  - "backlog item", "백로그 아이템", "이거 구현해줘", "implement this"
  No cross-session resume — scratchpad artifacts are gone once the session ends.
  Skip only if user explicitly says "inline" / "직접" / "without orchestrator".
---

Orchestrates backlog item implementation for the plugin repo. Explore → Implement → Verify → Bump → PR.

**Artifact location:** determine your scratchpad path from your own system prompt at the start of the run. Embed the full path explicitly in every `Agent(...)` spawn prompt below — sub-agents must not guess or reconstruct it.

## Phase 1: Identify Backlog Item

1. Read `backlog.md` — find the item to implement (from user prompt or first `- [ ]` in `## Now`)
2. Confirm item with user if ambiguous (2+ candidates)
3. Write Sprint Contract to `{scratchpad}/00_lead_sprint-contract.md`:
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

Write explorer output to `{scratchpad}/01_explorer_map.md`. Proceed only after map is available.

If gate does not fire: skip Phase 2.

## Phase 3: Implement

```
Agent({
  subagent_type: "implementer",
  prompt: "Objective: implement {backlog item} per sprint contract at {scratchpad}/00_lead_sprint-contract.md. Output format: diff summary + plugin.json bump. Tools: Read/Edit/Write on {files}, Grep/Glob for patterns. Boundaries: do not touch files outside {plugin}/{skill}/."
})
```

Write implementer output to `{scratchpad}/02_implementer_diff.md`.

## Phase 4: QA Verification (mandatory)

```
Agent({
  subagent_type: "qa-verifier",
  prompt: "Objective: verify implementation at {scratchpad}/02_implementer_diff.md against sprint contract at {scratchpad}/00_lead_sprint-contract.md. Pass criteria: all acceptance items green. Output format: criterion/pass/fail/evidence table. Tools: Bash for lint/test, Read/Grep for verification. Boundaries: no production edits."
})
```

Write qa-verifier output to `{scratchpad}/03_qa-verifier_report.md`.

If QA fails: present failures to user. Do NOT retry automatically — user decides whether to continue.

## Phase 5: PR + Review

Invoke `dev-tools:dev-review-cycle` for PR creation, review, and merge.

```
Use Skill(dev-tools:dev-review-cycle)
```

## Error Policy

- 1 agent fails → retry once with the same prompt
- Retry fails → report scratchpad artifact paths to user, stop
- Majority fail → report all failures + scratchpad artifact paths, stop

## Scratchpad Naming

```
00_lead_sprint-contract.md
01_explorer_map.md          (if Phase 2 ran)
02_implementer_diff.md
03_qa-verifier_report.md
```
