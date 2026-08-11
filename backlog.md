# Backlog

## Harness — skill description fixture ranking check (Half A)

Spec: `docs/design/skill-trigger-collision-check.md`. Source: comparison against
[addyosmani/agent-skills](https://github.com/addyosmani/agent-skills) (`evals/README.md`,
`scripts/run-evals.js` — structural / trigger-routing / behavioral tiers), 2026-08-10.
`docs/eval-criteria.md` weights Trigger Accuracy at 30% but prescribes a model-judged test,
against this repo's mechanical-enforcement-first rule. Fixture format is the external
`skill-creator` plugin's `{query, should_trigger}` shape, already on disk at
`prod/skills/persona-debate/evals/trigger-eval.json`. Supersedes the umbrella item this
section replaces, now decomposed into tickets 1–4.

- [ ] [HARNESS] Add `scripts/ci/check_skill_triggers.py` scoring each skill's `evals/trigger-eval.json` by TF-IDF rank over all skill descriptions (positive = tie-free top-1, negative = not top-1), skipping script-class-mismatched and `"waived"` queries with counts reported, failing a fixture with zero scorable positives, plus `test_check_skill_triggers.py`, a `skill-triggers` job in `harness-check.yml`, and a `docs/eval-criteria.md` §1 *How to test* amendment pointing at the script as the mechanical tier

## Harness — cross-point every near-collision description pair

Blocked until ticket 1's ranker exists: τ cannot be pinned without the measured distribution,
and the pointer edits cannot be chosen without τ. Landing these edits *before* the Half B gate
is what lets ticket 3 merge green. Predicted finding: `harness-capture`'s description names
`harness-curate`, but `harness-curate`'s names `harness-init`, not `harness-capture`.

- [ ] [HARNESS] Measure the 13×13 description pair-similarity distribution with ticket 1's ranker, pin τ per the spec's two conditions, append the measured distribution and τ to `docs/design/skill-trigger-collision-check.md` as a *Measured calibration* section, then add the missing mutual name pointer to every description in a pair at or above τ and bump both `dev/` manifests *(blocked by: 1-half-a-ranker)*

## Harness — near-collision gate (Half B)

Ships green because ticket 2 already added every pointer τ demands. Failure message must name
both skills in the pair and state that the fix is a cross-pointer, not a suppression entry.

- [ ] [HARNESS] Extend `check_skill_triggers.py` with the pairwise cosine collision gate at the τ recorded by ticket 2, failing only a pair at or above τ where either description does not name the other, and record the calibration basis in the module docstring *(blocked by: 2-cross-pointers)*

## Harness — trigger fixture ratchet on touched SKILL.md

Independent of tickets 2–3; needs only ticket 1's script and job. Converts the 12 missing
fixtures into incremental, evidence-driven work instead of one bulk authoring sprint.

- [ ] [HARNESS] Fail `check_skill_triggers.py` when `git diff origin/main...HEAD` shows a changed `*/skills/*/SKILL.md` whose skill has no `evals/trigger-eval.json`, naming the skill, and add `fetch-depth: 0` to the `skill-triggers` job so the diff base is available *(blocked by: 1-half-a-ranker)*

## Harness — Codex review resilience against shared-broker teardown (Windows)

Source: session diagnosis 2026-08-11 of `Codex payload unparsed` during `task-review` on Windows.
Root cause is in the **openai-codex plugin**, not here: `broker-lifecycle.mjs:61` spawns the shared
broker with `detached: true`, which on Windows does not sever the parent-child link (observed:
broker pid 25780's parent is companion pid 22396), while every teardown path uses
`terminateProcessTree` → `taskkill /PID x /T /F` (`process.mjs:67`, win32 branch only; the POSIX
branch kills one process group). So killing any companion — `session-lifecycle-hook.mjs:65` at
SessionEnd, `/codex:cancel`, or Claude Code stopping a background Bash task — takes the shared
broker down with it, and every other client on that workspace loses its socket mid-turn. Recovery
does not exist: `app-server.mjs:300` rejects pending requests with a plain
`"connection closed."` carrying no `code`, and the direct-fallback condition at `codex.mjs:622`
only matches `BROKER_BUSY` / `ENOENT` / `ECONNREFUSED`, so a mid-turn close is never retried — the
companion dies with no JSON on stdout and `codex-review.sh` reports
`payload status: unparsed`. Compounding: the broker is single-flight per workspace
(`app-server-broker.mjs:174`), so two overlapping review cycles push the second onto a second
app-server, doubling the orphan surface. Observed wreckage before cleanup: two patis review jobs
stuck at `status: running`, three stale `broker.json` files, two orphaned `codex app-server` trees.

The upstream fixes (re-parent the broker outside `taskkill /T` reach on Windows; add mid-turn
socket close to the direct-retry condition) belong in an openai-codex issue, not this repo. These
tickets harden *our* launcher against the failure while it exists. The stale-state prune and the
per-workspace lock shipped in dev v4.4.11; the one ticket below is what remains. It touches `dev/`,
so it bumps both `dev/` manifests.

- [ ] [HARNESS] Treat an unparseable or empty companion payload in `codex-review.sh` as transient rather than terminal: retry the run once after pruning the workspace's `broker.json` so the retry spawns a fresh broker, emit a bounded `WARN` naming the retry, and keep the current diagnostics and exit 1 when the second attempt also fails

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
