# Skill-extraction questions

> Source: "AI Delegation Loop Playbook" (sdk-kim-builds.com) — Prompt 1 (interview-driven
> SKILL.md extraction). Adapted: slot coverage replaces its fixed "≥8 questions" count.

Use this file when the Outcome is a new or substantially rewritten skill (a SKILL.md).
The goal is the judgment the user would never write down unprompted — that part makes the
skill's output match how the user actually works. Each slot must end resolved: by the user's
answer, by a repo lookup (Rule 3), or by an explicit "N/A". Ask only slots the request and
the repo leave unsettled. Anchor questions on the most recent real instance of the job
("Last time you did this, what did you do first?"), not on the abstract procedure.

| Slot | Question to ask | Default recommendation |
|------|-----------------|------------------------|
| **Purpose** | In one line, what does this job produce, and for whom? | Draft from the request; ask only to confirm. |
| **Triggers** | What exact words do you use when you want this done? | Quote the user's phrasing from this conversation; vague triggers ("help with X") never fire. |
| **Inputs** | What do you read or pull to do it, and where does each live? | Paths/sources found in the repo; ask only for ones not found. |
| **Steps** | Walking through the last real instance — what did you do, in order? | None; this slot must come from the user. |
| **Decision rules** | Where did you make a judgment call, and what tipped it? | None; probe each step that has a branch. |
| **Done / verification** | How would you tell at a glance that a result is bad? What can be checked against a source? | 5–10 items, each externally checkable (number traces to source file, link resolves, test passes). Reject "professional", "clear". |
| **Exceptions** | When does this job go differently or stop? | Cases surfaced in Steps; ask once for any others. |
| **Toolbox** | What do you rebuild by hand each time (script, template, reference list, past good example)? | Existing scripts/templates in the repo to reuse; else "none yet". |

Record Purpose in `Outcome:`, Done/verification in `Success:`, Decision rules and Exceptions in
`Constraint:`. Append Triggers, Inputs, Steps, and Toolbox as a `Skill slots:` block after the
four fields — the caller writing the SKILL.md needs them verbatim. List every slot there, including
repo-resolved ones (with the source path) and "N/A" ones.
