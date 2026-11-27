# Harness Maintenance Routine

Maintain repo agent instruction files under **minimal-noise policy**.

> **Session-start recommendation:** Add an explicit call in your `/init` command or SessionStart hook to enable automatic sync.

**Primary goal:**
- `AGENTS.md` — canonical, minimal operational log (size: `harness-invariants.md` → *AGENTS.md Size Policy*)
- `CLAUDE.md` — must contain exactly one line: `@AGENTS.md`
- `.agents/skills` → `../.claude/skills` symlink
- `tasks.md` holds Sprint Contracts. The persistent queue is `backlog.md` on the file backend
  and forge issues on the issues backend. See the reconciliation contract.

All thresholds, paths, contracts live in `harness-invariants.md`. Update there when values change.

## When to run

- Session start (recommended: wire into `/init` or SessionStart hook)
- After intentional harness edit (AGENTS.md/docs/ touched)
- Drift suspected (mismatched CLAUDE.md, orphaned `[>]` markers, broken symlink)

NOT for: rewriting AGENTS.md body, enforcing golden principles (→ sweep), bootstrap (→ harness-init bootstrap steps).

---

## Execution Order

A requires human judgment. B/C/D/E/F independent, may parallelize.
Scripts (C, E, F) always exit 0 on informational results — parallel sibling failure cannot cancel other checks. Non-zero = hard failure, stop batch.
B (sync-claude-md) exits 1/2 as normal remediation path, exempt from this contract.
Silent unless action taken or error occurs.

---

## A) AGENTS.md Update Rules

Apply `harness-invariants.md` → *AGENTS.md Edit Policy* (the four-condition filter and the
never-add list) when editing AGENTS.md. Edits minimal. Prefer modifying/removing outdated entries over appending.
Unsure → add short inline `TODO:` comment, don't invent guidance.

**If edit guidance is absent:** add concise applicable policy or a pointer to an existing policy. Preserve useful safety boundaries; avoid duplicating generic blocks.

---

## B) CLAUDE.md Deterministic Sync

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/sync-claude-md.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/sync-claude-md.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/sync-claude-md.sh"
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

Run silently. The script closes the `tasks.md` sprint block per its `status:`. For actions
on each backend, see `harness-invariants.md` → *Reconciliation Contract*.

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/reconcile-harness.py" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/reconcile-harness.py" >&2; exit 1; }
python3 "$SKILL_DIR/scripts/reconcile-harness.py"
```

Output:
- `Sprint active: <title>` / `Sprint queued: <title>` — leave intact
- `Sprint '<title>' done. tasks.md removed.` — sprint archived; D-2 applies
- `Sprint '<title>' failed. Sprint block closed.` — local sprint closed. The file backend
  adds `backlog items reverted to [ ]` to the status.
- On the file backend, `Backlog: N queued, M active` reports file counts and
  `Backlog clear.` reports an empty file queue. Use the queue listing for issues.

---

## D) Harness Docs Reconciliation

Run after C. Requires judgment — not scripted. Repo file-state only; skill/agent
**portfolio** health (which assets fire, which are stale or never load) is not
maintained here — that is transcript-driven and lives in `harness-curate`.

### D-1) Docs structure check

Verify **schema** (not content) of harness-related docs. Full schemas in `backlog-template.md` and `tasks-template.md`; minimal assertions below match those templates:

- File backend: `backlog.md` items follow the `[ ]` / `[>]` / `[x]` checkbox pattern under
  `##` headings, with plain bullets under `## Rejected — do not re-file`.
- Issues backend: absence of `backlog.md` is expected. GitHub origins with open file items
  awaiting migration still use the file backend. Relay the validator's `migrate_backlog.py` pointer.
- `tasks.md` must have a top-level `# Title`, `status:` line and Sprint Contract fields.
  Transfer persistent `## Review Backlog` or `## Security Fixes` entries to the resolved queue.

Structural drift detected → fix schema in-place. Do **not** rewrite content.

Point a repo adopting the file backend without `backlog.md` to harness-init Step 4a.
Absent `tasks.md` indicates an idle sprint.

### D-2) Doc-worthy capture (when C reported a sprint `done`)

At cleanup, the file cycle deletes the finished item and records its title in
`CHANGELOG.md`. On the issues backend, the closed issue preserves the queue record.
Judge whether the
shipped work established something future work must respect: a constraint, an
invariant, a behavior contract, a design decision. The script cannot make this
call; you must.

Signal to judge from (tasks.md is already deleted by C):
- the `done` line C printed (`Sprint '<title>' done. tasks.md removed.`)
- the latest `CHANGELOG.md` entry — title only, per the CHANGELOG Entry Contract; it names
  the change but carries no detail, so lean the judgment on the git bullet below
- `git log origin/main..HEAD` / `git diff origin/main..HEAD` for the sprint's commits

If doc-worthy → extract it into the relevant `docs/*.md` (the file named in the
AGENTS.md docs index) **as a durable rule**, before moving on. If it was a
routine fix, the existing history suffices. Keep durable rules in the owning doc.

### D-3) Plan remaining (only when the user asks)

When the user asks what to do next ("남은 작업 계획", "뭐부터 하지", "what's
next"), use `dev:task-next` → `references/queue-backend-contract.md` → *Ops* (`list`).
Summarize open file items by heading or open issues by group, then propose an order.
Leave sprint creation to the user.

---

## E) Skills Symlink Guard

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/symlink-guard.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/symlink-guard.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/symlink-guard.sh"
```

Ensures `.agents/skills` symlinks to `../.claude/skills`.
Silent on success; prints one line on change.

---

## F) Context Size Check

```bash
SKILL_DIR="<absolute parent directory of the loaded SKILL.md>"
[[ -f "$SKILL_DIR/scripts/check-context-size.sh" ]] || { echo "Bundled script unavailable: $SKILL_DIR/scripts/check-context-size.sh" >&2; exit 1; }
bash "$SKILL_DIR/scripts/check-context-size.sh"
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
| `scripts/reconcile-harness.py` | C | Close the sprint block; report counts on the file queue |
| `scripts/symlink-guard.sh` | E | Ensure .agents/skills symlink |
| `scripts/check-context-size.sh` | F | Warn when effective CLAUDE.md/AGENTS.md > 200 lines |

All scripts run from repo root, operate on files in current working directory.

## Post-sync: sweep

After all sections complete, run:

```bash
bash tools/sweep.sh
```

If `tools/sweep.sh` does not exist, skip this step and note the omission in the sync summary. This archives stale content per the minimal-noise policy.

## G) Post-sync validate

Run `scripts/validate-harness.sh` to confirm invariants still hold after sync.

- exit 0 (pass) or warn-only → continue
- hard fail → report to user, do NOT auto-fix (treat as init bug per pairing contract)
- script absent (legacy bootstrap) → emit one-line warning, exit 0 (parallel-safe)

---

## What the maintenance routine does NOT do

- **auto-sweep without check** — `tools/sweep.sh` (installed by harness-init Step 5) runs as a post-sync step but only if the file exists. Trigger policy beyond that (manual / SessionStart hook / cron) chosen at init time, recorded in `docs/runbook.md`.
- **full validation** — `scripts/validate-harness.sh` does deeper structural checks (conditional principle/delegation guidance, reference/configuration integrity, enforcement layer detection). Run after intentional harness change; routine only catches mechanically fixable drift.
- **content rewriting** — maintenance routine never rewrites body of `backlog.md`, `tasks.md`, or `AGENTS.md`. Fixes schemas, moves state through reconciliation contract; everything else is human's call.
