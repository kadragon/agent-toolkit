# Backlog

## Self-improvement loop — Signal 8 verifier-grounded failures (D1)

Source: `docs/design/harness-self-improvement-loop.md` D1.

## Self-improvement loop — loop contract + prediction schema (D5+D3)

Source: `docs/design/harness-self-improvement-loop.md` D3, D5.

## Self-improvement loop — validation gate in curate routing (D2)

Source: `docs/design/harness-self-improvement-loop.md` D2.

## Self-improvement loop — prediction re-audit step (D4)

Source: `docs/design/harness-self-improvement-loop.md` D4.

## Self-improvement loop — capture prediction line (D6)

Source: `docs/design/harness-self-improvement-loop.md` D6.

## Harness — Definition of Done floor

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`references/definition-of-done.md`), 2026-08-10. `.claude/agents/qa-verifier.md` → `## Checks
(always run)` already carries a standing floor (version bump, capture-before-use, lint/test exit 0),
so this extends that one list rather than creating a second that can drift from it.

- [ ] [HARNESS] Extend qa-verifier's `## Checks (always run)` with the missing standing gates (no out-of-scope edits, owning doc synced) and reference that list from the Sprint Contract template in `docs/eval-criteria.md`

## Harness — adversarial framing in the QA brief

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/doubt-driven-development/SKILL.md`), 2026-08-10. Both skills currently tell the verifier to
check "against those criteria rather than impressions" — neutral phrasing, with no instruction to
hunt for violations.

- [ ] [HARNESS] Add an explicit "find violations, do not confirm compliance" instruction to the qa-verifier spawn brief in `task-new` and `task-next`, and state that the orchestrator's own reasoning is not passed to the verifier

## Harness — contract-misread class in the QA retry path

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/doubt-driven-development/SKILL.md` → RECONCILE precedence), 2026-08-10.

- [ ] [HARNESS] Route a blocking QA finding caused by an unclear or incomplete Sprint Contract to a contract fix before any implementer respawn — `task-new` and `task-next` today send every blocking finding to `implementer`, so a contract defect is re-litigated as an implementation defect

## Harness — non-interactive defaults for `task-*` gates

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(Loading Constraints in `skills/interview-me/SKILL.md`, `skills/doubt-driven-development/SKILL.md`),
2026-08-10.

- [ ] [HARNESS] Give each interactive gate a stated default plus an announced skip when no live user is reachable (`/loop`, cron, subagent): `task-grill`'s interview, `task-next` Step 2 selection and Step 2.5 lite-path offer, `task-new` Step 3 plan-mode approval

## Harness — task-grill restate field shape and confirm gate

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/interview-me/SKILL.md`), 2026-08-10. `task-grill` Flow step 5 already summarizes resolved
decisions and Rule 4 already blocks acting before confirmation; the delta is the field shape and the
close condition, not the existence of a summary.

- [ ] [HARNESS] Give `task-grill`'s closing summary a fixed field shape (Outcome / Success / Constraint / Out of scope) that feeds the Sprint Contract directly, and add the rule that "알아서 해줘" / "좋아 보여" / silence do not close the interview

## Harness — concrete ticket size cap in task-tickets

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/planning-and-task-breakdown/SKILL.md` sizing table), 2026-08-10. `task-tickets` Step 2
("sized for exactly one Sprint Contract") and Step 5 (one item per heading) are authoring-time rules
already, but neither gives a number; the only numeric guard is `task-next`'s >8-item check, which
fires at execution time.

- [ ] [HARNESS] Add a concrete cap to `task-tickets` Step 2 — roughly 5 files / one subsystem, and a title that needs "and" is two tickets

## Harness — per-item checkpoint inside a multi-item sprint

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/incremental-implementation/SKILL.md`), 2026-08-10. Scope is `task-next`'s default
multi-item group path only: `task-new` runs exactly one ticket per invocation, and batch mode
(`references/batch.md` A5) already spawns a `qa-verifier` per unit. Per-slice commits are excluded —
the "Do NOT commit" rule reserves committing for `task-review` Step 1, one commit per review cycle.

- [ ] [HARNESS] Require a per-item lint/test checkpoint inside `task-next`'s default ≥2-item group sprint instead of a single QA pass at the end, so a failure in the first item cannot hide until handoff

## Harness — `[FIX]` reproduction criterion in the Sprint Contract

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/test-driven-development/SKILL.md` Prove-It), 2026-08-10. `docs/conventions.md` already
states `[FIX] | Bug fix — requires reproduction step before fix`; no contract-authoring step turns it
into something `qa-verifier` can check.

- [ ] [HARNESS] Require an acceptance criterion naming a test that fails before the fix whenever the Sprint Contract's tag is `[FIX]`, citing `docs/conventions.md` as the owning rule

## Harness — deterministic skill trigger/collision check

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`evals/README.md`, `scripts/run-evals.js` — structural / trigger-routing / behavioral tiers),
2026-08-10. `docs/eval-criteria.md` weights Trigger Accuracy at 30% but prescribes a model-judged
test, against this repo's mechanical-enforcement-first rule.

- [ ] [HARNESS] Build a CI check that ranks each skill's `description:` against declared positive/negative prompts and flags near-collisions between two descriptions *(deferred: needs a `docs/design/` spec first — new script plus per-skill fixtures across every dev and prod skill, not one sprint)*

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
