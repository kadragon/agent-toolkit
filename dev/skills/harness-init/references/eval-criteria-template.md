# Evaluation Criteria Template

Grading standards for work an evaluator checks. The evaluator is a **separate role** from the
generator: agents grading their own work lean lenient, and an independent evaluator is far more
tractable (Anthropic, generator–evaluator separation).

## Criteria

Choose 3–5 criteria that cover the project's real quality dimensions, weighted by importance.

```markdown
### {N}. {Criterion Name} (weight: {X}%)

{One sentence describing what this measures.}

| Score | Description |
|-------|-------------|
| 5 | {Excellent — specific} |
| 3 | {Acceptable — the minimum bar} |
| 1 | {Broken — specific} |

**How to test:** {concrete steps}
```

Pass: every criterion ≥ 3 and the weighted average ≥ 3.5. A failed Sprint Contract item fails the
work regardless of the average.

## Contract criteria by commit type

The Sprint Contract itself (fields, approval) is `dev:task-next` → `references/cycle.md` →
*Sprint Contract*. Two commit types need a specific agreed criterion, carried to the evaluator by
the contract's commit tag:

- **Bug fix** — one criterion names the test that fails before the fix and passes after. The
  repo's commit-convention doc owns the rule; this makes it gradable.
- **Refactor** — one criterion names the tests that hold the touched behavior, green before the
  first structural edit; with no such test, a characterization test written first. Type check and
  lint are not a pin (`cursor/plugins@9b93e81:pstack/skills/poteto-mode/playbooks/refactoring.md`
  step 1).

## Grading

List the pass/fail evidence per contract item before any score; grade each criterion on its own.
Where the evaluator's scores diverge from human judgment, tighten its prompt with the specific
miss and re-run.
