# Measure and focus the review cycle

This design follows [How the Claude Code team does code review](https://claude.dev/blog/solving-code-review-at-anthropic/)
(published 2026-10-15, read 2026-11-26) and uses `agent-toolkit@6785caa` as the baseline.

## User Stories

- A maintainer changing a reviewer can see its recall on every escaped-defect fixture. CI
  catches stale scores, and maintainers have an intake path for the next confirmed escape.
- A maintainer can measure false positives and other dropped findings by reviewer, including
  after the active review contract is retired.
- An author fixing a blocking bug checks the branch diff for the same bug pattern in the
  same pass.
- A repository owner can specify failure criteria, nit budgets, skipped paths and
  evidence expectations in their root `REVIEW.md`.
- An author can distinguish a branch regression from a confirmed bug that already existed
  in code the branch touches or reads. The latter goes to the review backlog.
- A review can pass with comment cleanup still outstanding. Existing comment rules remain
  available through a separate advisory pass.

## Implementation and Testing Decisions

- Reuse the existing recall fixture runner. Require the scorecard to match the inputs for a
  successful full run. CI checks the input fingerprint and leaves grading to a maintainer.
- Capture dispositions through the existing notes command, keyed by finding so late sources
  can be counted without counting the same finding twice. Preserve rows when retiring or
  replacing the contract. Keep the `comments` source for comparing advisory pass behavior.
- Use the existing Claude `code-review` skill for blocking findings. The local review in Claude
  Code 2.1.332 read and cited root `REVIEW.md` in an isolated fixture. Reuse its guidance and read
  the file once if the skill omitted it. Codex companion requires branch-scoped adversarial
  mode for custom instructions. Standalone `codex review` cannot combine `--base` and custom
  instructions, so supply the branch comparison in the custom prompt. Codex and agy use the
  committed root file to keep local edits out of the review request. For files over 8 KiB, the
  prompt directs the reviewer to read that same Git object to stay within process argument limits.
- The comment scheduler can change independently of the comment rules. If advisory edits break
  required checks, withdraw them and check the remaining candidate before merge.
- Exercise both Claude modes, Codex prompt transport and agy's priority tags with launcher
  regression tests. Test disposition preservation in the existing cycle-state suite and rerun
  the full recall suite for the prompt changes.
