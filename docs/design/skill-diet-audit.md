# Skill Diet Audit — over-engineering and over-instruction for Claude 5

**Status:** analysis + queued work (`[PLAN]`)
**Date:** 2026-10-28
**Method:** four read-only Opus subagents, one per skill family, graded against
`docs/writing-for-agents.md` → *Pruning* (no-op test is model-relative), the
`docs/design/harness-altitude-audit.md` → *Cut* list, and `backlog.md` → *Rejected*.
Headline claims below were re-verified by the orchestrator (`git show`, `wc`, `grep`, `ls`)
before being written down. Line estimates are the agents'; treat them as ±30%.

## Problem Statement

Twenty-one skills accumulated ~500 commits of incremental fixes since 2026-03. The
2026-09-04 diet (one Claude reviewer, size-routed lite path, 250-line SKILL.md cap) and the
2026-10-09 policy alignment trimmed SKILL.md bodies but never pruned `references/`. The
result is three distinct kinds of waste:

1. **Duplication that has already produced false statements.** The same rule is restated in
   up to eight files, and the copies have drifted. `maintenance.md` claims "The C script
   removes a `done` item from `backlog.md` mechanically", which `reconcile-harness.py` never
   does. `docs/workflows.md` points at a Sprint Contract template in `docs/eval-criteria.md`
   that lacks the three Git fields `cycle_state.py authorize` parses.
2. **Self-negating or stale material still shipped.** Sections that say of themselves "Not
   for long-context models" (`power-user-settings.md`), a *Context Anxiety* framing the repo's
   own reference calls model-dependent, ~110 lines of Agent Teams gates though
   `docs/delegation.md` says "There is no Agent Team route", and 18 references to hwpx scripts
   that no longer exist (`unpack.py`, `locate.py`, `next_id.py`, `calc_col_widths.py`).
3. **Prose that restates a script, `--help`, or the model's default.** About a third of
   task-review-cycle's reference prose describes what a script already prints; hwpx's
   `scripts-guide.md` echoes `--help` for ~40 lines and `compare.py` internals for ~50;
   task-debug spends ~60 of 214 lines on method a Claude 5 model applies unprompted
   ("Be aggressive, be creative, refuse to give up").

What is **not** over-built: the skill *count* and the chain shapes. task-grill / spec /
tickets are used (17 / 4 / 5 sessions in 1,141 transcripts) and their split is right;
curate / capture / reference-review read different inputs; repo-architecture and
repo-dependabot are judgment plus recorded gotchas on top of scripts; the OWPML references
in hwpx and the manual checklist in kr-style are load-bearing domain knowledge the script
cannot replace (`kr_audit.py` says so itself).

## Solution

Remove, do not restructure. Every item below is a deletion or a collapse to one owner; no
new gate, telemetry, or rationale prose. Ordered by tokens saved × confidence, grouped by
family so each group is one Sprint Contract.

### Per-family verdict

| Family | Files audited | Verdict | Est. removable lines |
|---|---|---|---:|
| harness-init refs | 30 refs, 2,980 lines | heavy | ~1,300 |
| task-review-cycle + task-next + workflows.md | 250 + 388 + 573 + 114 | heavy | ~230 |
| hwpx | 250 + 1,716 | heavy | ~235 |
| task-debug / task-tickets / test-prune | 214 / 134 / 207 | heavy / heavy / trim | ~130 |
| persona-debate, repo-quiz | 62+184, 250+128 | trim | ~130 |
| task-grill, task-spec, gongmun, report-draft, kr-style, capture, curate | — | lean/trim | ~120 |
| task-new, reference-review, repo-architecture, repo-dependabot, agents | — | lean | ~40 |

### Two decisions (resolved 2026-10-28)

- **D1 — Review panel default: keep #277.** PR #277 (57178ae, 2026-09-21) made the agy +
  Codex panel run by default on every non-lite route, reversing the diet's "panel only under
  `--panel`". The user kept #277 as current policy; the stale memory is corrected. The 7
  copies of the on/off rule still collapse into `risk-routing.md`; `review-sources.md` and
  `late-source-reclaim.md` stay.
- **D2 — harness-init Step 7b "Make delegation non-optional": cut to one line, drop the
  grep.** It instructed downstream descriptions to say "ALWAYS invoke … do NOT
  inline-execute", and `validate-harness.sh` §0 greps for that wording. It conflicts with
  `docs/delegation.md` "Eligibility never mandates a spawn" and no `dev/skills` description
  follows it since #234. Step 7b becomes one line (state the trigger condition in the
  description) and the §0 grep is removed.

