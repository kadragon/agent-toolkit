# Harness Maturity Levels

Progressive adoption model. Start at Level 1, advance only when current level is stable.

**Key rule:** Each level builds on the previous. Don't skip. Level 3 enforcement without Level 2 verification creates false confidence.

---

## Level 1 — Basic (Agent-Readable Docs)

**Goal:** Any AI agent can understand the repo without asking questions.

**Required artifacts:**
- [ ] `AGENTS.md` — index targeting ≤100 lines with Docs Index, working-code boundaries and Language Policy; concise edit guidance or a valid pointer
- [ ] `CLAUDE.md` → `@AGENTS.md` pointer
- [ ] `docs/runbook.md` — build/test/deploy commands and known failure modes

**Conditional artifacts** — generated only when the repo has the thing they document, and their absence is not a Level 1 miss:

| Artifact | Generate when |
|---|---|
| `docs/architecture.md` | the repo has real module boundaries to state |
| `docs/conventions.md` | rules exist that the linter does not already own |
| `docs/workflows.md` | the repo runs a defined work cycle worth writing down |
| `docs/eval-criteria.md` | the repo runs the Sprint Contract flow |
| `backlog.md` | the repo adopts the backlog/sprint flow |
| Golden Principles | real project invariants exist; no minimum count |
| Delegation guidance | configured Claude/Codex roles or an actual delegation workflow exist |
| Token Economy | useful project-specific guidance exists; optional |
| `docs/delegation.md` | roles/workflow need detail not already in an existing workflow doc |

Size warnings above 100 (strong above 200) do not fail a level; session checks warn only above
200. Broken references and malformed configuration remain failures.

**Passes Level 1 when:** `scripts/validate-harness.sh` exits 0 for all Level 1 checks.

**Time to reach:** 15–45 min (with harness-init skill).

---

## Level 2 — Verified (Mechanically Consistent)

**Goal:** Docs stay accurate automatically. Harness is self-checking.

**Required additions beyond Level 1:**
- [ ] CI workflow runs `scripts/validate-harness.sh` on every PR
- [ ] All doc cross-references resolve (no broken `docs/` links)
- [ ] Lint/test infrastructure exists and passes
- [ ] *(only if the repo has agent roles)* delegation routing triggers are objective and measurable, and `docs/workflows.md` embeds the gates as named steps
- [ ] AGENTS.md size check active (via `scripts/check-context-size.sh` or the `dev` plugin's SessionStart hook)
- [ ] Area-specific rules live outside AGENTS.md — in `docs/` (multi-tool repos) or `.claude/rules/*.md` with `paths:` (Claude-only repos) — see `path-scoped-rules.md` *(manual check — not enforced by `validate-harness.sh`)*

**Passes Level 2 when:** CI is green, `scripts/sweep.sh` reports zero drift.

**Time to reach:** 30 min – 2 hours (depends on CI setup complexity).

---

## Level 3 — Enforced (Self-Maintaining)

**Goal:** Violations are mechanically impossible, not just discouraged.

**Required additions beyond Level 2:**
- [ ] Branch protection: direct push to `main`/`master` requires PR + CI green
- [ ] Layer 0 settings-level deny for any destructive surface — `permissions.deny` / `sandbox.enabled` (model-independent; see `enforcement-template.md` → "Layer 0") *(manual check — not enforced by `validate-harness.sh`)*
- [ ] PostToolUse hooks catch golden principle violations at edit time (Layer 1 in enforcement chain)
- [ ] Pre-commit hooks block commits with unresolved violations (Layer 2)
- [ ] Drift detection on push — AGENTS.md checked for size and stale cross-references
- [ ] Scratchpad convention documented in `docs/runbook.md` (if multi-agent)
- [ ] Orchestrator skill exists (if multi-agent project)
- [ ] Harness edits route through `dev:harness-curate` with a named acceptance check per edit — never a hand edit of the verifiers (`validate-harness.sh`, CI, hook guards) to make a change pass

**CI / Hook Parity Principle:** Local git hooks must check only a *subset* of what CI validates. If hooks match CI exactly, contributors can bypass CI by disabling hooks. CI is authoritative; hooks are fast-feedback.

**Passes Level 3 when:** A new contributor can clone the repo and run `scripts/validate-harness.sh` with zero manual setup.

**Time to reach:** 1–4 hours.

---

## Assessing Current Level

Run `scripts/validate-harness.sh` against the target repo. Report format:

```
Level 1: PASS / FAIL (N missing items)
Level 2: PASS / FAIL (N missing items)
Level 3: PASS / FAIL (N missing items)

Next step: [specific action to advance one level]
```

**Target Level 1 for a new repo, and stop there.** Level 1 is the default init outcome, not a waypoint to rush past: an enforcement layer built before any violation has occurred is guarding against a guess. Advance when the repo produces the evidence — a rule that actually got broken, a doc that actually went stale — which usually means a later session, not this one. Level 2 in the same session is reasonable only when CI already exists and running the validator in it costs one file.

---

## Upgrade Path

```
Level 1 → 2:  Add CI workflow + fix any broken doc references + make triggers objective
Level 2 → 3:  Add branch protection + PostToolUse hooks + drift detection
```

**Don't over-engineer Level 3 before it's needed.** A solo dev on a greenfield project often ships faster at Level 2. Promote to Level 3 when the cost of a slip exceeds the setup cost.
