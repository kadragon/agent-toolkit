# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Dispatch — result and send robustness (2026-11-23)

- [ ] [fix] `dispatch.py collect` and `send --continue` reject a child's `result.json` that lacks `status` (`cannot read dispatch result …: invalid status, phase, or summary`). A Codex child wrote `{"phase":"review","pr":779,…}` mid-cycle, then its turn was interrupted; the home session could not continue it with `send --run --continue` and fell back to raw `hc send`, which left a paste in the idle composer (`started: false`) until Enter was pressed by hand. Either treat a missing `status` as `working` (keeping the other fields), or have the child contract require `status` on every write. Done-when: a receipt whose result has no `status` still collects and accepts `send --continue`, covered by a test in `dev/skills/dispatch/scripts` — dev/skills/dispatch/scripts/dispatch.py

- [ ] [fix] Codex first-task delivery fails silently enough to lose handoff fields. In the 2026-11-23 KNUE wave, two of three `launch --task` calls did not deliver: one withheld the task because a stray draft (`or`) sat in the idle composer (`no clear Codex input line`), one ended with `Herdr could not confirm delivery` while the composer was empty. Afterwards `send --run <receipt> [--continue]` kept refusing with `previous delivery is unconfirmed`, so the home session fell back to raw `hc send` and the verbatim request/unit/Git-limits block never reached that child. Clear a non-empty idle composer before typing (or report its text), retry an unconfirmed delivery once after re-reading the screen, and let `send` accept a receipt whose child has since started a working turn (or add `--mark-delivered`). Done-when: a stray draft and a lost first submit are both recovered by `launch` itself, and `send` works on such a receipt, each covered by a test — dev/skills/dispatch/scripts/dispatch.py
- [ ] [feat] Home-configured handoff lines for `launch`. KNUE repos need the same line in every Codex child's first message ("외부 리뷰 승인: Codex·Claude 허용, agy 제외"), or Codex's auto-approval reviewer refuses task-review's diff egress mid-cycle; the home session forgot it on 2026-11-23 and a child stopped to ask. Let the home repo declare extra handoff lines per repo path prefix (e.g. a file next to `repos/*.md`) that `launch` appends after the verbatim fields. Done-when: a launch into a matching repo carries the configured line without the home session typing it — dev/skills/dispatch/scripts/dispatch.py
- [ ] [fix] Cleanup after a non-merge or killed child. `collect <receipt> --close` refuses with `terminal has no final result or is still running; left intact` after the child reported `ready` by `hc send` and was then killed, so receipts pile up under `%TEMP%/dispatch-*`. On Windows `git worktree remove` also fails with `Permission denied` while the child terminal is alive, and the emptied directory can stay busy afterwards. Allow `--close` on a finished/killed terminal, and document (or script) the order: kill the child, wait for exit, close the receipt, then remove the worktree. Done-when: closing a killed child's receipt succeeds and the skill's cleanup steps state the order — dev/skills/dispatch/SKILL.md, dev/skills/dispatch/scripts/dispatch.py

## Rejected — do not re-file

Format: `dev/skills/harness-init/references/backlog-template.md` → *Rejected — do not re-file*.
The `task-*` edge cuts keep their own list (see the pointer at the top of this file).

- **Flag unpushed commits on the base before `branch` exits 0** (PR #391 follow-up 5a) — rejected by the user on 2026-11-14 when the in-flight gate was shrunk to "is this the base branch"; base freshness is not that gate's question. Re-file only with a recorded cycle whose PR carried unrelated base commits.
- **Gate shell-based memory writes in `memory-guard`** (PR #254 follow-up) — discarded by the user on 2026-10-17 (f8a60d7); no shell-path memory write has been observed. Re-file only with a recorded session where a memory file was written through Bash and bypassed the guard.
- **Run `claude plugin validate ./mods` and `claude plugin test ./mods` in `harness-check.yml`** — discarded by the user on 2026-10-17 (f8a60d7); the local gate in `docs/runbook.md` → *Validate* stands. Re-file only with a recorded mods regression that reached `main` because the local gate was not run. Covers the CI-job decision only: `check_test_suites_wired.py` still lists only `*.py` suites, so the mods `*.test.ts(x)` files run in no CI job — that coverage gap is not rejected here.
