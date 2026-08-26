# Evaluation Criteria

Evaluation is a separate role from implementation (Generator-Evaluator separation). The agent that implemented must not verify its own work.

## Skill Quality Criteria

**Provenance of the weights.** 30/40/15/15 is an author's judgement call, set against this repo's
own assets and never validated on an outside sample. Say so wherever the split decides something,
and re-set it from observed misses rather than defending the numbers.

### 1. Trigger Accuracy (weight: 30%)

Does the skill fire when it should, and not fire when it shouldn't?

| Score | Description |
|-------|-------------|
| 5 | Directive phrasing + concrete, distinctive trigger phrases + explicit `NOT for …` exclusions that fence off neighbor skills |
| 4 | Directive phrasing + concrete triggers; minor gaps or a phrasing a user would plausibly use is missing |
| 3 | Descriptive phrasing; fires inconsistently |
| 2 | Description too vague; frequently missed |
| 1 | Never triggers automatically |

**How to test:** Two tiers, sharing one fixture (`{skill}/evals/trigger-eval.json`, `{query, should_trigger}`).

- **Mechanical (necessary condition, merge-blocking):** `scripts/ci/check_skill_triggers.py` ranks each declared fixture query by TF-IDF cosine similarity over all skill descriptions and asserts `should_trigger: true` queries rank the owning skill 1st without a tie, and `should_trigger: false` queries do not. Queries whose script class (`ko`/`en`) mismatches the owning description, that carry a `waived` reason, or that have zero corpus-token overlap are skipped and only counted, not scored — the report's skip counts are what state the real coverage. It establishes only that the description carries tokens distinctive enough to win its own declared queries — passing does not certify the skill fires correctly in practice. **Ratchet:** a branch that changes a skill's `SKILL.md` must leave that skill with an `evals/trigger-eval.json`, or the check fails naming the skill — fixture coverage grows with whoever is already reasoning about that skill's triggering.
- **Model-judged (sufficient condition, above the mechanical floor):** Auto-invocation is description-driven. Draft the representative prompts a user would type, confirm this skill is the unambiguous best match for each, and confirm the `NOT for …` cases exclude neighboring skills.

### 2. Correctness (weight: 40%)

Does the skill produce correct, complete output?

| Score | Description |
|-------|-------------|
| 5 | All outputs verifiable against acceptance criteria; no known failure modes |
| 4 | Correct on golden path; 1–2 known edge cases |
| 3 | Correct on common cases; notable gaps documented |
| 2 | Correct on simple cases only; fails on realistic inputs |
| 1 | Produces incorrect or incomplete output on basic inputs |

**How to test:** One run answers only half the question. Run all three passes:

- **Absolute** — run the skill on a known input; grade the output against the acceptance criteria.
- **With/without** — run the same input with the skill withheld. The delta is what the skill
  actually buys; output indistinguishable from the no-skill baseline scores 1 here however well it
  reads. It is the per-skill form of the ablation that *Harness Component Assessment* (below)
  runs one layer up, on harness components.
- **Variance** — repeat the with-skill run 3+ times on the same input and compare the **process**
  taken, not the prose produced. Spread across runs is the defect: a skill exists to make the agent
  take the same route every time (`docs/writing-for-agents.md`). Where the runs diverge names the
  step whose completion criterion is too loose.

Record the baseline, the run count, and the observed spread beside the score — a score without
them is an impression. The with/without and variance passes are adapted from
[revfactory/harness](https://github.com/revfactory/harness) `README_KO.md`, which reports a quality
delta and a variance reduction for its generated harnesses and labels both author self-measurement.

### 3. Shell Doc Compliance (weight: 15%)

Do all shell patterns in SKILL.md follow capture-before-use?

| Score | Description |
|-------|-------------|
| 5 | Every `$var` reference has visible `var=$(cmd)` capture in same block |
| 3 | Most patterns compliant; 1–2 violations |
| 1 | Multiple `$var` references without capture |

**How to test:** Grep SKILL.md for `\$[A-Z_]` references without preceding capture in same code block.

### 4. Context Economy (weight: 15%)

Does the skill protect context window (progressive disclosure, delegate bulk)?

| Score | Description |
|-------|-------------|
| 5 | References detailed docs by path; no inline doc dumps; delegates analysis >20 lines |
| 3 | Minor verbosity; core guidance concise |
| 1 | Large inline reference dumps; would crowd actual work context |

## Sprint Contract (Pre-Implementation Agreement)

Before any implementation cycle, agree on "done":

```markdown
### Sprint Contract: {feature/fix name}

**Tag:** {[FEAT] | [REFACTOR] | [FIX] | [TEST] | [CONSTRAINT] | [DOCS] | [HARNESS] | [PLAN]}
**Scope:** {specific files or skills to modify}
**Acceptance criteria:**
- [ ] {criterion 1 — concrete and testable}
- [ ] {criterion 2}
**Out of scope:** {explicit exclusions}
**Lint/test command:** {command to run to verify}
```

Both generator and verifier must agree before coding starts. Evaluator grades against this contract, not vague impressions.

**Standing checks are inherited, not restated.** Every contract inherits the floor in
`.claude/agents/qa-verifier.md` → `## Checks (always run)`. Do not copy those gates into acceptance
criteria — criteria state what is specific to *this* change, and a second copy of the floor drifts
from the first.

**`[FIX]` requires a reproduction criterion.** When the tag is `[FIX]`, acceptance criteria must
include one naming the test that fails before the fix and passes after — that is what makes the
reproduction gradable rather than asserted. The **Tag** field is what carries this to the verifier:
without it a `[FIX]` contract that silently omits the criterion is indistinguishable from a
well-formed non-`[FIX]` one, and the omission is exactly what needs detecting. `docs/conventions.md` (the `[FIX]` row of the
commit-type table) is the owning rule.

## Harness Component Assessment

Quarterly: for each harness component, assess whether it still compensates for a real model limitation.

| Component | Assumption | Still load-bearing? |
|-----------|-----------|---------------------|
| Trigger router | Descriptions fire ~50% without help | Test: remove router, check fire rate |
| Version-bump CI | Agents forget to bump version | Test: omit bump intentionally, see if CI catches it |
| Capture-before-use rule | Agents reference unset vars | Test: omit pattern in docs, observe agent output |
| Generator-Evaluator separation | Self-eval is lenient | Likely still true across model generations |
