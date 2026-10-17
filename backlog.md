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

### PR #313 — mods status band above the prompt (2026-10-11)

- [ ] [FIX] On Windows in the Wave terminal the band sometimes shows broken glyphs or stale cells (e.g. `559m` where `duration()` can only emit `59m`); macOS renders it correctly, colors included (user check, 2026-10-17). Suspect the ambiguous-width glyphs the row emits — the effort mark (`○◔◑◕●`), the `█░` context bar, `⏱️` with its variation selector — measured at one cell by the engine but drawn at two by the terminal, so a redraw leaves cells behind; unverified — mods/hooks/status-band/format.ts *(deferred: needs a Windows + Wave session to reproduce; this machine is macOS)*

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `agy-review.sh` appends to its own `timings.log` from dev 4.11.3, but no agy rows exist yet; a run that hits the cap logs as `status=empty` or `failed` at elapsed≈900s — revisit once real cycles have logged agy runs)*