## User Stories

- As the maintainer, I want each rule to live in exactly one file so a behavior change is a
  one-place edit and copies cannot drift into false claims.
- As a Claude 5 agent loading a skill, I want only text that changes my behavior versus my
  default, so the 250-line cap buys instructions, not exposition.
- As a downstream repo, I want harness-init to ship contract and recorded gotchas, not
  generic engineering advice or sections that disclaim themselves.

## Implementation Decisions

Each slice is one Sprint Contract. Evidence anchors are quoted phrases, not line numbers.

### Slice 1 — harness-init references (~1,300 lines)

- `enforcement-template.md` (710) → keep Layer 0, the layer ladder, *Hook Signaling*
  (~120). Delete *Agent Teams Quality Gates*, *Read Deduplication*, *Bash Output Truncation*,
  *Circuit Breaker*, *Consent Gates*, Layer 2–4 boilerplate, the stale "Mandatory, blocking"
  and the *Choosing Layers* table that contradicts Step 7 "Layer 0 only".
- Delete self-negating material: `handoff-template.md` (uncited by harness-init; only
  `docs/workflows.md` points at it), `workflows-template.md` → *Context Anxiety*,
  *Continuous vs Sprint*, Step 1.5 "OR use Agent Teams"; `power-user-settings.md` except
  *Auto-memory*. Fix every `→ Context Anxiety` pointer in the same change or
  `check_harness_drift.py` fails.
- One owner each: prune-backlog ownership rule (8 copies → `harness-invariants.md`
  *Reconciliation Contract*), AGENTS.md size band (8 copies → `validate-harness.sh` §2 plus
  one sentence in SKILL Step 3), precedence hedge (~6 copies → Step 0b), 4-rule edit filter
  (→ `harness-invariants.md`). Fix the false `maintenance.md` D-2 claim.
- Collapse generic catalogs: `eval-criteria-template.md` to skeleton + bug-fix reproduction
  + refactor pin (~50 of 163); `conventions-template.md` to skeleton + commit-type table
  (~40 of 138); `architecture-template.md` drop "Concrete Example: Next.js SaaS App".
- Template drift: `tasks-template.md` uses `evaluating` (no task-* skill does) while
  task-next writes `status: open` (reconcile reports unknown); `backlog-template.md` `[>]`
  bundle-sprint text describes a retired flow. Align to what `cycle.md` and
  `task_nodes.py` actually write.
- `validate-harness.sh` §11 header "Step 4b template resync" and "Multi-pass Rule / Team
  Communication Protocol" refer to a role template deleted in 318a165 → reword.
- SKILL.md (~35): drop Step 9's prose restatement of the validator, fold Steps 4c/5/6 into
  Step 10, D2 above.

### Slice 2 — task-review-cycle, task-next, workflows.md (~230 lines)

- `ci-failure-handling.md` → *Merge and Clean Up* is a verbatim copy of SKILL Step 6 → pointer.
  Drop "Common mistake: `merge-and-cleanup.sh 9 squash`" (script rejects it), "The script
  selects the best merge strategy" (~90 words internals), and the no-ops "Run tests locally
  to confirm the fix works", "Determine the commit message yourself", "No subagent is needed
  for one file".
- `late-source-reclaim.md`, `review-sources.md`, `risk-routing.md`: drop maintainer/evidence
  prose ("It is the evidence for any future argument about how much runway", "timings.log
  puts every measured run at 43–228s", "PR #263 is the recorded case", "The Claude slot
  itself is not here"), the `.meta` field list, and the 4th copy of lite self-grading.
- SKILL.md: preflight boilerplate 3× → `<from Setup>` placeholder (~20); drop Forgejo/gh
  paragraph (preflight `errors[]` owns it); "`--prefer-staged` commits a non-empty index"
  → two actions only; permission-row explanation → rule only. **Keep** Step 6 "no `bash`
  prefix, no variable" (#365) and Step 4 "everything before the last step changes the tree".
- task-next: destructive-git guard 4× and "never finish silently" 5× → one copy in
  `cycle.md`; "The Bash tool is stateless — CWD resets each call" 3× → one sentence (#104,
  older model); drop rationale "the `Agent` tool has no timeout", "The user should not have
  to ask what the blockers are".
- Hand-off rule 6 copies, "`--from`/`--auto` grant no authority" 5 copies → owner is
  `git-authorization.md` / `cycle.md` → *Hand off*; others become one-line pointers.
  Drop the task-review wrapper's authority paragraph (the callee's *Caller gate* repeats it).
