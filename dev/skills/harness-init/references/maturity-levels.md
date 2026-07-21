# Harness Maturity Levels

Progressive adoption model. Start at Level 1, advance only when current level is stable.

**Key rule:** Each level builds on the previous. Don't skip. Level 3 enforcement without Level 2 verification creates false confidence.

---

## Level 1 — Basic (Agent-Readable Docs)

**Goal:** Any AI agent can understand the repo without asking questions.

**Required artifacts:**
- [ ] `AGENTS.md` — index ≤100 lines with Docs Index, Golden Principles, Delegation table
- [ ] `CLAUDE.md` → `@AGENTS.md` pointer
- [ ] `docs/` — at minimum: `architecture.md`, `conventions.md`, `runbook.md`
- [ ] `backlog.md` with correct schema

**Passes Level 1 when:** `scripts/validate-harness.sh` exits 0 for all Level 1 checks.

**Time to reach:** 15–45 min (with harness-init skill).

---

## Level 2 — Verified (Mechanically Consistent)

**Goal:** Docs stay accurate automatically. Harness is self-checking.

**Required additions beyond Level 1:**
- [ ] CI workflow runs `scripts/validate-harness.sh` on every PR
- [ ] All doc cross-references resolve (no broken `docs/` links)
- [ ] Delegation routing table triggers are objective and measurable (no subjective conditions)
- [ ] `docs/workflows.md` embeds delegation gates as named steps (not footnotes)
- [ ] Lint/test infrastructure exists and passes
- [ ] AGENTS.md size check active (via `scripts/check-context-size.sh` or `dev:harness-maintenance` SessionStart hook)
- [ ] Area-specific rules live outside AGENTS.md — in `docs/` (multi-tool repos) or `.claude/rules/*.md` with `paths:` (Claude-only repos) — see `references/path-scoped-rules.md` *(manual check — not enforced by `validate-harness.sh`)*

**Passes Level 2 when:** CI is green, `scripts/sweep.sh` reports zero drift.

**Time to reach:** 30 min – 2 hours (depends on CI setup complexity).

---

## Level 3 — Enforced (Self-Maintaining)

**Goal:** Violations are mechanically impossible, not just discouraged.

**Required additions beyond Level 2:**
- [ ] Branch protection: direct push to `main`/`master` requires PR + CI green
- [ ] Layer 0 settings-level deny for any destructive surface — `permissions.deny` / `sandbox.enabled` (model-independent; see `references/enforcement-template.md` → "Layer 0") *(manual check — not enforced by `validate-harness.sh`)*
- [ ] PostToolUse hooks catch golden principle violations at edit time (Layer 1 in enforcement chain)
- [ ] Pre-commit hooks block commits with unresolved violations (Layer 2)
- [ ] Drift detection on push — AGENTS.md checked for size and stale cross-references
- [ ] Scratchpad convention documented in `docs/runbook.md` (if multi-agent)
- [ ] Orchestrator skill exists (if multi-agent project)
- [ ] Harness evolution protocol in place: feedback → fix target → change history (see `references/harness-evolution.md`)

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

For new repos, target Level 1 in one session. Level 2 in the same session if CI is already set up. Level 3 as a follow-up when the team is ready.

---

## Upgrade Path

```
Level 1 → 2:  Add CI workflow + fix any broken doc references + make triggers objective
Level 2 → 3:  Add branch protection + PostToolUse hooks + drift detection
```

**Don't over-engineer Level 3 before it's needed.** A solo dev on a greenfield project often ships faster at Level 2. Promote to Level 3 when the cost of a slip exceeds the setup cost.
