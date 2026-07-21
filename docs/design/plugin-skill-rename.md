# Design: Plugin + Skill Naming Unification

**Status:** implemented (`eeb1084`, PR #161)
**Branch:** `refactor/plugin-skill-rename`
**Type:** `[REFACTOR]` — rename only, no behavior change. Major version bump on both renamed plugins.

## Goal

Two renames, done atomically in one PR:

1. **Plugins:** `dev-tools` → `dev`, `productivity` → `prod`. `team-standards` unchanged in name
   (but content edited — see below).
2. **dev skills:** unify under domain-prefix families (`task-*`, `harness-*`, `repo-*`). `grill`
   joins `task-*` as `task-grill` (it's the task-intake ambiguity-resolution step). `prod` skills
   keep their names (only the plugin prefix changes).
3. **Move:** `repo-quiz` relocates from the dev plugin to the prod plugin (name kept →
   `prod:repo-quiz`), since it's a learning/productivity tool, not a dev-cycle skill.
4. **Retire:** delete `orchestrate` and `loop-engineer` from the dev plugin. No skill invokes them
   via `Skill()`; the only pointers are docs. This is why the dev bump is unambiguously major.

Rationale: current dev-tools skill names mix verb / role-noun / preposition / singular-plural
forms; domain prefixes group related skills and make invocation predictable. Short plugin names
(`dev:`, `prod:`) cut invocation noise.

## Rename maps

### Plugins

| Old | New | Version |
|-----|-----|---------|
| `dev-tools` | `dev` | 3.11.2 → **4.0.0** |
| `productivity` | `prod` | 2.2.16 → **3.0.0** |
| `team-standards` | (name unchanged) | 1.0.0 → **1.0.1** (AGENT-STANDARDS.md pointer edit) |

### dev skills (directory + `name:` frontmatter)

| Family | Old → New |
|--------|-----------|
| task | `new-task`→`task-new`, `next-tasks`→`task-next`, `to-spec`→`task-spec`, `to-tickets`→`task-tickets`, `dev-review-cycle`→`task-review`, `grill`→`task-grill` |
| harness | `harness-init` (unchanged), `harness-curator`→`harness-curate`, `capture-learnings`→`harness-capture` |
| repo | `dependabot-manager`→`repo-dependabot` (`repo-quiz` moves to prod — see below) |

**Retired:** `orchestrate`, `loop-engineer` — deleted, not renamed.

9 dev skill dirs renamed in place; `harness-init` keeps its name; `repo-quiz` moves to prod;
`orchestrate`/`loop-engineer` are removed. dev's `repo` family is left with a single member
(`repo-dependabot`) — acceptable, the prefix still reads as "repo tooling". Final dev roster:
`task-{new,next,spec,tickets,review,grill}`, `harness-{init,curate,capture}`, `repo-dependabot`.

### prod skills (plugin prefix only, plus the moved skill)

`hwpx` and `persona-debate` keep their names. `repo-quiz` joins them via `git mv
dev-tools/skills/repo-quiz prod/skills/repo-quiz`; its invocation becomes `prod:repo-quiz`.

### Invocation prefix (compound — both parts can change)

- `productivity:<skill>` → `prod:<skill>` (skill name unchanged).
- `dev-tools:<oldskill>` → `dev:<newskill>` — **not** a bare prefix swap. E.g.
  `dev-tools:next-tasks` → `dev:task-next`, `dev-tools:capture-learnings` → `dev:harness-capture`.
- Bare skill-name mentions in prose (`next-tasks`, `to-spec`, `grill`, …) also update, but only
  where they refer to the skill — watch the English verb `orchestrate` (a false positive, and its
  skill is being deleted anyway, so those refs are removed, not renamed).

## Touch-points (sweep targets)

1. **Directory rename** (`git mv`): `dev-tools/`→`dev/`, `productivity/`→`prod/`, the 9 renamed dev
   skill subdirs, and the cross-plugin move `dev/skills/repo-quiz`→`prod/skills/repo-quiz`.
   **Delete** (`git rm -r`): `dev/skills/orchestrate`, `dev/skills/loop-engineer`.
2. **Manifests** (`name` field): `{dev,prod}/.claude-plugin/plugin.json` +
   `.codex-plugin/plugin.json` (4 files). Bump versions per table.
3. **Marketplace**: `.claude-plugin/marketplace.json` and `.agents/plugins/marketplace.json` —
   `name` + `source`/`path` for both renamed plugins.
4. **Skill `name:` frontmatter**: each renamed `SKILL.md`.
5. **Cross-refs**: 19 files use `dev-tools:`, 2 use `productivity:`; ~11 files use bare
   `dev-tools/`/`productivity/` paths. Includes `README.md`, `docs/*.md`,
   `team-standards/standards/AGENT-STANDARDS.md`, and dev skills referencing each other.
6. **CI**: `.github/workflows/harness-check.yml` — the three version-bump jobs hardcode
   `dev-tools`/`productivity` paths (~50 lines). See CI bootstrapping below.
7. **AGENTS.md**: the Docs Index / Golden Principles reference plugin dirs and skill names.
8. **Retirement cleanup**: remove the `orchestrate`/`loop-engineer` rows from `README.md` (skill
   table + `npx skills add` examples), and drop the `dev-tools:orchestrate` pointer from
   `team-standards/standards/AGENT-STANDARDS.md` (→ team-standards patch bump). Leave the false
   positives untouched: `harness-init/references/conventions-template.md` ("views orchestrate" is
   the English verb) and `CHANGELOG.md` history lines.

Out of scope (cannot control from the repo, flag to user for manual post-merge cleanup):
- The user's `~/.claude` plugin cache (regenerated on reinstall).
- `settings.local.json` permission entries naming `dev-tools:`/`productivity:`.
- **Global `~/.claude/CLAUDE.md` line 19** — `Detailed routing/model recipes → dev-tools:orchestrate`
  becomes a dangling pointer once `orchestrate` is retired; offer to edit it separately (it is not
  part of this repo's PR).

## CI bootstrapping problem + resolution

`harness-check.yml` compares `git show origin/main:<plugin>/…/plugin.json` (OLD) against the
working-tree manifest (NEW). After renaming `dev-tools`→`dev`, `origin/main:dev/…` does not exist
(main still has `dev-tools/`), so `git show` fails and the job breaks **on the rename PR itself**.

**Resolution:** rewrite the jobs to the new paths (`dev`, `prod`) AND add a guard: if the OLD
manifest is absent on `origin/main` (`git show … || true` yields empty), treat it as a
newly-pathed plugin — print `NEW/renamed plugin dir, skipping increment check` and pass. This also
correctly handles genuinely new plugins. Post-merge (main has `dev/`), normal increment checks
resume. The rename commit must include this workflow edit so CI is green in the same PR.

## Execution order (deterministic)

1. `git mv` plugin dirs and the 11 skill subdirs.
2. Update 4 plugin manifests (`name` + version bump) and both marketplace.json.
3. Update each renamed `SKILL.md` `name:` frontmatter.
4. Rewrite `harness-check.yml` (new paths + missing-old-path guard).
5. Sweep cross-refs via the compound map (prefix+skill), then bare path refs, then bare skill-name
   mentions (reviewed, not blind `sed`).
6. Update `AGENTS.md` and `README.md`.

## Verification gate (all must hold before merge)

- `grep -rI 'dev-tools\|productivity\|<renamed skill names>\|orchestrate\|loop-engineer'` over
  tracked files returns **0**, excluding: this spec, `CHANGELOG.md` history, the migration-continuity
  names `.harness-curator-state.json` and `task-audit-nudge/`, and the known false positive
  `conventions-template.md` ("views orchestrate"). No other stale name survives.
- `grep -rI 'dev-tools:\|productivity:'` returns 0 (no stale invocation prefix).
- `dev/skills/orchestrate` and `dev/skills/loop-engineer` no longer exist.
- Every `SKILL.md` `name:` matches its new directory name.
- `validate-harness.sh` → 0 FAIL.
- Each renamed dir resolves for every cross-ref (spot-check `Skill(dev:…)` targets exist).
- CI (`harness-check.yml`) green on the PR.

## Risks

- **Large diff / churn** — mitigated by doing it atomically (one PR, refs touched once) rather than
  in two passes.
- **False-positive sweeps** on generic words (`orchestrate` the verb, `dev`) — mitigated by
  reviewing bare-word replacements rather than blind global replace.
- **Downstream users** must re-install the marketplace and update any pinned `dev-tools:`/
  `productivity:` permissions — call out in the PR description.
