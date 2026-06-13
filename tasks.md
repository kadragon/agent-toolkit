## Review Backlog

### PR #49 — failure-log hook + curator wiring (2026-06-13)

- [ ] [debt] `dev-tools/hooks/failure-log/log.py:append_capped` — log + `.gitignore` writes follow symlinks (plain `open('w')`, no `O_NOFOLLOW`); a pre-planted symlink in `.claude/logs/` could redirect the secret-bearing stderr write, and a pre-existing non-ignoring `.gitignore` is left untouched. Fix: open both with `os.open(..., O_CREAT|O_WRONLY|O_NOFOLLOW)` and always ensure the dir ignore covers the log. Local-only, not remotely exploitable. (source: security-review, conf 40) — P3
- [ ] [debt] `dev-tools/hooks/failure-log/summarize.py:main` — `--help`/`-h` is treated as a path arg (git_root lookup) instead of printing usage. Fix: handle `--help`/`-h` before path resolution. (source: agy) — P3

### PR #47 — [HARNESS] CI checks, validate-harness, platform-specs, version bumps (2026-06-12)

- [x] [debt] Both `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` unset → hook command collapses to empty path with no error (source: pr-review-toolkit:review-pr) — `dev-tools/hooks.json:9`
- [x] [debt] `grep -Iq` exit code 2 (I/O error) silently treated as binary file → false PASS on unreadable script (source: pr-review-toolkit:review-pr) — `dev-tools/skills/harness-init/scripts/validate-harness.sh:67`

### PR #50 — [FIX] dev-review-cycle: emit clean Codex review via --json (2026-06-13)

- [ ] [debt] `status` variable in zsh is read-only — rename to `exit_code` to avoid crash when script run directly in zsh (source: agy) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:30`
- [ ] [debt] Silent raw-JSON fallback when jq absent or `.codex.stdout` null/empty — emit distinct stderr WARN per case (source: review, pr-review-toolkit:review-pr, agy) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:39-42`
- [ ] [debt] Empty `RAW` on companion silent crash (nonzero exit, no stdout) — add fallback `printf 'WARN: codex companion exited %s with no stdout\n'` to stderr (source: review) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:33`
- [ ] [debt] `jq -r ... 2>/dev/null || true` suppresses all jq errors including malformed JSON — log jq stderr before suppressing (source: review, pr-review-toolkit:review-pr) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:40`
- [ ] [doc] Comment at L36-37 omits "jq parse failure" from listed fallback triggers (source: pr-review-toolkit:review-pr) — `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:36`
