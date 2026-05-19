# 작업 로그

## 날짜

2026-05-15

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-skills
- PR: 미생성

## 작업 목적

- 프로토타입 프리뷰가 실제 iframe 화면을 렌더링한 뒤에도 Sandpack 기본 로딩 오버레이에 가려져 검은 화면처럼 보이는 문제를 해소합니다.

## 변경 요약

- `SandpackPreview` 기본 컴포넌트 대신 Sandpack client 기반의 직접 iframe 프리뷰를 구성했습니다.
- 프리뷰 로딩 상태를 iframe `onLoad`, Sandpack `start/done` 메시지, 제한 시간 fallback으로 직접 제어하도록 변경했습니다.
- 화면 복귀 시 focus/pageshow마다 provider를 재마운트하던 로직을 제거해 흰색 번쩍임과 반복 초기화를 줄였습니다.
- 자동 재실행 타이머를 1회로 축소해 preview/client 상태가 과도하게 재시작되지 않도록 조정했습니다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`

## 테스트 / 확인

- `frontend`에서 `npm run build` 실행 완료
- `frontend`에서 `npm run lint` 실행 완료
- `docker compose -f compose.yml restart frontend`로 프론트 컨테이너 재시작
- Playwright로 기존 프로토타입 세션 재진입 후 기본 `.sp-overlay`가 남지 않고 `Prototype Preview` iframe이 표시되는지 확인
- 다른 화면 이동 후 세션 복귀, Code 탭 전환 후 Preview 복귀 흐름 확인

## 결정 / 이슈

- 조사 결과 iframe 내부 React 화면은 이미 렌더링되어 있었고, Sandpack 기본 `LoadingOverlay`가 `done` 상태로 내려가지 않는 것이 검은 화면의 직접 원인이었습니다.
- Sandpack 런타임의 원격 telemetry 요청 실패와 Recharts 크기 경고는 관측되지만, 프리뷰 표시를 막는 직접 원인은 아니었습니다.

## 다음 단계

- 실제 사용자 입력으로 생성된 신규 프로토타입에서도 같은 방식으로 preview/code 전환과 세션 복귀를 반복 확인합니다.
