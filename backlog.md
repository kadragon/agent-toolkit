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

## Invocation axis — contract doc

Source: `docs/design/invocation-axis.md`. Tickets 1–7 below are that spec, sliced in dependency
order. Every ticket touching `dev/` bumps both `plugin.json` files per Golden Principle 1; the
series lands dev at `4.5.0` or above.

- [ ] [DOCS] Write `docs/invocation.md` — axis definition, per-platform fields, the user-invoked→user-invoked ban, the `Call the Skill tool with "ns:name"` notation standard, and the router-prose exemption rule. Index it from the AGENTS.md Docs Index and add a pointer from `docs/platform-specs.md` (which keeps the raw field syntax, not the policy).

## Invocation axis — split `task-review`

- [ ] [REFACTOR] Move the full review workflow (Arguments, Prerequisites, Setup, Steps 0–6, Error Handling, Scripts Reference) and the `scripts/` directory into a new model-invoked `dev/skills/task-review-cycle/`; leave `task-review` as the user-invoked entry point that parses flags and calls the Skill tool with `dev:task-review-cycle`. Keep the `task-review` name — renaming it would force a major bump. *(blocked by: 1-invocation-contract)*

## Invocation axis — call notation migration

- [ ] [REFACTOR] Rewrite the 22 `Skill(ns:name)` sites across `dev/skills/**` and `prod/skills/**` to `Call the Skill tool with "ns:name"`, splitting any two-skill step into two explicit calls, and repoint the four `task-review` callers (`task-new` ×2, `task-next` SKILL.md, `references/batch.md`, `references/tree.md`) at `dev:task-review-cycle`. Leave `docs/design/*.md` and the router-prose sites untouched. *(blocked by: 2-task-review-split)*

## Invocation axis — Claude frontmatter fields

- [ ] [FEAT] Add `disable-model-invocation: true` to the six user-invoked skills (`task-new`, `task-next`, `task-review`, `harness-init`, `harness-curate`, `repo-dependabot`); leave the model-invoked five unmarked. *(blocked by: 3-skill-call-notation)*

## Invocation axis — Codex sidecars

- [ ] [FEAT] Create `agents/openai.yaml` beside each of the six user-invoked skills carrying `policy.allow_implicit_invocation: false` plus the Codex UI metadata. This is a new file type for this repo — no sidecar exists today — so confirm the path Codex actually reads before landing. *(blocked by: 4-claude-axis-fields)*

## Invocation axis — user-invoked descriptions

- [ ] [DOCS] Rewrite the six user-invoked `description` fields as human-facing one-liners for the slash-command list, stripping trigger lists and `NOT for … →` disambiguation arrows. Model-invoked descriptions keep their trigger phrasing. Confirm `scripts/ci/check_skill_triggers.py` still passes on the shortened text. *(blocked by: 5-codex-sidecars)*

## Invocation axis — CI enforcement

- [ ] [FEAT] Extend `scripts/ci/check_skill_frontmatter.py` and its test with three checks: axis coherence (Claude field ↔ Codex sidecar agree), call graph (fail on a user-invoked skill calling another user-invoked skill), and notation (fail on residual `Skill(ns:name)` in operative skill prose). Router-prose exemptions carry an explicit marker per `docs/conventions.md` → *Adjudicated Exceptions Need a Marker*, not a silent path allowlist. Verify the checks exit non-zero on the pre-migration tree. *(blocked by: 6-user-invoked-descriptions)*
