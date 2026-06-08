#!/usr/bin/env bash
# tools/sweep.sh — Harness garbage collection for agent-toolkit
# Usage:
#   bash tools/sweep.sh          # full sweep
#   bash tools/sweep.sh --quick  # lint scan only

set -euo pipefail

TOOLS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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

echo -e "${CYAN}=== Sweep: agent-toolkit ===${NC}"
echo -e "  Date: $(date '+%Y-%m-%d %H:%M')"

# ── 1. Lint scan ─────────────────────────────────────────────
echo -e "${CYAN}[1/5] Lint scan...${NC}"

# Shell scripts: check for bare $var without visible capture
UNCAPTURED=()
while IFS= read -r hit; do
    UNCAPTURED+=("$hit")
done < <(
    grep -rn '\$[A-Z_]\{3,\}' \
        --include='*.sh' --include='*.md' \
        --exclude-dir='.git' \
        "$PROJ_DIR" 2>/dev/null |
    grep -v '^Binary' |
    grep -v '# CORRECT\|# WRONG\|SCREAMING_SNAKE\|ROUTES_FILE\|MAX_LINES\|BASH_OUTPUT' |
    head -20 || true
)
if [[ ${#UNCAPTURED[@]} -gt 0 ]]; then
    FINDINGS+=("[lint] $((${#UNCAPTURED[@]})) potential capture-before-use refs — review manually")
    echo -e "  ${YELLOW}WARN${NC} ${#UNCAPTURED[@]} potential uncaptured var refs (manual review needed)"
else
    echo -e "  ${GREEN}OK${NC}"
fi

$QUICK_MODE && { echo "Quick mode — done."; exit 0; }

# ── 2. Doc drift check ──────────────────────────────────────
echo -e "${CYAN}[2/5] Doc drift...${NC}"
RECENT_SKILLS=""
while IFS= read -r _line; do
    [[ -n "$_line" ]] && RECENT_SKILLS+="$_line"$'\n'
done < <(git log --since="7 days ago" --name-only --pretty=format: 2>/dev/null | grep 'skills/.*/SKILL\.md' | sort -u || true)

if [[ -n "$RECENT_SKILLS" ]]; then
    SKILL_COUNT=$(printf '%s' "$RECENT_SKILLS" | grep -c . || true)
    echo -e "  ${YELLOW}INFO${NC} $SKILL_COUNT SKILL.md modified in last 7 days — verify version bumped"
    FINDINGS+=("[doc] $SKILL_COUNT SKILL.md recently modified — confirm plugin.json version bump")
else
    echo -e "  ${GREEN}No recent skill changes${NC}"
fi

# ── 3. Golden principle spot-check ───────────────────────────
echo -e "${CYAN}[3/5] Golden principles...${NC}"

# Check: any file under dev-tools/ or productivity/ changed vs main, but plugin.json unchanged
DEVTOOLS_CHANGED=$(git diff main -- dev-tools/ 2>/dev/null | grep -c '^+\|^-' || true)
if [[ "$DEVTOOLS_CHANGED" -gt 0 ]]; then
    BUMP=$(git diff main -- dev-tools/.claude-plugin/plugin.json 2>/dev/null | grep '^\+.*"version"' | wc -l | tr -d ' ' || true)
    if [[ "$BUMP" -eq 0 ]]; then
        FINDINGS+=("[constraint] VIOLATION: dev-tools/ changed vs main but plugin.json version not bumped")
        echo -e "  ${RED}FAIL${NC} dev-tools/ changed but plugin.json not bumped (vs main)"
    else
        echo -e "  ${GREEN}OK${NC} dev-tools version bumped"
    fi
fi

PRODUCTIVITY_CHANGED=$(git diff main -- productivity/ 2>/dev/null | grep -c '^+\|^-' || true)
if [[ "$PRODUCTIVITY_CHANGED" -gt 0 ]]; then
    BUMP=$(git diff main -- productivity/.claude-plugin/plugin.json 2>/dev/null | grep '^\+.*"version"' | wc -l | tr -d ' ' || true)
    if [[ "$BUMP" -eq 0 ]]; then
        FINDINGS+=("[constraint] VIOLATION: productivity/ changed vs main but plugin.json version not bumped")
        echo -e "  ${RED}FAIL${NC} productivity/ changed but plugin.json not bumped (vs main)"
    else
        echo -e "  ${GREEN}OK${NC} productivity version bumped"
    fi
fi

[[ "$DEVTOOLS_CHANGED" -eq 0 && "$PRODUCTIVITY_CHANGED" -eq 0 ]] && echo -e "  ${GREEN}No plugin changes vs main${NC}"

# ── 4. Harness freshness ────────────────────────────────────
echo -e "${CYAN}[4/5] Harness freshness...${NC}"
AGENTS_LINES=$(wc -l < "$PROJ_DIR/AGENTS.md" 2>/dev/null || echo 0)
if [[ "$AGENTS_LINES" -gt 200 ]]; then
    FINDINGS+=("[harness] AGENTS.md > 200 lines ($AGENTS_LINES) — trim or move to docs/")
    echo -e "  ${RED}FAIL${NC} AGENTS.md too large: $AGENTS_LINES lines (limit 200)"
elif [[ "$AGENTS_LINES" -gt 100 ]]; then
    echo -e "  ${YELLOW}WARN${NC} AGENTS.md $AGENTS_LINES lines (target ≤100)"
else
    echo -e "  ${GREEN}OK${NC} AGENTS.md $AGENTS_LINES lines"
fi

# ── 5. Findings report ──────────────────────────────────────
echo -e "${CYAN}[5/5] Report${NC}"
if [[ ${#FINDINGS[@]} -eq 0 ]]; then
    echo -e "  ${GREEN}Clean — no findings${NC}"
else
    echo -e "  ${YELLOW}Findings (${#FINDINGS[@]}):${NC}"
    for f in "${FINDINGS[@]}"; do
        echo "  - $f"
    done
fi

echo ""
echo -e "${CYAN}=== Done ===${NC}"
[[ ${#FINDINGS[@]} -eq 0 ]] && exit 0 || exit 1
