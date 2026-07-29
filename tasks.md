# Out-of-Scope Review Findings

Deferred items surfaced during task-review. Not blocking; triage later.

## backlog_candidates

- [ ] **[P2] `tokenize()` does not strip fenced code blocks** — `_strip_html_comments` blanks `<!-- … -->` before tokenizing, but a ```` ``` ````-fenced block gets no such treatment, so a `#`/`##`/`###` line inside a code sample is parsed as a real heading. This corrupts candidate *selection* (a fake heading truncates the enclosing region, so a real checkbox after it can stop counting toward its heading), not just the zero-candidate diagnosis. Pre-existing — predates the diagnosis work, found by qa-verifier while probing it. Fix: blank fenced spans line-count-preserving, exactly as `_strip_html_comments` does, and add a fixture where a fenced `## Fake` sits between a heading and its items.

## teammate-role-template

- [ ] **[P2] `persona-actor.md` fails the new `validate-harness.sh` §11 spine check** — it carries frontmatter but zero body sections, so §11 WARNs on it every run. Its own description says "No tools, no file access — pure role-play, **kept lean to minimize per-spawn tokens**", which is a deliberate design, not drift. Unresolved tension: either `teammate-role-template.md` → *Required Body Sections* ("Every role file MUST contain these sections") is too absolute for pure role-play agents and needs a documented exemption class, or `persona-actor` should conform at a per-spawn token cost. Surfaced by the §11 dogfood run; deciding either way is a design change, not a fix.

## task-audit-nudge

The self-improve-nudge hook was retired for the manual `harness-capture` skill,
which is now scriptless (reflects on the live conversation — no transcript parse).
So the `detect_signals` / `encode_project` / `config_dir` items that were carried
into its old `scan_session.py` are moot for this skill. `task-audit-nudge` still
has its own copies; residual items below.

- [ ] **[P3] `encode_project` key collision** — `/tmp/foo.bar` and `/tmp/foo-bar` both encode to `-tmp-foo-bar` (codex C2). The verbatim `encode_project` lives in `task-audit-nudge` and `harness-curate/scan_transcripts.py`; extremely unlikely in practice. If fixed, fix both together (append a short path hash) to keep them consistent.
- [ ] **[pre-existing] `task-audit-nudge.config_dir` has the Codex/CLAUDE_PLUGIN_ROOT precedence bug** — under Codex, `CLAUDE_PLUGIN_ROOT` is set as a compat alias, so its `config_dir()` returns `~/.claude` instead of `~/.codex`. Fix: check `CODEX_HOME` (and a `/.codex/` script path) before falling back to the Claude default.
