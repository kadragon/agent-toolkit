# Evaluation Criteria Template

Product-level evaluation criteria. The evaluator is a **separate role** from the generator — this separation is the single most impactful harness design decision (per Anthropic research).

Why separation matters: when asked to evaluate their own work, agents systematically lean toward leniency, praising mediocre output. An independent evaluator, while still inclined toward generosity, is far more tractable.

## Designing Criteria

Choose 3-5 criteria that cover the project's quality dimensions. Weight them by importance — don't distribute evenly.

### Template

```markdown
### {N}. {Criterion Name} (weight: {X}%)

{One sentence describing what this measures.}

| Score | Description |
|-------|-------------|
| 5 | {Excellent — specific description} |
| 4 | {Good — specific description} |
| 3 | {Acceptable — minimum bar} |
| 2 | {Poor — specific description} |
| 1 | {Broken — specific description} |

**How to test:** {Concrete steps to verify this criterion}
```

### Common Criteria by Project Type

**Web applications:**
- Functionality (40%) — Do features work end-to-end?
- UI/UX consistency (20%) — Does it match the design system?
- Performance (20%) — Page load, API response times
- Security (20%) — Auth, input validation, OWASP compliance

**APIs/Services:**
- Correctness (40%) — Do endpoints return expected data?
- Contract compliance (25%) — Does the API match its spec/schema?
- Error handling (20%) — Are errors meaningful and structured?
- Performance (15%) — Response times under load

**Libraries:**
- API design (30%) — Is the public API intuitive and consistent?
- Correctness (30%) — Do all functions work as documented?
- Documentation (20%) — Are examples and edge cases covered?
- Backward compatibility (20%) — Do existing users need to change code?

**Data pipelines:**
- Data quality (40%) — Are outputs correct and complete?
- Idempotency (20%) — Does rerunning produce the same result?
- Error recovery (20%) — Does it handle partial failures gracefully?
- Observability (20%) — Can you tell what happened from logs/metrics?

## Sprint Contract (Pre-Implementation Agreement)

Before each implementation cycle, the generator and evaluator negotiate a **sprint contract** — a concrete definition of "done" that both sides agree on before any code is written. This bridges the gap between user stories in `backlog.md` and testable implementation.

```markdown
### Sprint Contract: {Feature Name}

**Generator proposes:**
- I will build: {specific scope}
- Success looks like: {concrete, testable criteria}
- Out of scope: {explicit exclusions}

**Evaluator reviews and confirms:**
- These criteria are testable: yes/no
- Missing acceptance criteria: {list}
- Ambiguous items: {list}

**Agreed contract:**
- [ ] {Criterion 1 — specific and testable}
- [ ] {Criterion 2}
- [ ] {Criterion 3}
```

The contract matters because without it, the evaluator grades against vague expectations and the generator builds against vague goals. Both drift. A written contract gives the evaluator concrete criteria to test against and the generator a clear target.

For long-running builds where sprint decomposition isn't needed (model can sustain coherent work for hours), the contract still applies — just at the feature level rather than the sprint level.

## Calibration Examples

Include 2-3 calibration examples per criterion — one excellent (score 5) and one poor (score 2). These anchor the evaluator's judgment and reduce drift across evaluations.

Calibration examples should include **detailed score breakdowns** explaining exactly why each score was given. Vague calibration ("this is good") produces vague evaluation.

```markdown
### Example: Score 5 (Excellent)

{Specific, concrete example from the project showing what excellence looks like.}

**Why this scores 5:** {Detailed breakdown — what specific things make this excellent, not just "it works well."}

### Example: Score 2 (Poor)

{Specific, concrete example showing what poor quality looks like, with specific defects listed.}

**Why this scores 2:** {Detailed breakdown — which criteria failed and how, with evidence.}
```

## Pass Threshold

Set a pass threshold that's high enough to catch real problems but not so high that minor issues block progress:

- **All criteria >= 3** (no single dimension is broken)
- **Weighted average >= 3.5** (overall quality is acceptable)

## Evaluator Execution Protocol

1. Read the `Done-when` criteria from `backlog.md`.
2. Read `docs/eval-criteria.md` for grading standards.
3. Read relevant project docs for context.
4. Exercise the feature (via Playwright MCP, API calls, or code review).
5. Grade each criterion with specific evidence.
6. Below threshold → findings become new `backlog.md` items → fix → re-evaluate.
7. All pass → feature done.

The evaluator must be **skeptical by default** — actively look for what's broken, not what works. Grade against criteria, not vibes.

## Evaluator Self-Deception Pattern

The most common evaluator failure mode is not missing bugs — it's **finding bugs and then talking itself out of them**. The pattern looks like this:

> "The drag-and-drop doesn't work on the timeline... but the overall functionality is solid and this is a minor interaction issue, so I'll give it a 4."

This is the evaluator equivalent of the delegation bypass problem: the agent identifies the issue correctly, then applies subjective reasoning to downgrade its severity. Over multiple criteria this compounds into inflated scores.

### Countermeasures

1. **Grade each criterion independently.** Don't let strong performance on one criterion excuse weakness on another. The evaluator should not see its own previous scores while grading the next criterion.

2. **Evidence-first grading.** Require the evaluator to list specific findings (pass/fail per contract item) before assigning any score. The score must follow from the evidence, not precede it.

3. **Penalize specific anti-patterns.** If the project has known "AI slop" patterns (e.g., purple gradients over white cards, unused stub functions, placeholder text left in), list them explicitly and make them automatic score penalties.

4. **Hard thresholds on contract items.** If a sprint contract criterion fails, the feature fails — regardless of how well other things work. This prevents the evaluator from averaging away real problems.

## Evaluator Tuning Process

Calibrating an evaluator is iterative, not one-shot. The process:

1. **Run evaluation** on a completed feature.
2. **Read the evaluator's full log** — not just the final scores, but the reasoning trace.
3. **Compare to human judgment.** Where does the evaluator diverge? Is it too generous on certain criteria? Does it miss interaction-level bugs that require clicking through the UI?
4. **Update the evaluation prompt** based on divergences. Be specific: "You scored drag-and-drop as working when it only handles single clicks, not click-drag. Test drag interactions explicitly."
5. **Repeat** until the evaluator grades within acceptable range of human judgment.

This typically takes 3-5 rounds. The first evaluator prompt is almost always too generous — expect to tighten it.
