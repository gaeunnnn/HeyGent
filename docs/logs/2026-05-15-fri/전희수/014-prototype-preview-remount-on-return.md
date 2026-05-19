# 프로토타입 프리뷰 복귀 시 재마운트 보강

- 날짜: 2026-05-15
- 작성자: 전희수
- 관련 브랜치 또는 PR: AI-feat/Agent-skills
- 작업 목적: 코드 탭이나 다른 화면을 오간 뒤 프로토타입 Preview가 검은 빈 화면처럼 남는 Sandpack stale iframe 상태를 줄인다.

## 변경 요약

- Preview 탭으로 다시 진입하거나 페이지/브라우저 포커스가 돌아올 때 SandpackProvider를 새 key로 재마운트하도록 했다.
- 기존 `runSandpack()` 재시도는 유지하되, iframe 실행 상태가 꼬인 경우 provider 자체를 다시 만들 수 있게 했다.
- 같은 artifact version이라도 컴포넌트 mount마다 다른 provider key를 쓰도록 해 이전 Sandpack iframe 인스턴스가 재사용되지 않게 했다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`

## 테스트 또는 확인 내용

- `npm run build` (`frontend`)
- `python -m pytest ai/tests/tools/test_design_runtime_tool.py ai/tests/tools/test_prototype_runtime_tool.py ai/tests/domain/test_capability_resolver.py`
- `docker compose up -d --build frontend`
- 실제 부산 날씨 프로토타입 세션에서 Code 탭, 다른 화면 이동, 세션 복귀, Preview 탭 전환 흐름을 확인했다.

## 결정, 이슈, 리스크

- Sandpack iframe 내부 DOM은 생성되어도 사용자의 화면에서는 검은 빈 preview로 남는 stale 상태가 발생할 수 있다.
- provider 재마운트는 preview 복구에 유리하지만, 포커스 복귀 시 preview가 한 번 다시 로딩될 수 있다.

## 다음 단계

- 같은 현상이 계속 보이면 preview iframe 상태를 UI에서 감지할 수 있는 별도 timeout/복구 버튼을 추가한다.
