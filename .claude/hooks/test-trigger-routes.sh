#!/usr/bin/env bash
# Regression gate for trigger-routes.json. Seeded from skill-audit findings.
# Each case: "<expected>|<prompt>" where <expected> is a substring that MUST
# appear in the router instruction, or "NONE" if the router must stay silent.
# Usage: bash .claude/hooks/test-trigger-routes.sh
set -u
ROOT=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
ROUTER="${ROOT}/.claude/hooks/trigger-router.sh"

CASES=(
  # --- skill-dev-orchestrator: implement fires, trivial typo skips ---
  "skill-dev-orchestrator|이거 구현해줘"
  "skill-dev-orchestrator|implement backlog item 3"
  "NONE|오타 한 줄만 고쳐줘"
  "NONE|fix this one-line typo"
  # --- dev-review-cycle: merge-intent fires, review-only skips ---
  "dev-review-cycle|리뷰 사이클 돌려줘"
  "dev-review-cycle|review and merge this branch"
  "dev-review-cycle|run review"
  "dev-review-cycle|리뷰 머지 해줘"
  "NONE|can you review this PR"
  "NONE|review only, do not merge"
  # --- orchestrate: fan-out fires ---
  "orchestrate|fan out agents"
  "orchestrate|delegate this across agents"
  "orchestrate|write a workflow for this"
  # --- harness-init: setup/validate fires, not curator ---
  "harness-init|set up a harness"
  "harness-init|validate harness"
  "harness-init|하네스 초기화 해줘"
  # --- harness-curator: transcript mining fires; generic over-fire stays silent ---
  "harness-curator|analyze my conversation history for skill candidates"
  "harness-curator|대화 기록 분석해서 뭘 스킬로 만들지 봐줘"
  "NONE|이 스킬 코드 분석해줘"
  "NONE|스킬 성능 분석 좀"
  # --- skill-evaluator: quality fires; improve-loop defers to loop-engineer ---
  "skill-evaluator|audit all skills for quality"
  "skill-evaluator|assess this skill"
  # --- loop-engineer: iterative-improve fires (incl. collision phrase) ---
  "loop-engineer|evaluate and improve this skill iteratively"
  "loop-engineer|keep improving until good"
  "loop-engineer|run eval loop on this agent"
  "loop-engineer|만족스러울 때까지 고쳐줘"
  # --- dependabot ---
  "dependabot-manager|too many dependabot PRs"
  "dependabot-manager|clean up dependency update PRs"
  "NONE|@dependabot rebase"
  # --- hwpx: doc task fires; product-talk skips ---
  "hwpx|hwpx 만들어줘"
  "hwpx|공문 작성해줘"
  "NONE|hancom is slow these days"
  # --- JSON-escaping guard: prompt with embedded double-quotes must still route ---
  'hwpx|"긴급" 공문 작성해줘'
)

pass=0; fail=0
run() { jq -nc --arg p "$1" '{prompt:$p, session_id:"t"}' | bash "$ROUTER" 2>/dev/null; }

for c in "${CASES[@]}"; do
  expected="${c%%|*}"; prompt="${c#*|}"
  out=$(run "$prompt")
  if [[ "$expected" == "NONE" ]]; then
    if [[ -z "$out" ]]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL (expected NONE, fired): $prompt"; echo "  -> $out"; fi
  else
    if [[ "$out" == *"$expected"* ]]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL (expected '$expected'): $prompt"; echo "  -> ${out:-<silent>}"; fi
  fi
done

# --- persona-debate adversarial eval (from skill's own trigger-eval.json) ---
EVAL="${ROOT}/productivity/skills/persona-debate/evals/trigger-eval.json"
if [[ -f "$EVAL" ]]; then
  n=$(jq 'length' "$EVAL")
  for ((i=0; i<n; i++)); do
    q=$(jq -r ".[$i].query" "$EVAL")
    want=$(jq -r ".[$i].should_trigger" "$EVAL")
    out=$(run "$q")
    fired="false"; [[ "$out" == *"persona-debate"* ]] && fired="true"
    if [[ "$fired" == "$want" ]]; then pass=$((pass+1)); else fail=$((fail+1)); echo "FAIL persona-debate (want trigger=$want got=$fired): ${q:0:60}..."; fi
  done
fi

echo "----"
echo "PASS=$pass FAIL=$fail"
[[ "$fail" -eq 0 ]] && { echo "✅ all green"; exit 0; } || { echo "❌ failures"; exit 1; }
