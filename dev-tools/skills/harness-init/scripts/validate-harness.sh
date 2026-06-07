#!/bin/bash
# validate-harness.sh — Verify harness artifacts are complete and consistent
# Usage: bash validate-harness.sh [project-root]
#
# Checks (keep aligned with references/harness-invariants.md):
#   1. Required files exist (AGENTS.md, CLAUDE.md, docs/*, backlog.md)
#   2. AGENTS.md size policy (target ≤100, warn ≤120, fail >120)
#   3. All files referenced in AGENTS.md docs index exist
#   4. Golden principles section present and 3-7 items
#   5. Delegation table is present and non-empty
#   6. Enforcement layer detected (hooks, pre-commit, or CI)
#   7. CLAUDE.md is exactly "@AGENTS.md" (sync B invariant)
#   8. .agents/skills → ../.claude/skills symlink (sync E invariant)
#   9. backlog.md schema (checkbox items under ## headings; sync D-1)
#  10. AGENTS.md ## Maintenance section embeds edit-policy rules
#
# A clean run means the maintenance routine will be a no-op on first invocation.
# Performance: Sections 1–5 and 7–10 use [[ =~ ]] bash builtins, no grep
# subprocesses. AGENTS.md is read in a single pass — no repeated file scans.
# Section 6b (auto-delegation router) uses grep to match SKILL.md content.

set -euo pipefail

PROJ_DIR="${1:-.}"
cd "$PROJ_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

PASS=0
WARN=0
FAIL=0

pass()  { PASS=$((PASS + 1)); echo -e "  ${GREEN}PASS${NC}  $1"; }
warn()  { WARN=$((WARN + 1)); echo -e "  ${YELLOW}WARN${NC}  $1"; }
fail()  { FAIL=$((FAIL + 1)); echo -e "  ${RED}FAIL${NC}  $1"; }

echo "=== Harness Validation ==="
echo "  Project: $(pwd)"
echo ""

# ── 1. Required files ──────────────────────────────────────
echo "--- Required Files ---"

for f in AGENTS.md CLAUDE.md; do
    [[ -f "$f" ]] && pass "$f exists" || fail "$f missing"
done

for f in docs/architecture.md docs/conventions.md docs/workflows.md docs/delegation.md docs/eval-criteria.md docs/runbook.md; do
    [[ -f "$f" ]] && pass "$f exists" || warn "$f missing"
done

# Harness state files (sync C/D-1 expect these)
[[ -f "backlog.md" ]] && pass "backlog.md exists" || warn "backlog.md missing (sync C expects it)"

# ── 2. AGENTS.md line count ────────────────────────────────
echo ""
echo "--- AGENTS.md Size ---"

if [[ -f "AGENTS.md" ]]; then
    lines=$(wc -l < AGENTS.md | tr -d ' ')
    if [[ $lines -le 100 ]]; then
        pass "AGENTS.md is $lines lines (limit: 100)"
    elif [[ $lines -le 120 ]]; then
        warn "AGENTS.md is $lines lines (limit: 100, slightly over)"
    else
        fail "AGENTS.md is $lines lines (limit: 100, too long)"
    fi
fi

# ── Single-pass AGENTS.md analysis ─────────────────────────
# Read AGENTS.md once; extract doc references, golden principles,
# delegation presence, and Maintenance section using [[ =~ ]] — zero grep forks.

referenced_docs=""
has_golden=false
principle_count=0
has_delegation=false
has_maintenance=false
maint_rule_count=0
in_golden_section=false
in_maintenance_section=false

