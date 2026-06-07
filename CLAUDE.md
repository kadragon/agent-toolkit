# skills

## Release

- 두 플러그인: `dev-tools/` (개발), `productivity/` (생산성). 수정한 플러그인의 `.claude-plugin/plugin.json` `version` 필드 — 머지 전 bump 필수. 안 하면 marketplace 미반영.
- semver: skill/agent 추가 → minor, 수정 → patch, 제거/개명 → major.

## Skill doc 작성 규칙

- 쉘 명령 패턴에서 변수 사용 시 capture 단계 명시: `var=$(cmd)` → (조건 체크) → `$var` 사용. 할당 없이 `$var` 참조하면 에이전트가 단계를 생략하거나 임의 해석함.
