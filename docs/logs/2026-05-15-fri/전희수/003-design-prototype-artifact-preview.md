# DESIGN.md 프로토타입 Artifact 프리뷰

- 날짜: 2026-05-15
- 작성자: 전희수
- 관련 브랜치 또는 PR: 로컬 작업 브랜치

## 작업 목적

- DESIGN.md 스킬 기반 화면 생성 요청이 로컬 브릿지 파일 작업으로 빠지지 않고, 세션에 종속된 프로토타입 Artifact로 저장되도록 한다.
- 사용자가 디자인/화면/프로토타입 요청을 보낼 때 오른쪽 프리뷰 패널에서 React 화면과 코드를 바로 확인할 수 있게 한다.

## 변경 요약

- `prototype.create_artifact` 런타임 도구와 세션별 Artifact 저장/조회 API를 추가했다.
- DESIGN.md 스킬 지침을 React 컴포넌트, CSS, 세션 Artifact 저장 중심으로 보강했다.
- 채팅 화면에서 디자인성 요청이 감지되면 2차 사이드바를 접고 오른쪽 프로토타입 패널을 열도록 연결했다.
- 프리뷰 패널에 Preview/Code 탭을 두고 저장된 React 파일 세트를 실행 렌더링 및 코드 확인에 사용하도록 했다.

## 주요 파일

- `ai/app/tools/prototype/prototype_tool.py`
- `ai/app/storage/postgres/prototype_repository.py`
- `ai/app/api/http/prototypes.py`
- `ai/app/skills/design/awesome-design/SKILL.md`
- `frontend/src/components/prototype/PrototypePanel.tsx`
- `frontend/src/pages/ChatSessionPage.tsx`
- `frontend/src/apis/prototypes.ts`

## 테스트 또는 확인 내용

- `python -m pytest ai\tests\tools\test_prototype_runtime_tool.py ai\tests\api\test_prototype_artifacts.py ai\tests\domain\test_capability_resolver.py ai\tests\tools\test_design_runtime_tool.py ai\tests\domain\test_agent_templates.py -q`
- `npx eslint src/components/prototype/PrototypePanel.tsx src/pages/ChatSessionPage.tsx src/apis/prototypes.ts`
- `npm run build`
- `docker compose up -d --build ai frontend`
- 개발용 테스트 로그인 후 실제 채팅에서 "AI 고객지원 SaaS 대시보드" 프로토타입 요청을 보내 Artifact 저장, 오른쪽 패널 표시, iframe 렌더링을 확인했다.

## 결정, 이슈, 리스크

- 디자인 작업은 브릿지 파일 쓰기가 아니라 세션 Artifact 저장 경로를 기본으로 사용한다.
- 프리뷰 실행 의존성은 원격 패키저가 최신 버전을 잘못 해석하지 않도록 안정 버전으로 고정했다.
- 외부 패키저 네트워크 장애가 있으면 Preview 로딩이 늦어질 수 있으므로, Artifact 저장과 Code 탭은 별도로 유지한다.

## 다음 단계

- Code 탭에서 복사/다운로드 UX를 정리한다.
- 생성 Artifact 버전 목록과 되돌리기 UI를 추가한다.
