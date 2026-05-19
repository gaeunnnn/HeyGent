# 작업 로그

## 날짜

2026-05-15

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-skills
- PR: 미생성

## 작업 목적

- 프로토타입 프리뷰가 오른쪽 패널 폭을 채우지 못하고 300px 수준으로 좁게 렌더링되는 문제를 수정한다.
- 기존 프로토타입에 대한 후속 채팅 수정 요청이 실제 Artifact 코드를 읽고 새 버전을 저장할 수 있게 한다.

## 변경 요약

- Sandpack 내부 `.sp-layout`, `.sp-preview`, iframe의 기본 폭을 패널 폭으로 강제해 프리뷰가 가로 폭을 모두 사용하도록 수정했다.
- Sandpack 기본 HTML에 `html`, `body`, `#root` margin/width reset을 추가했다.
- 프로토타입 런타임에 `prototype.get_active_artifact` 도구를 추가해 현재 세션 활성 Artifact 파일을 읽을 수 있게 했다.
- `awesome-design` 스킬 지침에 기존 프로토타입 수정 시 `prototype.get_active_artifact` 후 `prototype.create_artifact`로 새 버전을 저장하도록 명시했다.
- Sandpack 기본 의존성에 `framer-motion`, `clsx`, `date-fns`를 추가하고, Tailwind className 의존 대신 실제 CSS를 생성하도록 스킬 지침을 보강했다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`
- `ai/app/tools/prototype/prototype_tool.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/tools/runtime/toolsets.py`
- `ai/app/skills/design/awesome-design/SKILL.md`
- `ai/tests/tools/test_prototype_runtime_tool.py`

## 테스트 / 확인

- `npx eslint src/components/prototype/PrototypePanel.tsx`
- `npm run build`
- `python -m pytest ai\tests\tools\test_prototype_runtime_tool.py ai\tests\tools\test_design_runtime_tool.py -q`
- `python -m pytest ai\tests\domain\test_capability_resolver.py ai\tests\domain\test_skill_driven_work_tracking.py -q`
- Playwright로 프리뷰 tabpanel, Sandpack layout, iframe 폭이 모두 691px로 일치하는지 확인했다.
- 실제 채팅에서 기존 부산 날씨 프로토타입 수정 요청을 보내 `prototype.get_active_artifact`, `skills.read`, `design.list_presets`, `design.read_preset`, `prototype.create_artifact` 호출 및 v3 저장을 확인했다.
- `docker compose up -d --build ai frontend`로 AI/프론트 컨테이너를 재빌드했다.

## 결정 / 이슈

- 이전 일부 채팅 기록은 Artifact ID를 답변에 언급했지만 실제 `skills.read`, `design.read_preset`, `prototype.create_artifact` 호출 없이 설명형 응답만 반환한 케이스였다.
- 후속 수정은 이제 세션 Artifact를 직접 읽을 수 있으나, 모델이 로컬 파일 도구를 시도하면 브릿지 미연결 오류가 날 수 있다. 스킬 지침은 Artifact 도구 우선 사용으로 보강했다.

## 다음 단계

- 새 프로토타입 생성 요청에서도 Tailwind className만 생성하지 않고 CSS 파일에 디자인 토큰을 구체화하는지 계속 관찰한다.
- 필요하면 `prototype.get_active_artifact` 결과 크기 제한과 대형 파일 분할 읽기 전략을 추가한다.