if [[ -f "AGENTS.md" ]]; then
    while IFS= read -r line; do
        # Extract backtick-quoted doc references: `docs/...`
        remaining="$line"
        while [[ "$remaining" =~ \`(docs/[a-zA-Z0-9_./-]+)\` ]]; do
            referenced_docs+="${BASH_REMATCH[1]}"$'\n'
            remaining="${remaining#*"${BASH_REMATCH[0]}"}"
        done

        # Track Golden Principles section boundaries
        if [[ "$line" =~ ^##.*Golden[[:space:]]+Principles ]]; then
            has_golden=true; in_golden_section=true; in_maintenance_section=false; continue
        fi
        # Track Maintenance section (carries the AGENTS.md edit policy)
        if [[ "$line" =~ ^##[[:space:]]+Maintenance ]]; then
            has_maintenance=true; in_maintenance_section=true; in_golden_section=false; continue
        fi
        # Detect Delegation section header (must precede section-exit logic to avoid continue skipping it)
        if [[ "$line" =~ ^##[[:space:]].*Delegation ]]; then
            has_delegation=true; in_golden_section=false; in_maintenance_section=false; continue
        fi
        if $in_golden_section; then
            [[ "$line" =~ ^## ]] && { in_golden_section=false; continue; }
            [[ "$line" =~ ^[0-9]+\. ]] && principle_count=$((principle_count + 1))
        fi
        if $in_maintenance_section; then
            [[ "$line" =~ ^## ]] && { in_maintenance_section=false; continue; }
            [[ "$line" =~ ^[0-9]+\. ]] && maint_rule_count=$((maint_rule_count + 1))
        fi
    done < AGENTS.md
    referenced_docs="${referenced_docs%$'\n'}"
fi

# ── 3. Reference integrity ─────────────────────────────────
echo ""
echo "--- Reference Integrity ---"

if [[ -f "AGENTS.md" ]]; then
    if [[ -z "$referenced_docs" ]]; then
        warn "No docs/ references found in AGENTS.md"
    else
        while IFS= read -r doc; do
            [[ -z "$doc" ]] && continue
            [[ -f "$doc" ]] && pass "Referenced $doc exists" || fail "Referenced $doc missing"
        done <<< "$referenced_docs"
    fi
fi

# ── 4. Golden principles section ───────────────────────────
echo ""
echo "--- Golden Principles ---"

if [[ -f "AGENTS.md" ]]; then
    if $has_golden; then
        if [[ $principle_count -ge 3 && $principle_count -le 7 ]]; then
            pass "$principle_count golden principles defined (ideal: 3-7)"
        elif [[ $principle_count -gt 0 ]]; then
            warn "$principle_count golden principles (recommend 3-7)"
        else
            warn "Golden Principles section exists but no numbered items found"
        fi
    else
        fail "No Golden Principles section in AGENTS.md"
    fi
fi

# ── 5. Delegation table ────────────────────────────────────
echo ""
echo "--- Delegation ---"

if [[ -f "AGENTS.md" ]]; then
    if $has_delegation; then
        pass "Delegation section exists in AGENTS.md"
    else
        warn "No Delegation section in AGENTS.md"
    fi
fi

if [[ -f "docs/delegation.md" ]]; then
    pass "docs/delegation.md exists with detailed routing"
else
    warn "docs/delegation.md missing — delegation details not documented"
fi

# ── 6. Enforcement check ───────────────────────────────────
echo ""
echo "--- Enforcement ---"

has_enforcement=false
[[ -f ".claude/settings.json" ]] && { pass ".claude/settings.json (hooks) exists"; has_enforcement=true; }
[[ -f ".pre-commit-config.yaml" ]] && { pass ".pre-commit-config.yaml exists"; has_enforcement=true; }
[[ -f ".husky/pre-commit" ]] && { pass ".husky/pre-commit exists"; has_enforcement=true; }
[[ -d ".github/workflows" ]] && { pass ".github/workflows/ exists"; has_enforcement=true; }

$has_enforcement || warn "No enforcement layer detected (hooks, pre-commit, or CI)"

# ── 6b. Auto-Delegation Router (Step 7b) ──────────────────
# Warn only when there is something worth routing to:
#   - any .claude/agents/{role}.md, OR
#   - any .claude/skills/*/SKILL.md whose description directs delegation
#     (mentions an orchestrator or carries an ALWAYS-invoke directive).
# A trivial single-skill repo (e.g. a doc formatter) should NOT warn.
# Uses `find` instead of bash-builtin `compgen` so this block runs under
# `sh`/`zsh` invocation as well as `bash`.
has_orchestrator=false
has_agents=false
if [[ -d ".claude/agents" ]]; then
    find ".claude/agents" -maxdepth 1 -name "*.md" -print -quit 2>/dev/null | grep -q . && has_agents=true
fi
if [[ -d ".claude/skills" ]]; then
    while IFS= read -r -d '' skill; do
        if grep -qiE '(ALWAYS invoke|orchestrator|do NOT inline)' "$skill" 2>/dev/null; then
            has_orchestrator=true
            break
        fi
    done < <(find ".claude/skills" -maxdepth 2 -name "SKILL.md" -print0 2>/dev/null)
fi

if $has_orchestrator || $has_agents; then
    has_router=false
    if [[ -f ".claude/settings.json" ]]; then
        jq -e '.hooks.UserPromptSubmit' .claude/settings.json >/dev/null 2>&1 && has_router=true
    fi
    if $has_router && [[ -f ".claude/trigger-routes.json" ]]; then
        pass "Auto-delegation router installed (Step 7b)"
    else
        warn "Orchestrator/agents present but no UserPromptSubmit trigger router — see references/trigger-router-template.md (Step 7b)"
    fi
fi

# ── 7. CLAUDE.md pointer invariant (sync B) ────────────────
echo ""
echo "--- CLAUDE.md Pointer (sync B) ---"

if [[ -f "CLAUDE.md" ]]; then
    claude_trimmed=$(tr -d '[:space:]' < CLAUDE.md)
    if [[ "$claude_trimmed" == "@AGENTS.md" ]]; then
        pass "CLAUDE.md is exactly '@AGENTS.md'"
    else
        fail "CLAUDE.md is not a pure '@AGENTS.md' pointer — maintenance routine B will flag drift"
    fi
fi

# ── 8. Skills symlink invariant (sync E) ───────────────────
echo ""
echo "--- .agents/skills Symlink (sync E) ---"

if [[ -L ".agents/skills" ]]; then
    link_target=$(readlink ".agents/skills")
    if [[ "$link_target" == "../.claude/skills" ]]; then
        pass ".agents/skills → ../.claude/skills"
    else
        fail ".agents/skills points to '$link_target' (expected ../.claude/skills)"
    fi
elif [[ -f ".agents/skills" && ! -L ".agents/skills" ]]; then
    if [[ "$(cat .agents/skills)" == "../.claude/skills" ]]; then
        pass ".agents/skills → ../.claude/skills (git text-symlink; Windows core.symlinks=false)"
    else
        fail ".agents/skills exists as a file but content is not '../.claude/skills'"
    fi
elif [[ -e ".agents/skills" ]]; then
    fail ".agents/skills exists but is not a symlink or git text-symlink"
else
    warn ".agents/skills missing — maintenance routine E will create it on next run"
fi

# ── 9. backlog.md schema (sync D-1) ────────────────────────
echo ""
echo "--- backlog.md Schema (sync D-1) ---"

if [[ -f "backlog.md" ]]; then
    backlog_heading=false
    backlog_checkbox=false
    backlog_bad_box=false
    while IFS= read -r line; do
        [[ "$line" =~ ^##[[:space:]] ]] && backlog_heading=true
        if [[ "$line" =~ ^[[:space:]]*-[[:space:]]+\[ ]]; then
            if [[ "$line" =~ ^[[:space:]]*-[[:space:]]+\[[\ x\>]\] ]]; then
                backlog_checkbox=true
            else
                backlog_bad_box=true
            fi
        fi
    done < backlog.md

    $backlog_heading && pass "backlog.md has at least one ## heading" \
                     || warn "backlog.md has no ## headings"
    $backlog_checkbox && pass "backlog.md uses standard checkbox items [ ]/[>]/[x]" \
                      || warn "backlog.md has no checkbox items yet (empty backlog is OK)"
    $backlog_bad_box && fail "backlog.md contains non-standard checkboxes (only [ ], [>], [x] allowed)" \
                     || true
else
    warn "backlog.md missing — create via references/backlog-template.md"
fi

# ── 10. AGENTS.md Maintenance section (edit policy) ────────
echo ""
echo "--- AGENTS.md Maintenance Section ---"

if [[ -f "AGENTS.md" ]]; then
    if $has_maintenance; then
        if [[ $maint_rule_count -ge 4 ]]; then
            pass "AGENTS.md ## Maintenance has $maint_rule_count numbered rules (edit policy embedded)"
        else
            warn "AGENTS.md ## Maintenance has only $maint_rule_count rules (expected ≥4 from edit policy)"
        fi
    else
        fail "AGENTS.md missing ## Maintenance section — sync A edit policy not internalized"
    fi
fi

# ── Maturity Level Assessment ─────────────────────────────────
echo ""
echo "--- Maturity Level ---"

# Level 1: docs exist + CLAUDE.md pointer + backlog schema
level1=true
[[ -f "AGENTS.md" && -f "CLAUDE.md" ]] || level1=false
[[ -f "docs/architecture.md" && -f "docs/runbook.md" ]] || level1=false
[[ -f "backlog.md" ]] || level1=false
if [[ -f "CLAUDE.md" ]]; then
    claude_trimmed2=$(tr -d '[:space:]' < CLAUDE.md)
    [[ "$claude_trimmed2" == "@AGENTS.md" ]] || level1=false
fi

# Level 2: Level 1 + CI + reference integrity + delegation has objective triggers
level2=false
if $level1; then
    has_ci=false
    [[ -d ".github/workflows" || -f ".gitlab-ci.yml" || -f ".circleci/config.yml" ]] && has_ci=true
    has_refs=true
    [[ -f "docs/delegation.md" ]] || has_refs=false
    $has_ci && $has_refs && level2=true
fi

# Level 3: Level 2 + PostToolUse hooks + pre-commit or git hooks + drift detection
level3=false
if $level2; then
    has_hooks=false
    has_precommit=false
    if [[ -f ".claude/settings.json" ]]; then
        jq -e '.hooks | (has("PostToolUse") or has("PreToolUse"))' .claude/settings.json >/dev/null 2>&1 && has_hooks=true
    fi
    [[ -f ".pre-commit-config.yaml" \
       || ( -f ".husky/pre-commit" && -x ".husky/pre-commit" ) \
       || ( -f ".git/hooks/pre-commit" && -x ".git/hooks/pre-commit" ) ]] && has_precommit=true
    $has_hooks && $has_precommit && level3=true
fi

# Downgrade all levels if hard failures found
[[ $FAIL -gt 0 ]] && { level1=false; level2=false; level3=false; }

if $level3; then
    echo -e "  ${GREEN}LEVEL 3 — Enforced${NC}  (hooks + CI + drift detection active)"
    echo -e "  ${GREEN}✓${NC} Upgrade path: complete"
elif $level2; then
    echo -e "  ${YELLOW}LEVEL 2 — Verified${NC}  (CI active, hooks missing)"
    echo -e "  ${YELLOW}→${NC} To reach Level 3: add PostToolUse hooks + pre-commit hooks"
elif $level1; then
    echo -e "  ${YELLOW}LEVEL 1 — Basic${NC}  (docs present, no CI enforcement)"
    echo -e "  ${YELLOW}→${NC} To reach Level 2: add CI workflow + docs/delegation.md with objective triggers"
else
    echo -e "  ${RED}LEVEL 0 — Not initialized${NC}"
    echo -e "  ${RED}→${NC} Run harness-init to reach Level 1"
fi

# ── Summary ─────────────────────────────────────────────────
echo ""
echo "=== Summary ==="
echo -e "  ${GREEN}PASS: $PASS${NC}  ${YELLOW}WARN: $WARN${NC}  ${RED}FAIL: $FAIL${NC}"

if [[ $FAIL -gt 0 ]]; then
    echo -e "  ${RED}Harness incomplete — fix FAIL items before proceeding${NC}"
    exit 1
elif [[ $WARN -gt 0 ]]; then
    echo -e "  ${YELLOW}Harness functional but has gaps — consider addressing WARN items${NC}"
    exit 0
else
    echo -e "  ${GREEN}Harness complete${NC}"
    exit 0
fi