- `docs/workflows.md`: delete *Context Anxiety*; repoint the Sprint Contract template to
  `cycle.md`; collapse `code` Steps 0–6 to pointers (Step 0's `git checkout -b` drifts from
  `task_nodes.py branch`).
- D1 above (keep #277): collapse the 7 on/off copies into `risk-routing.md`.
- Drift fixes found alongside: `qa-verifier.md` check 1 "Required iff any changed path is
  under `dev/`" omits `mods/` (Golden Principle 1); `implementer.md` "Escalate … ≥3 skill
  directories" conflicts with its own "3+ independent units" trigger; `explorer.md` trigger
  "10+ files" vs budget "≤10 tool calls … partial report".

### Slice 3 — hwpx (~235 lines)

- SKILL.md: delete pointer-only or duplicate Rules 7, 10, 11, 12, 13, 20, 23 and the
  restore-pointer table row; collapse WF1 lineseg note (re-explains Rule 19), Rule 24 CLI
  detail (`table.py replace --help` has it), WF4 "Validation items" (`validate.py` output
  has it) to one line each; keep the `[[ -d ]] || exit` guard once, not 11×; drop WF3
  "Skill does not auto-execute on invoke"; resolve the `.hwpx_work/` vs `mktemp -d
  .hwpx_work_XXXXXX` vs `mkdir -p .hwpx_work` three-way conflict to one convention.
- Fix 18 dead script names in SKILL.md, `xml-integrity.md`, `editing-gotchas.md`,
  `section-writing.md` (current: `office.py unpack|pack`, `table.py locate|replace|
  calc-widths`, `text.py patch`, `build.py next-id`). Extend `check_harness_drift.py` to
  match bare `*.py` names only if it stays a one-line regex change.
- `hwpx-format.md`: delete "Deprecated — Do NOT use python-hwpx API directly" and *Low-level
  XML access* (~40; no script imports it) plus Rule 9 and the intro clause.
- `scripts-guide.md`: cut compare.py internals (~50; `compare.py` and
  `docs/design/hwpx-content-compare.md` own them) and plain `--help` echoes (~40); keep
  gotcha examples (`--para 0 0 ""` resets charPr, mktemp BSD suffix, strip-lineseg needs
  `--inplace`).
- lineseg / 빈 문서 explanation 28 mentions across 6 files → full text once at Rule 19 /
  gotchas §12, imperatives elsewhere. `reference-restore.md` *Analysis output items* and
  *Core principles* (restore criteria 4×) → keep the ratio/spacing-drift bullet only.

### Slice 4 — task-debug, task-tickets, test-prune, Sprint Contract (~130 lines)

- task-debug (0 references, 0 invocations since 2026-08-24, every block traces to the
  mattpocock/pstack import, none to a recorded failure): keep the ~35 lines of repo contract
  and ~35 lines of stop rules ("No red-capable command, no Phase 2", "Two failed fixes → test
  the premise", `[DEBUG-a4f2]` tag, revert refuted changes); cut the 9-item repro catalog to
  one line, "Be aggressive, be creative, refuse to give up", "A 30-second flaky loop is
  barely better than none", the rationale tails ("is a vibe", "Minimising is not tidying",
  "one breakpoint beats ten log lines"), and the phase restatements. Target ~150 lines.
  Flag for `harness-curate` retirement review if still unused in 2026-12.
- Sprint Contract single source: three disagreeing templates (`docs/eval-criteria.md` no
  Git fields; `cycle.md` has the fields `cycle_state.py` parses; harness-init
  `eval-criteria-template.md` "Generator proposes / Evaluator reviews"). `cycle.md` becomes
  the only field list; `eval-criteria.md`, task-grill, task-tickets, task-spec repoint.
  `[FIX]` and `[REFACTOR]` rules each 4× → `cycle.md` + `conventions.md` only.
- Skill-slots carry "Carry all seven slots verbatim" in 8 files, never used in any design
  doc or backlog entry → `skill-extraction.md` owns it; one-line carry elsewhere.
- task-tickets: "Deliberately does not build a Wayfinder-style" 3× → Boundaries only;
  delete "Version-bump note for the sequence" (Golden Principle 1 owns it); "Wide mechanical
  refactors" ~22 → ~6 (stage names + no integration-branch + rename = one ticket); Step 1
  commit paragraph → "never commit here"; keep "Never write a number without its slug" (#232).
- test-prune: SKILL.md ↔ `mutation-proof.md` duplicates (sampling "about 4%, minimum 3",
  "Calibrate…", green baseline 3×, timeout 2×) → reference owns; drop Step 6.4 "a reviewer
  that took no part checks" (task-review is the single reviewer); vitest/jest/pytest runner
  rows repeat `--help`, keep the go row.

### Slice 5 — persona-debate, repo-quiz, prod drafts, harness-capture, task-grill/spec (~250 lines)

- persona-debate `debate-method.md` (always loaded via "Read it before running") → why +
  output template only; drop *Token economy* (4/5 bullets repeat SKILL), duplicated *Round
  structure* and *Persona agent* text; "Never opus" 3× → one (script enforces). Keep the
  haiku-refusal finding "Do NOT tell the agent to ignore inherited instructions" in SKILL only.
- repo-quiz `state-reference.md` *Gamification* and *Commands* restate `quiz_state.py`
  (~23); grounding rule 3× → step 2; *Language* 15 → 3 lines; explanation prose → keep the
  "Broader context:" label only.
- kr-style loop written out in full in kr-style, gongmun Step 4, report-draft G2 → one
  `Skill(prod:kr-style)` line + each caller's ending rule; drop dead `$LINT` block in
  `hwpx-recipes.md` §1; report-draft Step 1.5 duplicates `style-rules.md` §4; "Call the
  Skill tool with prod:hwpx" 6× → 1 per file.
- harness-capture: agent-toolkit-specific text in a shipped skill ("This repo has families
  — the `task-*` cycle skills") → remove; `routing.md` → attribution + two unique
  sentences (~30). harness-curate: thresholds table 3rd copy, *Classify before routing*
  2nd copy, grill→skill-creator handoff 2nd copy → one owner each.
- task-grill: "If the answer is discoverable by reading a file" 3× → Rule 3; rationale
  tails; description "Callable from other skills via `Skill(dev:task-grill)`" is a no-op but
  needs a `check_skill_triggers.py` run before changing. task-spec: mkdir block, "Do not
  skip user review" 3×, "call dev:task-grill first" 3× → one each.
- Agents: `skill-evaluator.md` "Opus reasoning pays off here" and the third read-only
  statement → delete; `qa-verifier.md` "Catches: …" duplicates *Checks*.

### Bugs found while auditing (not diet; file separately or fix in-slice)

- `prod/skills/kr-style/scripts/kr_audit.py` P1 regex `되어[지졌진]` misses its own documented
  example `분석되어집니다` and exits 0.
- `prod/skills/report-draft/scripts/lint_report.py` raises ImportError without defusedxml
  even for text-only `--gongmun`; not listed as a dependency.
- `docs/architecture.md` "harness-init/references/ is internal … do not reference from
  other skills" is violated by task-grill, qa-verifier, `backlog_candidates.py`,
  security-overview → update the rule, not the four consumers.

## Testing Decisions

- Every slice: `bash dev/skills/harness-init/scripts/validate-harness.sh`,
  `python3 scripts/ci/check_harness_drift.py`, `python3 scripts/ci/check_skill_triggers.py`, and
  the `harness-check.yml` steps for any touched `test_*.py`. Line counts are reported in the
  PR body per file (before → after); a slice that removes fewer than 60% of its estimate
  explains why in the PR.
- Slice 3 adds one assertion to `check_harness_drift.py` (or its test) that a bare script
  name mentioned in `prod/skills/hwpx/**/*.md` exists under `scripts/`, if that is a
  one-regex change; otherwise it stays a manual `ls` check noted in the PR.
- Slice 4 proves the Sprint Contract single source by running `cycle_state.py save` on the
  `cycle.md` template verbatim and on a repointed-skill output.
- No A/B on model behavior is run; the claim is token load and single-ownership, not accuracy.

## Out of Scope

- Anything in `harness-altitude-audit.md` → *Cut* or `backlog.md` → *Rejected*.
- Merging task-spec into task-tickets or any skill rename (major bump; usage data does not
  justify it).
- Removing `evals/security-effort` (42 files) from task-review-cycle — zero context cost; a
  later move to a repo-root eval dir is cosmetic.
- Retiring task-debug now — zero use for two months is evidence for a `harness-curate`
  review, not a cut.
- `mods/` — not audited.

## Further Notes

- Both authority sources for the diet remain: memory `feedback_lean_harness.md` (2026-09-04)
  and `docs/design/harness-policy-alignment.md`. D1 was the only place they were known to
  contradict current `main`; the memory now records #277 as policy.
- Raw per-family reports (agents' full findings with every quoted anchor) were kept in the
  session scratchpad only; this doc is the durable record.
