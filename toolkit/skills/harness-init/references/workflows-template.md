# Workflows Template

Six workflows. Pick the primary one per cycle. Minor side-effects are allowed (see bottom).

Adapt these to the project — not all projects need all six. A small library might only use `code` and `draft`. A large system might use all six.

## `plan` — Spec Generation

Expand a short prompt into a full product spec.

1. Expand into `docs/design/{feature}.md`: user stories, high-level tech design, phased feature list. **No granular implementation details** — errors cascade downstream.
2. Review with user. Don't proceed until approved.
3. Generate `backlog.md` items from approved spec.

Skip for trivial features.

## `code` — Implementation

The primary cycle for behavioral changes. Delegation checkpoints are **named steps** in this workflow — they are not optional "consult if needed" references.

**Step 0: Branch**
Before any edit, ensure you're on a feature branch — never on `main`/`master`. If currently on the default branch, run `git checkout -b <type>/<slug>` (e.g. `feat/user-auth`, `fix/login-redirect`). Exceptions must be declared explicitly in this repo's `AGENTS.md` / `CLAUDE.md`.

**Step 1: Scope check (delegation gate)**
Check objective delegation triggers from `docs/delegation.md`:
- Does the target module exceed the file/LOC threshold? → Delegate to Analysis agent before proceeding.
- Does the change touch ≥3 directories? → Delegate to Architecture analysis agent.
- Is this the first edit in this directory this session? → Delegate to Explore agent.
- Does the file match a critical path pattern? → Delegate to Analysis agent.
If none of the triggers match, proceed directly.

**Step 1.5: File Ownership Declaration (multi-agent only)**
If the sprint will spawn ≥2 parallel subagents OR use Agent Teams, the lead MUST declare file-ownership globs per role in `tasks.md` BEFORE spawning anyone. Overlapping globs cause silent overwrites. Cross-boundary edits require explicit lead approval — teammates do not cross globs unilaterally.

```markdown
## File Ownership
- implementer-A: `src/api/users/**`, `tests/api/users/**`
- implementer-B: `src/web/users/**`, `tests/web/users/**`
- qa-verifier:   read-only (any path), writes only to `docs/eval/**`
```

Skip this step for single-agent work.

**Step 2: Sprint Contract (negotiation with evaluator)**
Before writing code, define what "done" looks like in concrete, testable terms. If the project uses a separate evaluator agent, the generator proposes scope and the evaluator confirms the criteria are testable. If no separate evaluator, write the contract yourself — the discipline of writing testable criteria before coding is what matters.

See `docs/eval-criteria.md` → "Sprint Contract" for the template.

Adapt testing approach to the project:
- **Projects with test frameworks:** Red → Green → Refactor (TDD cycle)
- **Projects without tests:** Reference implementation → Implement → Lint/verify → Manual check
- **Legacy systems:** Read existing patterns → Implement following patterns → Cross-verify consistency

**Step 3: Implement**
For changes spanning ≤2 files, the orchestrator may implement directly. For larger changes, delegate to Implementation agent with spec + conventions + reference files.

**Step 4: Post-implementation QA (mandatory delegation)**
Always delegate to QA/verification agent. The agent that implemented must NOT verify its own work. No exceptions. The evaluator grades against the sprint contract criteria, not vague impressions.

**Step 5: Feature-complete evaluation (mandatory delegation)**
When the feature is done, delegate to Product evaluator with done-when criteria and `docs/eval-criteria.md`. Generator-Evaluator separation is non-negotiable.

**`backlog.md` format:**

```markdown
## Feature Name
> Goal: what and why.
> Design: docs/design/{feature}.md
> Done-when: (concrete acceptance criteria — agreed BEFORE coding)

- [ ] Simplest case
- [ ] Next case builds on previous
```

## `draft` — Documentation

Write or update `docs/`. Ground every claim in current code. Never modify production code. If the doc reveals a missing constraint, add to `backlog.md` or `tasks.md`.

## `constrain` — Architectural Enforcement

1. Write structural test or lint rule first.
2. Run it.
3. If current code violates → add remediation to `backlog.md`, don't fix here.
4. Update `docs/architecture.md`.

## `sweep` — Garbage Collection

Fight entropy. Run between features or on a schedule.

- Run automated sweep script (`tools/sweep.sh` or equivalent)
- List findings in `tasks.md` tagged as `[doc]`, `[constraint]`, `[debt]`, or `[harness]`
- Fix trivials inline
- Leave complex items for later
- Include harness simplification: "Is this component still compensating for a real model limitation?"

## `explore` — Research

State the question → research/prototype → report options and tradeoffs → **do not commit**. If approved, flows into `plan` or `code`.

## `debate` — Competing Hypotheses (optional, on-demand)

Adversarial multi-agent root-cause investigation. Use ONLY when a first-pass single-agent diagnosis failed on a high-stakes bug. Requires Agent Teams. Full procedure in `references/competing-hypotheses-playbook.md`.

Not a default workflow. Most projects invoke it <1×/month.

---

## Permitted Side-Effects

While in a primary workflow, these side-effects are allowed without switching:

| Primary workflow | Permitted side-effect |
|------------------|-----------------------|
| `code` | Add `[doc]` or `[constraint]` item to `tasks.md` when discovering issues |
| `code` | Update relevant docs after implementation |
| `draft` | Add `backlog.md` item when doc reveals missing behavior |
| `sweep` | Fix trivial `[doc]` items inline |

**Not permitted:** Writing production code during `draft` or `sweep`.

---

## Context Anxiety

Models lose coherence on lengthy tasks as context fills. Some exhibit **context anxiety** — prematurely wrapping up work, cutting corners, or declaring features "done" as they approach perceived context limits. Symptoms:

- Implementing the first 3 of 8 features fully, then stub-implementing the rest
- Suddenly summarizing remaining work instead of doing it
- Dropping quality noticeably in later parts of a long session

### Countermeasures

1. **Context resets over compaction.** When context fills during large tasks, prefer a full reset with a structured handoff file over in-place compaction. A reset provides a clean slate; compaction preserves continuity but doesn't resolve the anxiety behavior.

2. **Handoff files for multi-session work.** Write `handoff-{feature}.md` at the **start** of multi-session work (when context is fresh and the plan is clear), not when context is already degraded. Delete when the feature is complete.

3. **Sprint decomposition for weaker models.** If the model can't sustain coherent work for >1 hour, decompose into sprints (one feature at a time) with QA gates between them. Stronger models that maintain quality over longer sessions can work in continuous mode.

4. **Monitor for the pattern.** If later features in a backlog consistently have lower quality than earlier ones, that's context anxiety — add more reset points.

## Continuous Session vs Sprint-Based

This is a model-capability-dependent design choice, not a universal rule.

| Approach | When to use | Trade-off |
|----------|-------------|-----------|
| **Sprint-based** | Model loses coherence after ~30-60min; complex multi-feature builds | More overhead (contract negotiation, handoffs), but sustained quality |
| **Continuous** | Model sustains quality for hours; single-feature work | Less overhead, but risks degradation on very long tasks |

**The simplification principle applies:** start with the simplest approach (continuous session) and only add sprint decomposition if quality degrades. Each harness component encodes an assumption about model limitations — when the model improves, strip what's no longer load-bearing.
