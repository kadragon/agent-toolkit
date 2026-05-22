---
name: harness-sync
version: 0.2.0
description: "This skill should be used when the user says: \"sync harness\", \"harness sync\", \"harness 동기화\", \"AGENTS.md 정리\", \"AGENTS.md 업데이트\", \"CLAUDE.md 동기화\", \"backlog 정리\", \"tasks 정리\", \"세션 시작 루틴\", \"하네스 유지보수\"."
---

# Harness Sync

Maintain repo agent instruction files under **minimal-noise policy**.

> **Session-start recommendation:** Add an explicit call to this skill in your `/init` command or session-start hook to enable automatic sync.

**Paired skill:** `harness-init` bootstraps invariants this skill maintains. First-run sync shows unexpected drift in init-bootstrapped repo → treat as init bug, fix template — not sync false positive.

**Primary goal:**
- `AGENTS.md` — canonical, minimal operational log (target ≤100 lines, hard warn >200)
- `CLAUDE.md` — must contain exactly one line: `@AGENTS.md`
- `.agents/skills` → `../.claude/skills` symlink
- `backlog.md` / `tasks.md` — follow reconciliation contract

All thresholds, paths, contracts live in `harness-init`'s `references/harness-invariants.md`. Update there, not here, when values change.

## Execution Order

A requires human judgment. B/C/D/E/F independent, may parallelize.
Scripts (C, E, F) always exit 0 on informational results — parallel sibling failure cannot cancel other checks. Non-zero = hard failure, stop batch.
B (sync-claude-md) exits 1/2 as normal remediation path, exempt from this contract.
Silent unless action taken or error occurs.

---

## A) AGENTS.md Update Rules

4-rule edit policy below also embedded verbatim in AGENTS.md's `## Maintenance` section by `harness-init` (see `references/harness-invariants.md` → "AGENTS.md Edit Policy"). Any session editing AGENTS.md — not only sync sessions — follows same filter. Keep two copies in lockstep.

Update `AGENTS.md` **only** when ALL true:

1. Info not directly discoverable from code / config / manifests / docs
2. Operationally significant — affects build, test, deploy, or runtime safety
3. Would likely cause mistakes if undocumented
4. Stable, not task-specific

**Never add:**
- Architecture summaries or tech stack descriptions
- Directory structure overviews
- Style conventions already enforced by tooling
- Anything already visible in repo
- Temporary or task-specific instructions

Edits minimal. Prefer modifying/removing outdated entries over appending.
Unsure → add short inline `TODO:` comment, don't invent guidance.

**If AGENTS.md lacks `## Maintenance` section:** repo bootstrapped by older init or set up manually. Add section in-place using this exact rule list — costs nothing, makes policy visible to every future session.

---

## B) CLAUDE.md Deterministic Sync

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/harness-sync/scripts/sync-claude-md.sh
```

Exit codes:
- `0` — Already contains exactly `@AGENTS.md`. Stop.
- `1` — Did not exist → script created it with `@AGENTS.md`. Done.
- `2` — Exists but differs → script printed original content to stdout.

**If exit code 2:**
1. Read extracted content from stdout.
2. **Validate before proceeding:** if extracted content is empty or unparseable (no lines, binary garbage, or unmatched structure), halt immediately — do not proceed to step 3. Show user the raw extract and ask for manual review.
3. Filter each instruction using A) acceptance criteria.
4. Merge qualifying items into `AGENTS.md`: insert under the existing matching heading. If no matching heading exists, append a new section at the end of the file. Deduplicate: skip any item already present verbatim. If structural conflict exists (e.g., two `## Maintenance` sections), merge their content under one heading and note the consolidation in the sync summary.
5. Rewrite `CLAUDE.md` to contain exactly (no extra text, no blank lines):
   ```
   @AGENTS.md
   ```

---

## C) Harness Reconciliation

Run silently. Script syncs `tasks.md` status into `backlog.md`, prints one status line.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/skills/harness-sync/scripts/reconcile-harness.py
```

Output:
- `Sprint active: <title>` — tasks.md active or evaluating; leave intact
- `Backlog: N queued, M active` — backlog has pending items
- `Backlog clear.` — nothing pending

---

## D) Harness Docs & Skills Refresh

Run after C. Requires judgment — not scripted.

### D-1) Docs structure check

Verify **schema** (not content) of harness-related docs. Full schemas in `harness-init`'s `references/backlog-template.md` and `references/tasks-template.md`; minimal assertions below match those templates:

- `backlog.md` items must follow `[ ]` / `[>]` / `[x]` checkbox pattern under `##` headings
- `tasks.md` must have: top-level `# Title`, `status:` line, sections `Scope`, `Acceptance Criteria`, `Evaluator Feedback`

