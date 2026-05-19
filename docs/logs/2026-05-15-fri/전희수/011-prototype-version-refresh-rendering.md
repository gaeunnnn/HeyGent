# 프로토타입 새 버전 갱신 및 프리뷰 렌더링 보강

- 날짜: 2026-05-15
- 작성자: 전희수
- 관련 브랜치 또는 PR: AI-feat/Agent-skills

## 작업 목적

- 기존 프로토타입이 있는 세션에서 사용자가 "밝게 바꿔봐"처럼 후속 수정을 요청하면 새 버전은 저장되지만 오른쪽 프리뷰 패널이 이전 버전에 머무는 문제를 수정한다.
- Sandpack 프리뷰가 흰 화면 또는 런타임 파서 오류로 멈추는 케이스를 줄여 실제 React 프로토타입 화면이 보이도록 한다.

## 변경 요약

- 프로토타입 패널 polling 조건을 수정해 채팅 작업 진행 중에는 기존 artifact가 있어도 active artifact를 다시 조회하도록 변경했다.
- 패널이 단순히 열려 있다는 이유로 계속 polling하지 않고, 실제 채팅 작업 진행 중일 때만 polling하도록 호출부를 조정했다.
- Sandpack 템플릿을 생성 코드 구조에 맞는 React TypeScript 렌더링 흐름으로 조정하고 엔트리 파일을 보강했다.
- Sandpack iframe 시작 타이밍을 보정하는 자동 실행 컴포넌트를 추가했다.
- 일부 생성 코드의 이모지, 온도 기호, 장식 기호가 Sandpack 파서에서 실패하는 케이스를 프리뷰용 코드 정규화로 완화했다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`
- `frontend/src/pages/ChatSessionPage.tsx`

## 테스트 또는 확인 내용

- `npx eslint src/components/prototype/PrototypePanel.tsx src/pages/ChatSessionPage.tsx`
- `npm run build`
- `docker compose up -d --build frontend`
- 개발 로그인 세션에서 실제 채팅 입력 `한 번 더 밝게 바꿔봐. 기존 프로토타입 코드를 읽고 새 버전으로 저장해줘.`를 전송해 v7 artifact 저장을 확인했다.
- 브라우저에서 세션을 다시 열어 오른쪽 프로토타입 패널이 v7로 갱신되고 부산 날씨 React 화면이 실제로 렌더링되는 것을 확인했다.

## 결정, 이슈, 리스크

- Vite 기반 Sandpack 템플릿은 현재 생성 코드와 조합 시 Nodebox 파서 오류가 재현되어 React TypeScript 템플릿으로 전환했다.
- 프리뷰 안정성을 위해 Sandpack에 전달하는 코드에서 일부 특수 시각 기호를 안전한 텍스트로 정규화한다. 원본 artifact 저장 데이터는 변경하지 않는다.
- Sandpack 외부 런타임이 사용하는 telemetry 요청 timeout은 프리뷰 렌더링과 무관하게 발생할 수 있다.

## 다음 단계

- 생성 프롬프트 또는 skill description에서 프로토타입 코드에 파서 민감 기호를 과하게 쓰지 않도록 안내를 강화할지 검토한다.
- 후속 작업에서 프리뷰 코드 복사 시 원본 artifact 코드와 프리뷰 정규화 코드 중 어느 쪽을 보여줄지 제품 정책을 정한다.
