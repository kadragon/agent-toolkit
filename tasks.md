## Review Backlog

### PR #52 — hwpx .hwpx_work/ temp dir cleanup (2026-06-14)

- [ ] [debt] `SKILL.md:132` — `mktemp .hwpx_work/section0_XXXX.xml` invalid on macOS; template must end in X's (`.xml` suffix blocks substitution). Pre-existing pattern. Fix: `mktemp .hwpx_work/section0_XXXXXX` (source: agy) — P2 (out-of-scope; pre-existing)
- [ ] [debt] `SKILL.md:219` — Workflow 2 multi-stage prose references `.hwpx_work/step_N.hwpx` but no `mkdir -p .hwpx_work` shown before it; `office.py pack` will fail on fresh checkout. Fix: add `mkdir -p .hwpx_work` before stage pack step. (source: codex) — P2
- [ ] [debt] `SKILL.md:152` — concurrent single-file hwpx workflows in same CWD: first to finish wipes `.hwpx_work/` while second is still running. Fix: add comment warning, or use per-invocation suffix. (source: review) — P2

### PR #51 — next-tasks debt batch (2026-06-14)

- [ ] [debt] `dev-tools/hooks/failure-log/log.py:186` — `gi_fd` leaks if `os.fdopen()` raises before `with` block entered; inner `except OSError: pass` catches without closing. Fix: same `try/except OSError: os.close(gi_fd); raise` guard as log_fd. (source: pr-review-toolkit:review-pr, conf 90) — P2
- [ ] [debt] `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:44` — `mktemp` temp file leaks on SIGINT/error between creation and `rm -f`; also no diagnostic when `mktemp` itself fails (set -e aborts silently). Fix: `trap 'rm -f "$_jq_tmp"' EXIT` immediately after mktemp; add `|| { printf 'ERROR: mktemp failed\n' >&2; exit 1; }`. (source: pr-review-toolkit:review-pr, agy) — P2
- [ ] [debt] `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:48` — jq partial parse edge: if companion output has valid JSON prefix + trailing garbage, jq may populate TEXT and emit stderr. Current code warns but outputs TEXT instead of raw fallback, dropping diagnostic detail. (source: codex) — P3
- [ ] [debt] `dev-tools/hooks/failure-log/log.py:209` — `f.flush()` missing before `fcntl.LOCK_UN`; buffered writes may not reach disk before lock released, allowing parallel reader to see stale data. Pre-existing pattern. (source: agy) — P2 (out-of-scope; pre-existing)
- [ ] [debt] `dev-tools/hooks/failure-log/log.py:188` — `UnicodeDecodeError` from `encoding="utf-8"` not caught by `except OSError`; propagates to `__main__` `except BaseException: pass` (silent, no disruption). Pre-existing. Fix: add `errors="replace"` or wrap with `except (OSError, UnicodeDecodeError)`. (source: agy) — P2 (out-of-scope; pre-existing)

### PR #47 — [HARNESS] CI checks, validate-harness, platform-specs, version bumps (2026-06-12)

- [x] [debt] Both `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` unset → hook command collapses to empty path with no error (source: pr-review-toolkit:review-pr) — `dev-tools/hooks.json:9`
- [x] [debt] `grep -Iq` exit code 2 (I/O error) silently treated as binary file → false PASS on unreadable script (source: pr-review-toolkit:review-pr) — `dev-tools/skills/harness-init/scripts/validate-harness.sh:67`
