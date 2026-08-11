# Evaluation Criteria

Evaluation is a separate role from implementation (Generator-Evaluator separation). The agent that implemented must not verify its own work.

## Skill Quality Criteria

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

- **Mechanical (necessary condition, merge-blocking):** `scripts/ci/check_skill_triggers.py` ranks each declared fixture query by TF-IDF cosine similarity over all skill descriptions and asserts `should_trigger: true` queries rank the owning skill 1st without a tie, and `should_trigger: false` queries do not. Queries whose script class (`ko`/`en`) mismatches the owning description, that carry a `waived` reason, or that have zero corpus-token overlap are skipped and only counted, not scored — the report's skip counts are what state the real coverage. It establishes only that the description carries tokens distinctive enough to win its own declared queries — passing does not certify the skill fires correctly in practice.
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

**How to test:** Run skill on known input; compare output to acceptance criteria.

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
