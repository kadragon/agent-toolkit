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
(`references/definition-of-done.md`), 2026-08-10.

- [ ] Add `docs/definition-of-done.md` — a standing, per-repo bar separate from a task's acceptance
      criteria (regression test exists · lint/test green · no out-of-scope edits · owning doc synced),
      then reference it from the Sprint Contract template in `docs/eval-criteria.md` and from the
      `qa-verifier` brief in `task-new`/`task-next`, so verification no longer depends entirely on
      how well one contract's criteria were worded.

## Harness — adversarial QA brief + finding classification

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/doubt-driven-development/SKILL.md`), 2026-08-10.

- [ ] Fix the QA spawn brief in `task-new`/`task-next` to pass the contract and the artifact only,
      never the orchestrator's own reasoning or conclusion, and to instruct the verifier to look for
      violations rather than confirm compliance — the current brief invites agreement bias.
- [ ] Add a finding-classification rule to the QA retry path: a finding caused by an unclear or
      incomplete Sprint Contract fixes the **contract** first, before any implementer respawn. Today
      both skills route every blocking finding to `implementer`, so a contract defect is silently
      re-litigated as an implementation defect.

## Harness — non-interactive contract for `task-*` skills

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(Loading Constraints in `skills/interview-me/SKILL.md`, `skills/doubt-driven-development/SKILL.md`),
2026-08-10.

- [ ] Define behavior when no live user is reachable (`/loop`, cron, subagent) for the interactive
      gates: `task-grill`'s interview, `task-next` Step 2 selection and Step 2.5 lite-path offer,
      `task-new` Step 3's plan-mode approval. Each needs a stated default plus an announced skip;
      today all of them block indefinitely waiting on a reply that cannot arrive.

## Harness — task-grill restate + explicit-confirm gate

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/interview-me/SKILL.md`), 2026-08-10.

- [ ] Add a closing restate block to `task-grill` (Outcome / Success / Constraint / **Out of scope**)
      that the caller feeds straight into the Sprint Contract, plus an explicit-yes gate — "알아서
      해줘" / "좋아 보여" / silence do not close the interview. The `Out of scope` field of every
      Sprint Contract is currently authored with no procedure that produces it.

## Harness — Sprint Contract sizing and verification rules

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`skills/planning-and-task-breakdown/SKILL.md`, `skills/incremental-implementation/SKILL.md`,
`skills/test-driven-development/SKILL.md`), 2026-08-10.

- [ ] `task-tickets`: cap ticket size at authoring time (≈5 files / one subsystem; a title needing
      "and" is two tickets). Only `task-next`'s >8-item guard exists today, and it fires at execution
      time, after the oversized ticket is already written.
- [ ] `task-new`/`task-next`: require a per-item lint/test checkpoint inside a ≥2-item sprint instead
      of a single QA pass at the end, so a failure in the first item cannot hide until handoff.
      Do NOT adopt per-slice commits — they conflict with `task-review`'s single-commit contract.
- [ ] Sprint Contract authoring: when the tag is `[FIX]`, require an acceptance criterion naming a
      test that fails before the fix. The rule exists in the global instruction layer but no
      contract-authoring step enforces it, so `qa-verifier` has nothing to check it against.

## Harness — deterministic skill trigger/collision check

Source: comparison against [addyosmani/agent-skills](https://github.com/addyosmani/agent-skills)
(`evals/`, `scripts/run-evals.js` — three-tier structural / trigger-routing / behavioral split),
2026-08-10.

- [ ] `docs/eval-criteria.md` weights Trigger Accuracy at 30% but prescribes a model-judged test,
      which contradicts this repo's mechanical-enforcement-first rule. Build a CI check that ranks
      each skill's `description:` against declared positive/negative prompts and flags near-collisions
      between two descriptions. Sizing note: this is a new script + per-skill fixtures across every
      dev and prod skill — spec it before implementing, do not treat it as one sprint.

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
