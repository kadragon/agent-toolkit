# Sprint: codex-review.sh jq partial-parse fallback (PR #51 finding)

status: active

**Scope:** `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh` only — resolve the line 48 jq partial-parse finding from PR #51 review.

**Acceptance criteria:**
- [x] On a jq parse error (`JQ_ERR` non-empty), the possibly-truncated `TEXT` is discarded and the raw JSON is emitted instead, so no truncated review reaches stdout. WARN message states raw fallback is in effect.

**Out of scope:** the line 44 mktemp/trap finding (already resolved in PR #56); any `dev-review-cycle/SKILL.md` or other-file changes.

**Lint/test command:** `bash dev-tools/skills/harness-init/scripts/validate-harness.sh` then `bash -n dev-tools/skills/dev-review-cycle/scripts/codex-review.sh`.

---

## Review Backlog

### PR #62 — hwpx .hwpx_work/ guards (2026-06-15)

- [ ] [debt] `productivity/skills/hwpx/SKILL.md:221` — Workflow 2 multi-stage still shares a fixed `.hwpx_work/`; parallel multi-stage sessions in the same CWD collide. Fix: use a per-stage unique dir (e.g. `.hwpx_work_step_N` or captured `mktemp -d`). (source: agy) — P3
- [ ] [debt] `productivity/skills/hwpx/SKILL.md:131-157` — inline-build example has no `trap 'rm -rf ...' EXIT`; under `set -euo pipefail` an error before the cleanup line leaks `.hwpx_work/`. Fix: `trap 'rm -rf .hwpx_work' EXIT` after the `mkdir -p`. (source: agy) — P3

### PR #59 — failure-log cross-platform fix (2026-06-15)

- [x] [debt] `dev-tools/hooks/failure-log/log.py:44` — Windows no-op `_lock`/`_unlock` makes `append_capped` read-modify-write unguarded; two concurrent PostToolUse hook processes targeting same repo log can race and drop/duplicate entries. Fix: implement `msvcrt.locking()` in the ImportError branch, or switch append to `O_APPEND` + separate MAX_LINES trim pass. (source: pr-review-toolkit:review-pr, code-review) — P2 *(resolved: PR #60 — msvcrt LK_NBLCK branch)*

### PR #57 — start-task bundle candidates (2026-06-15)

- [x] [debt] `start-task/SKILL.md:50` — type-compat rule says "[FEAT] bundles only with [FEAT]" but silent on whether [FIX]/[DEBT]/[DOCS]/[HARNESS]/[TEST] may cross-bundle. Add sentence: "Types within [FIX]/[DEBT]/[DOCS]/[HARNESS]/[TEST] may bundle with each other." (source: review, confidence 72) — P2 *(resolved: PR #58 — sentence added, SKILL.md:52)*

### PR #52 — hwpx .hwpx_work/ temp dir cleanup (2026-06-14)

- [x] [debt] `SKILL.md:132` — `mktemp .hwpx_work/section0_XXXX.xml` invalid on macOS; template must end in X's (`.xml` suffix blocks substitution). Pre-existing pattern. Fix: `mktemp .hwpx_work/section0_XXXXXX` (source: agy) — P2 (out-of-scope; pre-existing) *(resolved: PR #62)*
- [x] [debt] `SKILL.md:219` — Workflow 2 multi-stage prose references `.hwpx_work/step_N.hwpx` but no `mkdir -p .hwpx_work` shown before it; `office.py pack` will fail on fresh checkout. Fix: add `mkdir -p .hwpx_work` before stage pack step. (source: codex) — P2 *(resolved: PR #62)*
- [x] [debt] `SKILL.md:152` — concurrent single-file hwpx workflows in same CWD: first to finish wipes `.hwpx_work/` while second is still running. Fix: add comment warning, or use per-invocation suffix. (source: review) — P2 *(resolved: PR #62)*

### PR #51 — next-tasks debt batch (2026-06-14)

- [x] [debt] `dev-tools/hooks/failure-log/log.py:186` — `gi_fd` leaks if `os.fdopen()` raises before `with` block entered; inner `except OSError: pass` catches without closing. Fix: same `try/except OSError: os.close(gi_fd); raise` guard as log_fd. (source: pr-review-toolkit:review-pr, conf 90) — P2 *(resolved: guard already present in current log.py:233-237 — stale finding)*
- [x] [debt] `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:44` — `mktemp` temp file leaks on SIGINT/error between creation and `rm -f`; also no diagnostic when `mktemp` itself fails (set -e aborts silently). Fix: `trap 'rm -f "$_jq_tmp"' EXIT` immediately after mktemp; add `|| { printf 'ERROR: mktemp failed\n' >&2; exit 1; }`. (source: pr-review-toolkit:review-pr, agy) — P2 *(resolved: PR #56 — trap + mktemp guard at lines 44-45)*
- [x] [debt] `dev-tools/skills/dev-review-cycle/scripts/codex-review.sh:48` — jq partial parse edge: if companion output has valid JSON prefix + trailing garbage, jq may populate TEXT and emit stderr. Current code warns but outputs TEXT instead of raw fallback, dropping diagnostic detail. (source: codex) — P3 *(resolved: PR #63 — JQ_ERR non-empty forces TEXT="" → raw fallback)*
- [x] [debt] `dev-tools/hooks/failure-log/log.py:209` — `f.flush()` missing before `fcntl.LOCK_UN`; buffered writes may not reach disk before lock released, allowing parallel reader to see stale data. Pre-existing pattern. (source: agy) — P2 *(resolved: PR #60 — flush before _unlock)*
- [x] [debt] `dev-tools/hooks/failure-log/log.py:188` — `UnicodeDecodeError` from `encoding="utf-8"` not caught by `except OSError`; propagates to `__main__` `except BaseException: pass` (silent, no disruption). Pre-existing. Fix: add `errors="replace"` or wrap with `except (OSError, UnicodeDecodeError)`. (source: agy) — P2 *(resolved: PR #60 — inner+outer except widened; log write preserved)*

### PR #54 — start-task skill (2026-06-14)

- [x] [debt] `SKILL.md:59` — plan mode gate trivial/non-trivial conditions still partially overlap: "1–2 files AND not [FEAT]/[REFACTOR]" skip vs "≥3 files OR [FEAT]/[REFACTOR]" enter — a 1-file `[FEAT]` now routes to non-trivial (correct) but the OR logic may still mis-route 2-file `[REFACTOR]` (source: review, pr-review-toolkit) — P2
- [ ] [debt] `.claude/trigger-routes.json:4` — `start.*work` pattern can match "start implementing a skill"; no guard for `implement|구현` to skip to skill-dev-orchestrator route instead (source: review) — P2
- [x] [debt] `SKILL.md:40` — Step 2 table "1 candidate → proceed" doesn't check deferred status inline; the deferred check is only in the table note, which can be missed. Move deferred check to an inline branch in the table (source: agy) — P2
- [x] [debt] `SKILL.md:54` — `backlog-template.md:15` documents `[>]` setter as "Human on sprint start" only; start-task writes `[>]` programmatically. Update `harness-init/references/backlog-template.md` to add "or start-task skill" as a permitted setter (source: pr-review-toolkit) — P2 *(resolved: PR #58 — backlog-template.md setter now lists start-task skill)*
- [x] [debt] `SKILL.md:22` — prerequisites list `backlog.md`/`docs/workflows.md` but sprint body reads `docs/eval-criteria.md` (Sprint Contract) and `docs/conventions.md` (version bump). Add both to prerequisites guard (source: pr-review-toolkit) — P2
- [x] [debt] `SKILL.md:51` — branch name fallback documented for no-[type]-tag items but no warning emitted when falling back; silent assumption can produce wrong branch prefix (source: pr-review-toolkit) — P2
- [x] [debt] `SKILL.md:47` — inner step labels use "workflows.md Step N" but SKILL.md outer steps are also numbered 1–4; "before workflows.md Step 2" could be misread as "before SKILL.md Step 2". Prefix all inner refs as "workflows.md Step N" consistently (partial, some still ambiguous) (source: pr-review-toolkit) — P3 *(resolved: PR #58 — bare "Steps 0–5/Step 6" prefixed with "workflows.md")*
- [x] [harness] `SKILL.md:31` — P-label sort order documented, but missing-label placement note is implicit. Explicit "unlabelled items sort after P3" already present; verify it remains after future edits (source: review, pr-review-toolkit) — P3 *(resolved: verified present, SKILL.md:43)*
- [ ] [debt] `.claude/trigger-routes.json:4` — route instruction "Do NOT inline-pick or inline-implement" conflicts with SKILL.md line 66 which allows "inline edit" for ≤2 files. Reword route to "Do NOT skip the skill" (source: pr-review-toolkit, conf 70) — P3
- [x] [debt] `SKILL.md:65` — implementer brief spec mentions "Sprint Contract + absolute paths + lint/test command" but `docs/delegation.md` four-field format (Objective/Output format/Tools/Boundaries) not referenced. Add pointer to delegation brief template (source: agy, pr-review-toolkit) — P3 *(resolved: PR #58 — four-field pointer added, SKILL.md:133)*

### PR #47 — [HARNESS] CI checks, validate-harness, platform-specs, version bumps (2026-06-12)

- [x] [debt] Both `PLUGIN_ROOT` and `CLAUDE_PLUGIN_ROOT` unset → hook command collapses to empty path with no error (source: pr-review-toolkit:review-pr) — `dev-tools/hooks.json:9`
- [x] [debt] `grep -Iq` exit code 2 (I/O error) silently treated as binary file → false PASS on unreadable script (source: pr-review-toolkit:review-pr) — `dev-tools/skills/harness-init/scripts/validate-harness.sh:67`
