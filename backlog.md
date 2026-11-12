# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Review Backlog

### PR #386 — pr-recap pane opens with the branch's Sprint Contract on top (2026-11-12)

- [ ] [harness] `task_nodes.py branch` warns on stderr when the checkout it runs in sits on a branch with commits not on the base, naming `git worktree add .worktrees/<slug>` — a user had to stop an in-place `checkout -b` that would have switched an unmerged cycle's checkout out from under it (source: harness-capture) — dev/skills/task-next/scripts/task_nodes.py
- [ ] [debt] contract section's command match collapses whitespace runs, so `--expected 'a  b'` matches a record of `--expected 'a b'`; compare backticked spans verbatim (source: codex) — mods/hooks/contract-pane/contract.ts `normalize` (introduced here)
- [ ] [debt] contract section draws its `r` reread button only when a contract is shown, so a folded line (no contract, failed first read) can be refreshed only by a cycle command or reopening the pane (source: codex) — mods/hooks/contract-pane/register.tsx `contractSection` (introduced here)

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
