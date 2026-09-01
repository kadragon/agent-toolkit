# Backlog

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

### Cut — do not re-file without new evidence

Re-filing requires evidence of the specific kind each item failed on, not a restated intuition:

- **commit-guard merge coverage** — cut at ≈1/3 after scoring, which is what the item itself asked for before any build. Both named sites were read, and neither is a mistake to catch. (1) `merge-and-cleanup.sh:86–89` runs its `git merge --ff-only FETCH_HEAD` only inside `if [ "$MERGE_OK" = "true" ]` — the remote PR merge has already landed — and immediately after `git fetch origin "$BASE_BRANCH"`, so it fast-forwards local `main` onto a commit that is already on the remote. It creates no state and pushes nothing; there is nothing there to guard. (2) `task-next`'s lite path merges to `main` **by design**, reached only when the user picks `[1] 라이트 패스` at Step 2.5 — a decision, not the unintended landing the commit guard exists for. (3) Decisive: the only opt-out `guard.py` implements is the repo-wide `<!-- commit-guard: allow-main -->` marker read by `_marker_present`, and both guards consult it. Marking the repo to let the lite path merge would also switch off the branch guard on `git commit` — trading a 3/3 mechanism for a 1/3 one. A separate marker avoids that only by adding a second opt-in surface to maintain. *Silent* and *Costly* therefore rest on a hypothetical third site; only *Decidable* holds outright. Re-file only with a recorded incident where a merge landed on `main` unintentionally — not from either site above.
- **qa-verifier evidence check (edge #6)** — cut on verified grounds, re-scored from 2.5/3 to ~0.5/3. Three findings, in order of decisiveness. (1) *Decidable fails outright:* the gate cannot fire where the item assumed it would — `task-review` commits through `commit-and-push.sh`, which `commit-guard` did not see at the time this was cut (`docs/design/harness-altitude-audit.md` → *Superseded*, which also records the dev v4.0.33 `--precommit-check` fix that closed it). (2) *Silent and Costly hold only on the lite path:* the full cycle puts every commit through three reviewers, the P0/P1 verifier agent, and CI before merge, so a skipped QA is caught pre-merge and the residual failure is bounded — failing the doc's own "2/3 ships only if the residual failure is unbounded" clause. Only `task-next`'s lite path (direct `merge --no-ff` + push to `main`, no PR, no CI) leaves it unbounded. (3) *The diff match is unworkable even if (1) were fixed:* `task-review` Step 5 commits code edited in Step 4 — review findings applied **after** QA ran — so the evidence hash is stale on every cycle where any finding is applied, and excluding bookkeeping files does not help because these are real code edits. Separately, the gated actor holds the write primitive: an orchestrator with Bash can create the evidence file in one command, so the hook cannot establish even that *something* ran. Re-file only with a recorded cycle where QA was skipped on the lite path and the miss reached `main`.
- **Review transport accounting (edge #7)** — cut on verified grounds: `task-review/SKILL.md` already distinguishes reviewed-empty from skipped and surfaces both — see its *Collect Reviews* 600s-breach rule, the three "Reviewers Skipped: …" labels, and the reviewer prompt's *"Send the array even when it is empty ([]) so the slot is recorded as reviewed, not stalled"* — and both route to the same action. Re-file only with a recorded cycle where the two states led to *different* correct actions.
- **Semantic same-fix detector (edge #8, C2)** — failed Decidable. Re-file only with a deterministic predicate (an exact rule over files/exit codes) that does not require judging whether two attempts are "the same fix".
- **Edges #9, #11, #12** — scored 1.5/3, 0.5/3, 1/3 individually. #9 (assert `tasks.md` has a `status: active` block) was only ever viable as ~3 lines riding inside the edge #6 hook; with #6 cut it has no carrier and does not stand alone at 1.5/3. All three need a recorded failure that escaped the session.

## Harness — auto-memory status lifecycle field

Source: ECC comparison (`memory-vault-format.js` `status: active|superseded|rejected`). The current
schema carries only `type`, so staleness is handled as prose in `harness-capture` ("sediment",
L184-191) and depends on a model noticing. One frontmatter field makes supersession decidable and
gives `harness-curate` a mechanical prune target.

- [ ] [FEAT] Add a `status: active|superseded|rejected` frontmatter field to the auto-memory schema, write it from `harness-capture`, and have `harness-curate` surface non-active entries as prune candidates

## Harness — skill run telemetry

Source: ECC comparison (`scripts/lib/skill-evolution/tracker.js`). Signal 3 ("Underperforming
asset") currently infers underperformance from transcript reading; there is no per-skill outcome
record. Complements — does not duplicate — the `Predicted impact`/`Verified` loop in
`harness-evolution.md` §3, which is qualitative and per-edit rather than per-run.
Not a parallel eval harness: this records outcomes, it does not grade skills (`harness-evolution.md`
§2 keeps eval ownership with `skill-creator`).

- [ ] [FEAT] Record each skill invocation to a bounded JSONL sink (`skill_id`, `skill_version`, `outcome` success/failure/partial, `user_feedback` accepted/corrected/rejected, `recorded_at`) with a retention cap and owner-only file mode

## Harness — Signal 3 consumes run telemetry

Source: ECC comparison (`scripts/lib/skill-evolution/health.js`). Turns the raw sink from the
previous ticket into the declining-asset judgment Signal 3 needs: a 7-day vs 30-day success-rate
delta, with `insufficient-data` when either window is under its minimum run count.

- [ ] [FEAT] Have `harness-curate` Step 3 read the run telemetry sink and mark a skill `declining` on a 7d-vs-30d success-rate drop past threshold, reporting `insufficient-data` rather than a verdict when run counts are too low *(blocked by: 4-skill-run-telemetry)*

## Harness — task-tickets and task-next disagree on a dirty backlog.md

Observed this session, PR #253. `task-tickets` step 7 states its `backlog.md` edit is deliberately
uncommitted — *"This skill makes no commit of its own: the edit rides into whichever commit the
caller's cycle makes next."* `task-next`'s Prerequisites working-tree gate then refuses to run:
on `main`, with no `tasks.md` and no worktree, a dirty tree means *"list the dirty files — do NOT
proceed — and ask the user to commit, stash, or discard first."* So the documented
`task-tickets` → `task-next` sequence always stalls, and the only ways through are a
`[PLAN]` commit-and-merge cycle for the tickets alone or an explicit gate override. Both were
offered to the user this session; the override was chosen.

- [ ] [HARNESS] Reconcile the `task-tickets` hand-off with `task-next`'s working-tree gate — either carve a `backlog.md`-only exception into the gate (as `--tree` already carves one for `tasks.md`) or drop `task-tickets`' no-commit rule, whichever keeps one authority for the rule

## Review Backlog

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Extend `memory-guard`'s secret families to GitLab (`glpat-`) and Google (`AIza…`) keys — raised in PR #254 review, deferred as out of the Sprint Contract's named families (AWS/GitHub/Slack/npm/provider/PEM)
- [ ] [HARNESS] Make `memory-guard`'s `FORBIDDEN_CHARS` and `scripts/ci/check_asset_hygiene.py`'s `_forbidden_chars()` provably in sync — the tables are duplicated by design (one ships, one is CI tooling) but nothing detects a future divergence
- [ ] [FIX] Narrow `memory-guard`'s generic `sk-` provider pattern so hyphenated prose (`sk-8ball-review-checklist-for-the-team…`) stops matching — widening the tail to `[A-Za-z0-9_-]` for `sk-proj-`/`sk-svcacct-` keys traded a false negative for this false positive; a denial costs a rewrite, so it is minor, not free
- [ ] [FEAT] Have `memory-guard` resolve the configured `autoMemoryDirectory` before its path predicate runs — a store relocated outside `.claude` (documented at `dev/skills/harness-init/references/power-user-settings.md:81`) currently bypasses every check, since `_is_memory_file` requires a `.claude` ancestor
- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow
