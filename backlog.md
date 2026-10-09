# Backlog

## 2. P0 — review-authorization-boundary

Source: `docs/design/harness-policy-alignment.md` → Implementation Decisions, slice 2. Read the design's authorization cases before changing caller gates or Git actions.

- [ ] [HARNESS] Expose task-new/task-next Git effects in Claude descriptions and Codex sidecars; carry the existing contract's approval source and Git limits through review/batch/tree/resume; enforce those limits before local commits, push/PR writes, and lite/hub merge without repeating valid approvals or treating --from/--auto as authorization. Read `docs/design/harness-policy-alignment.md`, slice 2, before forming the contract.

Acceptance: explicit Markdown approval-source/action/limit fields persist in the existing contract archive without a new schema; router/flag claims establish no authority; implementation-only blocks local commits; unknown authority denies affected actions; lite checks direct base-branch merge/push permission before entry; hub/batch/tree/resume preserve limits and authorized automation. Approach: enumerate affected entry/handoff paths and focused action-boundary tests before edits; broader state/execution redesign requires a separate ticket.

## 3. P1 — harness-init-simplification

Source: `docs/design/harness-policy-alignment.md` → Implementation Decisions, slice 3. Read the conditional-section and size-policy decisions before editing templates or validation.

- [ ] [HARNESS] Simplify harness-init templates and validation: remove the >20-output-lines delegation rule, condition optional sections on real invariants/delegation needs, reduce mandatory generic/verbatim blocks, and align size purposes, thresholds, messages, and tests while retaining useful defect detection. Read `docs/design/harness-policy-alignment.md`, slice 3, before forming the contract. *(blocked by: 2-review-authorization-boundary)*

Acceptance: the Sprint Contract settles generation/validator/session size thresholds and messages before edits; the design's Golden Principles/Delegation/Token Economy/Maintenance policy replaces contradictory verbatim mandates; minimal/existing fixtures, broken references/configuration, configured delegation and each size boundary are covered. Approach: update owning examples/rationale/invariants with validator changes; preserve applicable safety rules and version both dev manifests when shipped assets change.

## 4. P2 — subagent-model-selection-policy

Source: `docs/design/harness-policy-alignment.md` → Implementation Decisions, slice 4. Read the platform-specific precedence corrections; model omission does not activate automatic routing.

- [ ] [HARNESS] Document task-specific model/effort selection in docs/delegation.md and platform resolution in docs/platform-specs.md: advisory Light/Standard/Deep, expected total cost, evidence-based escalation, resolved defaults, Claude version/forced-mode exceptions, and Codex custom-agent precedence; retain current role pins and separate headless review policy. Read `docs/design/harness-policy-alignment.md`, slice 4, before forming the contract. *(blocked by: 3-harness-init-simplification)*

Acceptance: the policy is explicitly provisional; advisory model tiers are independent of unchanged Effort Tier budgets; dated official sources and installed-version evidence support platform precedence, or local availability is marked unverified; common policy carries no fixed provider IDs and existing runtime settings remain unchanged. Approach: policy-first P2 documentation, no global rules, new router, or duplicate roles.

## 5. P2 — subagent-model-selection-evaluation

Source: `docs/design/harness-policy-alignment.md` → Implementation Decisions, slice 5 and Testing Decisions. Read the paired-run protocol before launching agents; keep the existing headless review-effort experiment separate.

- [ ] [HARNESS] Evaluate approximately 10–20 representative delegated tasks against current settings using paired inputs/criteria: Claude per-spawn overrides and Codex unpinned evaluation roles or built-ins; record requested/actual settings, client/default/forced context, quality, retries, lead review, elapsed time, tokens and measured or explicitly estimated cost; recommend role-specific keep/change/unverified outcomes without removing production pins. Read `docs/design/harness-policy-alignment.md`, slice 5, before forming the contract. *(blocked by: 4-subagent-model-selection-policy)*

Acceptance: preregister 10–20 task IDs total, finite attempts/time/cost-token budgets per platform, observation methods and benefit thresholds; setting-unverified runs cannot support model-effect claims; recommendations meet the design's paired-input/repeat/quality evidence bars and include total retry/review cost; unfinished platforms remain unverified and pin changes require a follow-up. Approach: staged platform runs using existing evaluation conventions and evaluation-only selection reasons; no permanent telemetry or reviewer-process changes.

## 6. Skill frontmatter hygiene

Source: `docs/design/skill-review-followups.md` → Implementation Decisions, slice A. Read the design before forming the Sprint Contract; covers only residual hygiene not owned by backlog 1–5.

- [ ] [HARNESS] Add missing `version:` to dev/skills/harness-init, task-review, task-review-cycle, repo-dependabot and prod/skills/hwpx, persona-debate; audit `allowed-tools` per skill (gongmun-draft/report-draft absent, kr-style Glob omission) with a one-line reason each. Read `docs/design/skill-review-followups.md`, slice A, before forming the contract.

Acceptance: `grep -r '^version:' dev/skills prod/skills` shows zero misses; frontmatter checker and harness validation pass; bumps follow conventions with both manifests in sync; model-pin lines untouched. Approach: metadata-only fix, no authorization or delegation changes. Dependencies: none (soft: prefer after 1–3 land to avoid racing P0/P1 edits).

## 7. HWPX trigger and report coupling

Source: `docs/design/skill-review-followups.md` → Implementation Decisions, slice B. Read the design before forming the Sprint Contract.

- [ ] [HARNESS] Fix hwpx description-vs-behavior contradiction on legacy `.hwp` (SKILL.md:7 vs :218) and decouple report-draft `HWPX_DIR="$SKILL_DIR/../hwpx"` sibling-path coupling toward Skill-tool invocation or plugin-root resolution. Read `docs/design/skill-review-followups.md`, slice B, before forming the contract.

Acceptance: `.hwp` requests route to hwpx; trigger-collision check passes; report-draft lint/validate flows pass after decoupling; no behavior change to conversion itself. Approach: description fix plus path decoupling in one slice; check other `../<skill>` references. Dependencies: none.

## 8. Evidence-rule and wording corrections

Source: `docs/design/skill-review-followups.md` → Implementation Decisions, slice C. Read the design before forming the Sprint Contract.

- [ ] [HARNESS] Unify gongmun-draft unverified-value rule (:18 vs :97) toward `[확인 필요]` placeholders listed in Step 5, and narrow repo-quiz single-writer invariant (:247–249) to its scoped `mistakes.md` exception. Read `docs/design/skill-review-followups.md`, slice C, before forming the contract.

Acceptance: both gongmun lines agree (draft with placeholders, never fabricated dates); repo-quiz invariant matches `allowed-tools`; docs-only inspection, no behavior tests. Approach: wording-only correction, no fallback routing or availability changes. Dependencies: none.

## Harness — `task-*` edge enforcement (rescoped)

Source: `docs/design/task-graph-audit.md`, re-scored in `docs/design/harness-altitude-audit.md`.
Each edge is scored on three questions — **Silent** (invisible to the orchestrator at its next
decision point), **Costly** (damage survives the session: lands on `main`/remote, corrupts tracked
state, or burns a resource a re-run does not reclaim), **Decidable** (a file or exit code settles
it). 3/3 ships; 2/3 ships only if the residual failure is unbounded; 0–1/3 is ceremony.

Cut items and their re-file bars live in `docs/design/harness-altitude-audit.md` →
*Cut — do not re-file without new evidence*. Nothing from this group is queued.

## Harness — review effort follow-up

- [ ] [harness] task-review-cycle: measure `EFFORT=high` vs default (and `low`) on a security plant buried in a large, mostly benign diff — f1–f7 (`dev/skills/task-review-cycle/evals/security-effort/RESULTS.md`) are ≤9-line diffs that hit a recall ceiling twice; record the resolved model ID per run (source: code-review PR #298)

## Review Backlog

### PR #290 — task-grill skill-extraction interview slots (2026-10-02)

- [ ] [harness] No consumer carries the `Skill slots:` block: neither the Sprint Contract template (`docs/eval-criteria.md`) nor the task-spec template has a field for it, and no skill-authoring route (harness-capture/harness-curate → `skill-creator`) invokes task-grill first; caller wiring was deferred by user decision (source: code-review) — dev/skills/task-grill/SKILL.md:80 *(deferred: caller wiring held by user decision; excluded again from the 2026-10-02 batch)*

### PR #272 — review slot shell-out follow-ups

- [ ] [HARNESS] Re-fit `agy-review.sh`'s `--print-timeout` to the reviewer's runway — the Claude slot now holds the foreground for at most 600s and the cycle no longer waits past it, so agy's 15m self-cap means it will almost never report in time; decide the new cap against `timings.log` per `late-source-reclaim.md`, not against one cycle *(deferred: `timings.log` is written only by `codex-review.sh`, so it carries zero agy rows — and agy persists no sidecar, so the cap governs only how long an unreadable run continues, not whether its findings land; revisit when agy timing is recorded)*

### PR #254 — memory-guard follow-ups

- [ ] [FEAT] Gate shell-based memory writes in `memory-guard` — the hook matches `Write|Edit` only, so `printf ... > ~/.claude/projects/<slug>/memory/note.md` writes ungated; `commit-guard`'s PreToolUse(Bash) static command analysis is the precedent to follow *(deferred: no shell-path memory write has been observed; the other four PR #254 follow-ups shipped without it in PR for 4.9.6 — revisit against a recorded case)*
