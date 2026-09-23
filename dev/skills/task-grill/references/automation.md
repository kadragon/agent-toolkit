# Automation questions

> Vocabulary adapted from mattpocock/skills `loop-me` (https://github.com/mattpocock/skills).

Use this file when the Outcome is a recurring automation: a hook, a `/loop` or scheduled run, a
CI workflow, a cron job. Each term below is a candidate question, not a required part of the
design. An automation needs no checkpoint, no schedule, and no AI step unless the interview shows
it does. Ask only the questions the request and the repo leave unsettled.

| Term | Question to ask | Default recommendation |
|------|-----------------|------------------------|
| **Trigger** | What starts each run: an event (a push, a new issue, a tool call) or a schedule? | Event. A schedule runs when nothing changed; an event runs only when there is work. |
| **Checkpoint** | Where must a person verify or decide before the run continues? Is there any such point? | None, or one point as late as possible. Do all the work that needs no decision first, then ask once. |
| **Brief** | At a checkpoint, what does the person see? | A short summary: what was produced, why, and a link or path to the full output. Never the raw output. |

Record the Trigger and Checkpoint decisions in the summary's `Constraint:` field. Record the
Brief format in `Success:` when the checkpoint is part of how the result is verified.
