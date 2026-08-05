#!/bin/bash
# sweep.sh — Automated garbage collection for harness
# Usage:
#   ./tools/sweep.sh              # full sweep
#   ./tools/sweep.sh --quick      # lint only
#
# Copy this file into your project's tools/ directory and adapt
# the sections marked with "# ADAPT:" to your tech stack.

set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJ_DIR="$(cd "$TOOLS_DIR/.." && pwd)"

RED='\033[0;31m'
YELLOW='\033[0;33m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

FINDINGS=()
QUICK_MODE=false
[[ "${1:-}" == "--quick" ]] && QUICK_MODE=true

cd "$PROJ_DIR"

echo -e "${CYAN}=== Sweep ===${NC}"
echo -e "  Date: $(date '+%Y-%m-%d %H:%M')"

# ── 1. Lint scan ─────────────────────────────────────────────
echo -e "${CYAN}[1/5] Lint scan...${NC}"
# ADAPT: Replace with your project's lint command
# Examples:
#   npm run lint 2>&1
#   cargo clippy 2>&1
#   python -m flake8 . 2>&1
#   ./tools/lint.sh --all 2>&1
lint_output=$(echo "No lint configured — adapt this section" 2>&1) || true
# Parse lint output and add to FINDINGS if issues found

$QUICK_MODE && { echo "Quick mode — done."; exit 0; }

# ── 2. Doc drift check ──────────────────────────────────────
echo -e "${CYAN}[2/5] Doc drift...${NC}"
# Check if recently modified source files have corresponding doc updates
recent_files=""
while IFS= read -r _line; do
    [[ -n "$_line" ]] && recent_files+="$_line"$'\n'
done < <(git log --since="24 hours ago" --name-only --pretty=format: 2>/dev/null | sort -u) || true
recent_files="${recent_files%$'\n'}"
if [[ -n "$recent_files" ]]; then
    # ADAPT: Define which source files should have corresponding docs
    # Example: for each modified service file, check if docs/spec/ was updated
    echo -e "  ${GREEN}Checked $(echo "$recent_files" | wc -l) recent file(s)${NC}"
else
    echo -e "  ${GREEN}No recent commits${NC}"
fi

# ── 3. Golden principle spot-check ───────────────────────────
echo -e "${CYAN}[3/5] Golden principles...${NC}"
# ADAPT: Check project-specific golden principles on recently modified files
# Examples:
#   - Check for raw SQL (grep for string concatenation in query files)
#   - Check for missing error handling (grep for empty catch blocks)
#   - Check for hardcoded secrets (grep for API keys, passwords)
#   - Check for missing audit fields (grep INSERT/UPDATE statements)
echo -e "  ${GREEN}Adapt golden principle checks to your project${NC}"

# ── 4. Harness freshness ────────────────────────────────────
echo -e "${CYAN}[4/5] Harness freshness...${NC}"
harness_issues=0

# Check that all files referenced in AGENTS.md exist
if [[ -f "AGENTS.md" ]]; then
    referenced_docs=""
    while IFS= read -r _line; do
        while [[ "$_line" =~ (docs/[a-zA-Z0-9_./-]+\.(md|txt)) ]]; do
            referenced_docs+="${BASH_REMATCH[1]}"$'\n'
            _line="${_line#*"${BASH_REMATCH[0]}"}"
        done
    done < AGENTS.md
    referenced_docs="${referenced_docs%$'\n'}"
    for doc in $referenced_docs; do
        if [[ ! -f "$doc" ]]; then
            FINDINGS+=("[harness] AGENTS.md references missing file: $doc")
            harness_issues=$((harness_issues + 1))
        fi
    done
fi

# Check key docs exist — same two tiers as validate-harness.sh section 1.
# Always required: docs/runbook.md, the one doc whose content (build/test/deploy
# commands, env setup, failure modes) is never inferable from source. Everything
# else is conditional: harness-init generates it only when the repo has the thing
# it documents, so a missing file is a decision, not a defect. Reporting those as
# findings would file backlog items against a correct minimal init.
if [[ ! -f "docs/runbook.md" ]]; then
    FINDINGS+=("[harness] Missing key doc: docs/runbook.md")
    harness_issues=$((harness_issues + 1))
fi

conditional_docs=(
    "docs/architecture.md:generated when the repo has real module boundaries"
    "docs/conventions.md:generated when rules exist that the linter does not own"
    "docs/workflows.md:generated when the repo runs a defined work cycle"
    "docs/eval-criteria.md:generated when the repo runs the Sprint Contract flow"
    "docs/delegation.md:created with the repo's first agent role (see dev:harness-curate)"
)
for entry in "${conditional_docs[@]}"; do
    doc="${entry%%:*}"
    why="${entry#*:}"
    [[ -f "$doc" ]] || echo -e "  INFO  $doc absent — $why"
done

[[ $harness_issues -eq 0 ]] && echo -e "  ${GREEN}All references valid${NC}"

# ── 5. Summary ──────────────────────────────────────────────
echo ""
if [[ ${#FINDINGS[@]} -eq 0 ]]; then
    echo -e "${GREEN}=== Sweep clean ===${NC}"
    exit 0
fi

echo -e "${YELLOW}=== ${#FINDINGS[@]} finding(s) ===${NC}"
for f in "${FINDINGS[@]}"; do echo "  $f"; done

# Append to backlog.md if it exists. NOT tasks.md: sweep findings outlive the sprint that
# happens to be in flight, and tasks.md is deleted whole at sprint close.
if [[ -f "backlog.md" ]]; then
    echo "" >> backlog.md
    echo "## Sweep $(date '+%Y-%m-%d %H:%M')" >> backlog.md
    echo "" >> backlog.md
    for f in "${FINDINGS[@]}"; do
        echo "- [ ] $f" >> backlog.md
    done
    echo -e "${GREEN}Added ${#FINDINGS[@]} item(s) to backlog.md${NC}"
else
    # Never drop findings silently. backlog.md is optional after a minimal init, so its
    # absence is expected -- but then the findings above exist only in this terminal.
    echo -e "${YELLOW}No backlog.md — ${#FINDINGS[@]} finding(s) NOT persisted.${NC}" >&2
    echo -e "${YELLOW}Create backlog.md (harness-init references/backlog-template.md) to capture them.${NC}" >&2
fi

exit 1
