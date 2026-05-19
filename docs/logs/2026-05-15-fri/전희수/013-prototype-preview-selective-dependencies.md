# 프로토타입 프리뷰 선택적 의존성 로딩

- 날짜: 2026-05-15
- 작성자: 전희수
- 관련 브랜치 또는 PR: AI-feat/Agent-skills
- 작업 목적: 프로토타입 프리뷰가 모든 지원 패키지를 매번 로딩하면서 Sandpack 초기 렌더링이 과도하게 느려지는 문제를 줄인다.

## 변경 요약

- 프론트 패키지 설치 목록은 유지하되, Sandpack preview에는 생성 코드가 실제로 import한 패키지만 전달하도록 변경했다.
- React와 ReactDOM은 core dependency로 항상 포함하고, 나머지는 `/src` 코드의 import/export/require/dynamic import를 스캔해 선택한다.
- `recharts`는 `react-is`, `@react-three/drei`와 `@react-three/fiber`는 `three` 같은 연동 의존성을 함께 포함하도록 했다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`

## 테스트 또는 확인 내용

- `npm run build` (`frontend`)
- `python -m pytest ai/tests/tools/test_design_runtime_tool.py ai/tests/tools/test_prototype_runtime_tool.py ai/tests/domain/test_capability_resolver.py`
- `docker compose up -d --build frontend`
- 실제 부산 날씨 프로토타입 세션(`session_cc29904c645b42c39a0652fa8677d896`)을 다시 열어 Sandpack iframe 본문에 `대한민국 기상청 지역 예보 서비스`가 약 9초 안에 렌더링되고 콘솔 에러가 없는 것을 확인했다.

## 결정, 이슈, 리스크

- 많은 패키지를 설치해두는 것과 매번 프리뷰에 모두 로딩하는 것은 다르다. 설치 목록은 넓게 유지하되, 프리뷰 로딩은 실제 import 기반으로 좁힌다.
- import 문자열을 정적으로 스캔하는 방식이므로, 완전 동적 문자열로 패키지를 조립하는 코드는 감지하지 못한다. 프로토타입 생성 코드는 일반적인 정적 import를 쓰도록 유지한다.

## 다음 단계

- 자주 쓰는 패키지 중 peer dependency가 추가로 드러나면 `PROTOTYPE_LINKED_DEPENDENCIES`에 보강한다.
