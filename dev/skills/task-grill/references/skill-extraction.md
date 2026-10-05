# Skill-extraction questions

> Source: "AI Delegation Loop Playbook" (sdk-kim-builds.com) — Prompt 1 (interview-driven
> SKILL.md extraction). Adapted: slot coverage replaces its fixed "≥8 questions" count.

Use this file when the Outcome is a new or substantially rewritten skill (a SKILL.md).
The goal is the judgment the user would never write down unprompted — that part makes the
skill's output match how the user actually works. Each slot must end resolved: by the user's
answer, by a repo lookup (SKILL.md Rule 3), or by an explicit "N/A". Ask only slots the request and
the repo leave unsettled. Anchor questions on the most recent real instance of the job
("Last time you did this, what did you do first?"), not on the abstract procedure.

| Slot | Question to ask | Default recommendation |
|------|-----------------|------------------------|
| **Purpose** | In one line, what does this job produce, and for whom? | Draft from the request; ask only to confirm. |
| **Triggers** | What exact words do you use when you want this done? | The user's phrasing for running the job, not their request to create the skill; ask if neither the conversation nor the repo shows it. Vague triggers ("help with X") never fire. |
| **Inputs** | What do you read or pull to do it, and where does each live? | Paths/sources found in the repo; ask only for ones not found. |
| **Steps** | Walking through the last real instance — what did you do, in order? | The procedure as recorded in the repo or the request, if either has it; else no default — ask the user. |
| **Decision rules** | Where did you make a judgment call, and what tipped it? | No default; probe each step that has a branch. |
| **Done / verification** | What would tell you at a glance that a result is bad, checked against a source? | 5–10 items, each externally checkable (number traces to source file, link resolves, test passes). Reject "professional", "clear". |
| **Exceptions** | When does this job go differently or stop? | Cases surfaced in Steps; ask once for any others. |
| **Toolbox** | What do you rebuild by hand each time (script, template, reference list, past good example)? | Existing scripts/templates in the repo to reuse; else "none yet". |

Record Purpose in `Outcome:`. Append the other seven slots as a `Skill slots:` block after the
four fields — the caller writing the SKILL.md needs them verbatim. Done/verification, Decision
rules and Exceptions describe how the future skill checks and branches at runtime, so they go
there too, not in `Success:`/`Constraint:`: those two stay the building PR's own criteria.
`Success:` names each Done/verification item, Decision rule and Exception as one such
criterion ("SKILL.md checks/handles <item>"), so none is lost before a caller reads
`Skill slots:`. List all seven, including repo-resolved ones (with the source path) and "N/A" ones. A slot with no default left
unanswered in a non-interactive run goes to the handoff as unresolved (SKILL.md Rule 4), never as "N/A".
