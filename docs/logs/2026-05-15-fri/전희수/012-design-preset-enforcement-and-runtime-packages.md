# 디자인 프리셋 강제 및 프로토타입 런타임 패키지 확장

- 날짜: 2026-05-15
- 작성자: 전희수
- 관련 브랜치 또는 PR: AI-feat/Agent-skills
- 작업 목적: DESIGN.md 기반 프로토타입 생성에서 실제 preset 사용을 강제하고, 프리뷰 런타임에서 사용할 수 있는 UI/시각화 패키지 범위를 넓힌다.

## 변경 요약

- `design.list_presets` 응답에 각 DESIGN.md frontmatter의 `description`을 포함해 모델이 실제 preset 특징을 보고 고를 수 있게 했다.
- `prototype.create_artifact`가 새 프로토타입 저장 시 `designPresetId` 없이 성공하지 않도록 런타임 검증을 추가했다.
- 기존 프로토타입 수정 요청에서는 활성 Artifact의 `designPresetId`를 자동 승계해 후속 수정이 끊기지 않게 했다.
- 기본 도구셋에 `design`, `prototype`을 포함해 세션 기본 상태에서도 디자인 preset 조회와 Artifact 생성 도구를 사용할 수 있게 했다.
- Sandpack 프리뷰 런타임과 프론트 패키지에 Radix UI, d3, three, react-three, gsap, lottie-react, animejs, react-icons, react-is, mapbox-gl, bootstrap 등 프로토타입용 패키지를 추가했다.
- `awesome-design` 스킬 지침에 실제 preset 1개 이상 조회/읽기, `designPresetId` 전달, 기존 preset 승계 규칙을 명시했다.

## 주요 파일

- `ai/app/skills/design/awesome-design/SKILL.md`
- `ai/app/tools/design/design_tool.py`
- `ai/app/tools/prototype/prototype_tool.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/main.py`
- `frontend/src/components/prototype/PrototypePanel.tsx`
- `frontend/package.json`
- `frontend/package-lock.json`
- `ai/tests/tools/test_design_runtime_tool.py`
- `ai/tests/tools/test_prototype_runtime_tool.py`

## 테스트 또는 확인 내용

- `python -m pytest ai/tests/tools/test_design_runtime_tool.py ai/tests/tools/test_prototype_runtime_tool.py ai/tests/domain/test_capability_resolver.py`
- `npm run build` (`frontend`)
- `docker compose up -d --build ai frontend`
- 실제 채팅에서 `AI 고객지원 SaaS 대시보드 디자인해줘. 실제 화면으로 볼 수 있게 React 컴포넌트 프로토타입으로 만들어줘.` 입력 후 `skills.read`, `design.list_presets`, `design.read_preset`, `prototype.create_artifact` 실행 기록과 오른쪽 프로토타입 패널 렌더링을 확인했다.
- Recharts가 Sandpack에서 `react-is`를 요구하는 오류를 확인하고 `react-is`를 추가한 뒤, iframe 본문에 생성된 AssistFlow AI 대시보드 텍스트가 렌더링되는 것을 확인했다.

## 결정, 이슈, 리스크

- `designPresetId`를 JSON schema required로 두면 기존 Artifact 수정 시 preset 승계 전에 스키마 검증에서 막히므로, 스키마에는 강한 설명을 두고 런타임에서 실제 검증한다.
- 프리뷰 패키지 수가 늘어 Sandpack 초기 로딩이 무거워질 수 있다. 대신 사용자가 요청한 디자인/시각화 라이브러리 import 실패 가능성을 낮추는 방향을 택했다.
- Docker 프론트 빌드 중 `camera-controls`가 Node 22 이상을 권장한다는 npm engine warning이 남지만, 설치와 컨테이너 시작은 성공했다.
- Tailwind 빌드 파이프라인에 의존하는 코드는 여전히 지양한다. DESIGN.md 토큰은 실제 CSS로 구현하는 지침을 유지한다.

## 다음 단계

- 프리셋별로 자주 쓰는 폰트/라이브러리 요구가 더 있으면 Sandpack allowlist와 스킬 설명을 추가 보강한다.
