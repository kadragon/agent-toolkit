# Harness Evolution — the loop contract

> Concept: Lilian Weng, "Harness Engineering for Self-Improvement"
> (https://lilianweng.github.io/posts/2026-07-04-harness/). This file is the
> **contract** every harness-editing loop follows — what may be edited, what
> acceptance requires, and how changes are recorded so a later run can falsify
> them. **Detection is not defined here**: which signals mean the harness needs
> evolving lives in `dev:harness-curate` → `references/signal-taxonomy.md`
> (Signals 1–8), the single detection authority. This file governs what happens
> *after* a signal is confirmed.

A harness is a living system, not a one-time setup. But a loop that edits its
own harness optimizes whatever signal it is given — so the contract bounds
three things: the editable surface, the acceptance bar, and the record.

## 1. Editable-surface manifest

| Tier | Surfaces | Rule |
|------|----------|------|
| **May edit** (on a confirmed signal, through the owning creator) | repo skills (`SKILL.md` + bundled scripts), repo agents (`.claude/agents/*.md`), repo hooks/settings (`.claude/settings.json` via `update-config`/`hookify`), `docs/*.md`, auto-memory | Route through the owning generator — never hand-edit what a creator owns (`skill-creator`, `plugin-dev:agent-creator`, `hookify`, `update-config`) |
| **Confirmation-gated** | repo `CLAUDE.md` / `AGENTS.md` (always-loaded maps) | Show the exact line before/after; apply only on explicit confirmation |
| **Read-only** | global `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md` (surface the line, user edits); the platform's base instructions (not editable at all); **the verifiers** — `validate-harness.sh`, the qa-verifier agent's acceptance bar, CI workflows, hook guards under test | A loop-originated edit must never touch the mechanism that evaluates it — reward hacking is the failure mode this tier exists to block. Loosening an over-firing guard is legitimate only when the *signal itself* is harness-friction (signal-taxonomy §5), routed and confirmed like any other change — never as a side effect of making another change's check pass |

## 2. Validation gate — acceptance is an objective check, not plausibility

Every proposed harness edit names its acceptance check **in the brief, before
the edit is made**. The check passing is the exit criterion; failing it means
revert, not retry-until-green.

| Edit route | Acceptance check |
|------------|------------------|
| Skill create / modify | `skill-creator` eval pass (it owns evals — do not build a parallel harness) |
| Skill triggering description | `skill-creator` description-optimizer train/test pass |
| Agent triggering description | `plugin-dev:agent-development` modify + re-run of the missed trigger case (the skill optimizer does not own agent definitions) |
| Hook / settings change | Trigger simulation: pipe a fixture event through the hook (`echo '{...}' \| bash hook.sh`) and assert the expected verdict |
| Agent create / modify | Re-run of the failing case (or a dry-run of the changed flow) succeeds |
| Docs / memory write | Record-only — no runtime behavior to test; the prediction field (below) is still required |

**No verifier available** → the edit may still land on user confirmation, but
its record is marked `unverified` and it is first in line at the next re-audit.
Disclose the limit; never present an unverified edit as a verified one.

## 3. Change record — every edit carries a falsifiable prediction

Record every harness change in the change-history table in
`docs/harness-log.md` (never CLAUDE.md — it stays a pure `@AGENTS.md`
pointer). **The record does not depend on an orchestrator existing**: if the
repo has no `docs/harness-log.md` yet, the first loop-originated edit creates
it — the table below plus one Docs Index row in AGENTS.md — regardless of
whether an orchestrator pointer block was ever registered there. The schema
pairs each edit with a prediction a later run can check:

```markdown
**Change History:**
| Date | Change | Scope | Reason | Predicted impact | Verified |
|------|--------|-------|--------|------------------|----------|
| 2026-05-03 | Add security-reviewer agent | agents/security-reviewer.md | Output missed auth issues | next security-touching PR review flags auth issues | pending |
| 2026-05-07 | Expand orchestrator description | skills/domain-orchestrator | "재실행" keyword not triggering | trigger-miss for "재실행" drops to 0 over next 5 sessions | 2026-06-01 — 0 misses in 6 sessions |
```

- **Predicted impact** — falsifiable and observation-scoped: what measurable
  behavior changes, over what window. "Improves quality" is not a prediction.
- **Verified** — `pending` until checked; then a date + one-line evidence, or
  `failed`. An edit that landed without a verifier is written `unverified`
  instead of `pending` (see §2) and gets checked the same way. An
  `Initial setup` row (from the orchestrator template) may carry `-` in both
  new columns — there is no edit to falsify at setup time.
- The re-audit consumer of this column is `dev:harness-curate` Step 2.5, which
  loads `pending`/`unverified` rows, stamps predictions that held, and surfaces
  `failed` ones as prune/rework candidates until resolved. It runs on
  `current`/`--project` scope only — `all` scope has no resolvable repo path,
  so pending rows are not re-audited there. Changes without
  a history entry are invisible to future sessions — this record IS the
  harness memory, and an unrecorded edit can never be falsified.

## 4. Protocol (per confirmed signal)

1. **Identify** — the confirmed signal, from `signal-taxonomy.md` (quote its
   evidence; verifier-grounded evidence per signal-taxonomy §8 when available).
2. **Diagnose** — read the failing definition to find the gap.
3. **Propose** — minimal change, within the §1 manifest, through the owning
   creator; the brief names the §2 acceptance check and the §3 prediction.
4. **Validate** — run the named check. Pass → land; fail → revert.
5. **Record** — append the §3 row, prediction included.

Changes to golden principles or enforcement layers are high risk — always
confirm with the user before applying, regardless of tier.

## Periodic audit

Portfolio health (unused assets, stale descriptions, instruction-layer
overlap, memory promotion) is `dev:harness-curate`'s job — run it rather than
re-deriving a checklist here. Its report plus this file's `Verified` column
together answer the two audit questions that matter: *is anything dead weight*
and *did past edits actually work*. Delete stale agents; shrink over-specified
skills. A lean harness beats a comprehensive one.
