# Out-of-Scope Review Findings

Deferred items surfaced during task-review. Not blocking; triage later.

## backlog_candidates

- [ ] **[P2] `tokenize()` does not strip fenced code blocks** — `_strip_html_comments` blanks `<!-- … -->` before tokenizing, but a ```` ``` ````-fenced block gets no such treatment, so a `#`/`##`/`###` line inside a code sample is parsed as a real heading. This corrupts candidate *selection* (a fake heading truncates the enclosing region, so a real checkbox after it can stop counting toward its heading), not just the zero-candidate diagnosis. Pre-existing — predates the diagnosis work, found by qa-verifier while probing it. Fix: blank fenced spans line-count-preserving, exactly as `_strip_html_comments` does, and add a fixture where a fenced `## Fake` sits between a heading and its items.

## Delegation-mandate removal (PR #169 follow-ups)

- [ ] **[P3] `dev/skills/task-next/SKILL.md:256` label drift** — the block is titled `**QA (workflows.md Step 4 — mandatory)**`, but `docs/workflows.md` Step 4 no longer mandates delegation. The skill's own ALWAYS-spawn-`qa-verifier` rule is legitimate (the global layer permits "a skill directs"); only the attribution to workflows.md is stale. Drop the `— mandatory` parenthetical or restate it as the skill's own bar.
- [ ] **[P2] Local `.claude/agents/*.md` descriptions still carry the removed mandates** — `qa-verifier` ("ALWAYS invoke after any implementer run or source edit"), `implementer` ("ALWAYS spawn … do NOT inline-implement"), `explorer` ("Trigger on first edit … OR target area has >3 files"). AGENTS.md states auto-invocation is description-driven, so these descriptions are the *effective* layer while the docs are the nominal one. Untracked (`.gitignore`: `.claude/agents/`), so out of any PR's diff — decide whether to rewrite them as fit-descriptions or keep the stricter local bar deliberately.
- [ ] **[P3] Generated agent instances never resync with their template** — `harness-init` Step 4b writes `.claude/agents/{role}.md` per repo from `references/teammate-role-template.md`, but nothing pulls template improvements back into existing repos. `qa-verifier.md` is at 4 distinct hashes / 27–36 lines across agent-toolkit, prompt-vault, moe-tracker, knue-www-short-url. Some divergence is intended (repo-specific test/lint commands); confirm which parts should be common before building any resync.
- [ ] **[P3] `agy-review.sh` prints its failure sentinel on a successful run** — during PR #169 the script exited 0 with a complete review, yet the output ended with `{"agy_review":"failed"}`. Either the script emits the sentinel itself, or the caller's `|| echo` fallback fires on a non-fatal condition. Harmless here (the review was consumed) but it will misclassify a real failure. Reproduce and fix in `dev/skills/task-review/scripts/agy-review.sh`.

## task-audit-nudge

The self-improve-nudge hook was retired for the manual `harness-capture` skill,
which is now scriptless (reflects on the live conversation — no transcript parse).
So the `detect_signals` / `encode_project` / `config_dir` items that were carried
into its old `scan_session.py` are moot for this skill. `task-audit-nudge` still
has its own copies; residual items below.

- [ ] **[P3] `encode_project` key collision** — `/tmp/foo.bar` and `/tmp/foo-bar` both encode to `-tmp-foo-bar` (codex C2). The verbatim `encode_project` lives in `task-audit-nudge` and `harness-curate/scan_transcripts.py`; extremely unlikely in practice. If fixed, fix both together (append a short path hash) to keep them consistent.
- [ ] **[pre-existing] `task-audit-nudge.config_dir` has the Codex/CLAUDE_PLUGIN_ROOT precedence bug** — under Codex, `CLAUDE_PLUGIN_ROOT` is set as a compat alias, so its `config_dir()` returns `~/.claude` instead of `~/.codex`. Fix: check `CODEX_HOME` (and a `/.codex/` script path) before falling back to the Claude default.
