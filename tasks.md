## Review Backlog

### PR #47 — [HARNESS] CI checks, validate-harness, platform-specs, version bumps (2026-06-12)

- [ ] [debt] Both `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` unset → hook command collapses to empty path with no error (source: pr-review-toolkit:review-pr) — `dev-tools/hooks.json:9`
- [ ] [debt] `grep -Iq` exit code 2 (I/O error) silently treated as binary file → false PASS on unreadable script (source: pr-review-toolkit:review-pr) — `dev-tools/skills/harness-init/scripts/validate-harness.sh:67`