Structural drift detected → fix schema in-place. Do **not** rewrite content.

Either file entirely missing → repo not fully bootstrapped — point user at `harness-init` Step 4b, don't guess content.

### D-2) Skills refresh

```bash
find .claude/skills -name "SKILL.md" 2>/dev/null
```

For each `SKILL.md` found:
- Verify frontmatter parseable (must have `name` and `description` fields)
- Flag stale skills: run `git log --follow -1 --format='%ci' <skill-path>/SKILL.md` for each skill. Flag skills with no commit in 60+ days. If git is unavailable, skip and note in summary.

Print stale list to stdout if any. Do **not** auto-delete — human decides.

---

## E) Skills Symlink Guard

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/harness-sync/scripts/symlink-guard.sh
```

Ensures `.agents/skills` symlinks to `../.claude/skills`.
Silent on success; prints one line on change.

---

## F) Context Size Check

```bash
bash ${CLAUDE_PLUGIN_ROOT}/skills/harness-sync/scripts/check-context-size.sh
```

Warns when file Claude reloads every message grows past hard-warn threshold (default 200 lines; see `harness-invariants.md` → "AGENTS.md Size Policy"). `harness-init` targets ≤100 lines — 100–200 band is soft zone; `validate-harness.sh` flags at init time; sync check silent until >200. Resolves effective file automatically:

- If `CLAUDE.md` is exactly `@AGENTS.md` → checks `AGENTS.md`
- Otherwise → checks `CLAUDE.md` directly

Silent under limit. On overflow, prints one line plus optional bloat hints:

```
context-size: AGENTS.md is 247 lines (>200) — consider splitting into docs/*.md and leaving pointers
  hint: ~140 lines are inside fenced code blocks — AGENTS.md is a map, move examples to docs/
  hint: duplicate ## headings detected (5 total, 3 unique) — merge redundant sections
```

Two heuristics catch most common bloat causes:
- **Fenced code blocks > 20% of total** — AGENTS.md = map, not cookbook. Long examples → `docs/*.md`.
- **Duplicate `##` headings** — stale appends instead of edits; merge or subdivide with `###`.

**Caveat:** fenced code block detection uses a toggle counter on ` ``` ` lines. If `AGENTS.md` contains unclosed triple-backtick blocks (malformed markdown), the context size estimate may be inaccurate. Fix malformed markdown before relying on this check.

**Do not auto-trim.** 200+ line file may be load-bearing. Surface warning, let human decide what moves into `docs/*.md` with pointer line in `AGENTS.md` (pattern: `See docs/conventions.md for naming rules.`).

Override threshold via env var: `CONTEXT_SIZE_LIMIT=300 bash ...`.

---

## Bundled Scripts

| Script | Section | Purpose |
|--------|---------|---------|
| `scripts/sync-claude-md.sh` | B | Check CLAUDE.md state; exit 0/1/2 |
| `scripts/reconcile-harness.py` | C | Sync tasks.md → backlog.md |
| `scripts/symlink-guard.sh` | E | Ensure .agents/skills symlink |
| `scripts/check-context-size.sh` | F | Warn when effective CLAUDE.md/AGENTS.md > 200 lines |

All scripts run from repo root, operate on files in current working directory.

## Post-sync: sweep

After all sections complete, run:

```bash
bash tools/sweep.sh
```

If `tools/sweep.sh` does not exist, skip this step and note the omission in the sync summary. This archives stale content per the minimal-noise policy.

## What sync does NOT do

- **auto-sweep without check** — `tools/sweep.sh` (installed by `harness-init` Step 5) runs as a post-sync step but only if the file exists. Trigger policy beyond that (manual / SessionStart hook / cron) chosen at init time, recorded in `docs/runbook.md`.
- **full validation** — `harness-init`'s `scripts/validate-harness.sh` does deeper structural checks (golden principle count, reference integrity, enforcement layer detection). Run after intentional harness change; sync only catches mechanically fixable drift.
- **content rewriting** — sync never rewrites body of `backlog.md`, `tasks.md`, or `AGENTS.md`. Fixes schemas, moves state through reconciliation contract; everything else is human's call.