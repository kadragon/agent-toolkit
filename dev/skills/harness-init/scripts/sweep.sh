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

is_security_finding() {
    [[ "$1" == \[[sS][eE][cC][uU][rR][iI][tT][yY]\]* ]]
}

report_findings() {
    echo ""
    if [[ ${#FINDINGS[@]} -eq 0 ]]; then
        echo -e "${GREEN}=== Sweep clean ===${NC}"
        return 0
    fi

    echo -e "${YELLOW}=== ${#FINDINGS[@]} finding(s) ===${NC}"
    local finding
    for finding in "${FINDINGS[@]}"; do
        if ! is_security_finding "$finding"; then
            printf '  %s\n' "$finding"
        elif ! $QUICK_MODE && [[ -t 2 ]]; then
            printf '  %s\n' "$finding" >&2
        fi
    done
    return 1
}

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

if $QUICK_MODE; then
    report_findings && exit 0
    exit 1
fi

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

# Check key docs exist — the same two tiers validate-harness.sh applies in its
# section 1, with docs/delegation.md folded into the conditional list. That doc
# sits outside section 1 there, where a role-aware check can WARN once the repo
# has roles but no routing doc; sweep has no roster context, so it stays INFO.
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
report_findings && exit 0

QUEUE_BACKEND_SCRIPT="${AGENT_QUEUE_BACKEND_SCRIPT:-$TOOLS_DIR/queue/queue_backend.py}"
if [[ ! -r "$QUEUE_BACKEND_SCRIPT" && -z "${AGENT_QUEUE_BACKEND_SCRIPT:-}" ]]; then
    QUEUE_BACKEND_SCRIPT="$PROJ_DIR/dev/skills/task-next/scripts/queue_backend.py"
fi
if [[ ! -r "$QUEUE_BACKEND_SCRIPT" ]] || ! command -v python3 >/dev/null; then
    echo "Findings were not persisted — install the queue modules with sweep or configure AGENT_QUEUE_BACKEND_SCRIPT and python3." >&2
    exit 1
fi
REPO=$(git rev-parse --show-toplevel) || exit 1

QUEUE_FINDINGS=()
VISIBILITY=""
WITHHELD=0
for f in "${FINDINGS[@]}"; do
    if is_security_finding "$f"; then
        if [[ -z "$VISIBILITY" ]]; then
            REQUEST=$(python3 -c 'import json, sys; print(json.dumps({"contract": 1, "repo": sys.argv[1], "verify_visibility": True}))' "$REPO")
            if DESCRIBE=$(printf '%s\n' "$REQUEST" | python3 "$QUEUE_BACKEND_SCRIPT" describe); then
                VISIBILITY=$(python3 -c '
import json
import sys

description = json.load(sys.stdin)
visibility = description.get("visibility")
if visibility == "unknown" and description.get("backend") != "backlog":
    visibility = "unverified"
print(visibility)
' <<< "$DESCRIBE")
            else
                VISIBILITY=unverified
            fi
        fi
        if [[ "$VISIBILITY" != "private" && "$VISIBILITY" != "unknown" ]]; then
            WITHHELD=$((WITHHELD + 1))
            continue
        fi
    fi
    QUEUE_FINDINGS+=("$f")
done
if [[ "$WITHHELD" -gt 0 ]]; then
    echo "$WITHHELD security finding(s) withheld from the queue." >&2
fi
[[ "$WITHHELD" -lt "${#FINDINGS[@]}" ]] || exit 1

CREATE=$(python3 -c '
import hashlib
import json
import sys

request = {"contract": 1, "repo": sys.argv[1], "queue_limits": sys.argv[2]}
request["items"] = [
    {
        "key": "sweep:" + hashlib.sha256(finding.encode("utf-8")).hexdigest(),
        "title": finding[:256],
        "body": finding,
        "labels": ["security"] if finding.lower().startswith("[security]") else [],
        "refile_completed": True,
    }
    for finding in dict.fromkeys(sys.argv[3:])
]
print(json.dumps(request))
' "$REPO" "${AGENT_QUEUE_LIMITS:-none}" "${QUEUE_FINDINGS[@]}")
RESPONSE=$(printf '%s\n' "$CREATE" | python3 "$QUEUE_BACKEND_SCRIPT" create) || exit 1
EDIT_FILE=$(python3 -c 'import json, sys; print(json.load(sys.stdin).get("edit_file", ""))' <<< "$RESPONSE")
if [[ -z "$EDIT_FILE" ]]; then
    python3 -c '
import json
import sys

result = json.load(sys.stdin)
if result.get("withheld_security"):
    print(result["withheld_security"], "security finding(s) withheld from the queue.", file=sys.stderr)
for issue in result.get("created", []):
    print("Queue issue:", issue["ref"], issue.get("url", ""))
for entry in result.get("incomplete", []):
    print("Incomplete queue item:", entry, file=sys.stderr)
if result.get("error"):
    print(result["error"], file=sys.stderr)
if result.get("pending"):
    print("Pending queue drafts:", ", ".join(result["pending"]), "in", result["pending_path"], file=sys.stderr)
' <<< "$RESPONSE"
    exit 1
fi
if [[ "$EDIT_FILE" != "backlog.md" ]]; then
    echo "Unrecognized queue edit_file response: $EDIT_FILE" >&2
    exit 1
fi

FILE_QUEUE="$REPO/$EDIT_FILE"
if [[ -f "$FILE_QUEUE" ]]; then
    {
        printf '\n## Sweep %s\n\n' "$(date '+%Y-%m-%d %H:%M')"
        printf -- '- [ ] %s\n' "${QUEUE_FINDINGS[@]}"
    } >> "$FILE_QUEUE"
    echo -e "${GREEN}Added ${#QUEUE_FINDINGS[@]} item(s) to backlog.md${NC}"
else
    # Never drop findings silently. backlog.md is optional after a minimal init, so its
    # absence is expected -- but then the findings above exist only in this terminal.
    echo -e "${YELLOW}No backlog.md — ${#QUEUE_FINDINGS[@]} finding(s) NOT persisted.${NC}" >&2
    echo -e "${YELLOW}Create backlog.md (harness-init references/backlog-template.md) to capture them.${NC}" >&2
fi

exit 1
