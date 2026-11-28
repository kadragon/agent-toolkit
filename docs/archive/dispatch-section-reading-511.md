# Dispatched section reading measurement

[Issue #511](https://github.com/kadragon/agent-toolkit/issues/511) tracks the
section-reading guide released in dev 5.0.8 by
[PR #540](https://github.com/kadragon/agent-toolkit/pull/540).

The dispatched child for [issue #539](https://github.com/kadragon/agent-toolkit/issues/539)
ran with the released dev 5.0.10 plugin. Its handoff named the phase index,
and the transcript shows separate reads of `task-next/SKILL.md` ranges 1–125,
126–179, and 210–240. It read the worktree instructions as a standalone
reference and requested different ranges of `references/cycle.md` for the
branch, contract, and implementation and handoff phases. The child completed
independent review and CI for [PR #560](https://github.com/kadragon/agent-toolkit/pull/560)
before handing it back for merge.

## Pre-merge token totals

All three runs were dispatched as single GitHub issues in isolated worktrees
using Codex `gpt-6.2-sol` with high reasoning effort. They covered review
workflow work and reached the pre-merge gate after review and CI.
[#504](https://github.com/kadragon/agent-toolkit/issues/504) changed review retry
and verification rules. [#522](https://github.com/kadragon/agent-toolkit/issues/522)
changed how the review cycle pins a PR head. #539 independently reviewed a
historical merge, reproduced and queued findings, and recorded the findings
in its own reviewed PR.

| Dispatch | Observed intake | Input tokens | Cached input tokens |
| --- | --- | ---: | ---: |
| [#504, PR #529](https://github.com/kadragon/agent-toolkit/pull/529) | Whole task-next and cycle files | 17,237,450 | 17,032,192 |
| [#522, PR #532](https://github.com/kadragon/agent-toolkit/pull/532) | Whole task-next and tree files | 14,519,583 | 14,325,376 |
| [#539, PR #560](https://github.com/kadragon/agent-toolkit/pull/560) | Section reads with released dev 5.0.10 | 11,639,276 | 11,450,496 |

Read the last `event_msg/token_count` with a non-null
`info.total_token_usage` immediately before the first `task_complete` that
reports the PR ready. Use `input_tokens` directly since it already includes
`cached_input_tokens`. This excludes later turns that resync or clean up the
worktree. The transcripts have 124, 107, and 95 token-count events up to that
point, respectively.

The section-guided run used 32.5% fewer input tokens than #504 and 19.8% fewer
than #522. The tickets differed in implementation scope and review rounds.
These totals measure actual dispatches. They do not isolate the reduction
attributable to the reading guide.
