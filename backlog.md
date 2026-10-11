# Backlog

## 5. P2 — subagent-model-selection-evaluation

Source: `docs/design/harness-policy-alignment.md` → Implementation Decisions, slice 5 and Testing Decisions. Read the paired-run protocol before launching agents; keep the existing headless review-effort experiment separate.

- [ ] [HARNESS] Evaluate approximately 10–20 representative delegated tasks against current settings using paired inputs/criteria: Claude per-spawn overrides and Codex unpinned evaluation roles or built-ins; record requested/actual settings, client/default/forced context, quality, retries, lead review, elapsed time, tokens and measured or explicitly estimated cost; recommend role-specific keep/change/unverified outcomes without removing production pins. Read `docs/design/harness-policy-alignment.md`, slice 5, before forming the contract.

Acceptance: preregister 10–20 task IDs total, finite attempts/time/cost-token budgets per platform, observation methods and benefit thresholds; setting-unverified runs cannot support model-effect claims; recommendations meet the design's paired-input/repeat/quality evidence bars and include total retry/review cost; unfinished platforms remain unverified and pin changes require a follow-up. Approach: staged platform runs using existing evaluation conventions and evaluation-only selection reasons; no permanent telemetry or reviewer-process changes.

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Harness — review effort follow-up

- [ ] [harness] task-review-cycle: measure `EFFORT=high` vs default (and `low`) on a security plant buried in a large, mostly benign diff — f1–f7 (`dev/skills/task-review-cycle/evals/security-effort/RESULTS.md`) are ≤9-line diffs that hit a recall ceiling twice; record the resolved model ID per run (source: code-review PR #298)

## Review Backlog

### PR #315 — status band colors, cache countdown, hook and skill counts (2026-10-11)

- [ ] [debt] status-band builds the installed-plugins path as `${home}/.claude` with a forward slash, unchecked against a Windows `USERPROFILE`; a failed read only leaves the hook count out (source: agy) — mods/hooks/status-band/register.tsx (introduced here)

### PR #313 — mods status band above the prompt (2026-10-11)

- [ ] [debt] status-band keeps the pre-compaction context fill for up to a minute after a manual `/compact`: `session.compact` is a gating hook, so the mod stays out of it and waits for the tick or the next measure (source: code-review) — mods/hooks/status-band/register.tsx
- [ ] [debt] status-band cannot tell that the engine ended its `clock.every` interval after a refused period, so the minute tick is not re-armed in that case (source: code-review) — mods/hooks/status-band/register.tsx
- [ ] [constraint] the band's on-screen look (colors, truncation, the engine's `[-]` mark, wide-character row counts) is checked by mount tests only; nobody has looked at it in a live terminal (source: contract) — mods/hooks/band.tsx

### PR #312 — mods plugin with next-steps suggestions (2026-10-11)

- [ ] [debt] next-steps holds `turn.complete` open for the model call (1.2s measured, 8s cap); whether the engine sequences anything after that chain is unconfirmed — measure in an interactive session before moving the call to a timer (source: code-review) — mods/hooks/next-steps/register.tsx
- [ ] [debt] next-steps digit hotkeys take a bare digit typed into an empty prompt while the band is up, so a reply that starts with `2` picks suggestion 2 instead; the digits are the user-approved V1 UX, so changing them is a product decision (source: code-review) — mods/hooks/next-steps/register.tsx

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*

### PR #111 — commit-guard follow-up

- [ ] [FIX] commit-guard newline/`;`-separator false-block — `_split_segments` in `dev/hooks/commit-guard/guard.py` normalizes unquoted newlines to `;`, but in-chain branch-creation state (`git checkout -b X`) carries only across `&&` (`main`: "Branch attribution may only carry across '&&'"). So a common multi-line script — `git checkout -b X` on one line, `git commit` on a later line — drops the branch switch, falls back to the live branch (`main`), and false-blocks a legitimate commit. Hit during the PR #111 follow-up (worked around by splitting into separate Bash calls). Consider carrying a successful-looking `checkout -b`/`switch -c` across `;`/newline too, or blocking only when no branch switch appears in any prior segment regardless of operator. Preserve the fail-toward-block contract for genuinely ambiguous chains *(recovered 2026-10-11 from the deleted local branch `plan/security-hit-pattern`, written 2026-07-04; the `&&`-only rule is still in the code, the false-block itself was not re-run)*

## mods — next-steps follow-ups

- [ ] [CONSTRAINT] Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml` — today both are a local gate only (`docs/runbook.md` → Validate); `check_test_suites_wired.py` lists only `*.py` suites, so it reports all suites wired while the mods `*.test.ts(x)` files run in no job — extend it in the same change; first settle how CI installs a pinned `claude` CLI and whether `plugin test` runs unauthenticated *(deferred: user chose local evidence for V1 on 2026-10-11)*
- [ ] [FEAT] next-steps V2: rule-based suggestions from explicit harness state before the model fallback — recommend a `dev` command only on a recorded tool result or task state, never on a file merely existing; keep the rules as pure functions beside `mods/hooks/next-steps/suggest.ts` *(deferred: V1 ships model-only by design; needs a spec)*
- [ ] [FEAT] next-steps V3: record suggestion adoption and feed it to `harness-curate` *(blocked by: next-steps V2)*
