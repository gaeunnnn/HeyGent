# 프로토타입 ZIP 다운로드 추가

- 날짜: 2026-05-18
- 작성자: 전희수
- 관련 브랜치 또는 PR: AI-fix/model-RPM-set
- 작업 목적: 생성된 프로토타입 artifact를 preview 패널에서 바로 ZIP 파일로 내려받을 수 있게 한다.

## 변경 요약

- 프로토타입 preview/code 탭 상단의 버전 표시 옆에 ZIP 다운로드 아이콘 버튼을 추가했다.
- 현재 Sandpack 파일 묶음(`package.json`, `index.html`, `src/*`)을 브라우저에서 ZIP으로 생성해 내려받도록 했다.
- 추가 npm 의존성 없이 무압축 ZIP 생성 유틸을 프론트 내부에 구현했다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`

## 테스트 또는 확인 내용

- `docker compose -f compose.yml exec -T frontend npx eslint src/components/prototype/PrototypePanel.tsx`: 통과
- `docker compose -f compose.yml up -d --build frontend`: 성공
- Playwright에서 기존 테스트 세션 `session_b03e182941944037aa0839b0a30f73d7`의 프로토타입 패널을 열고 `프로토타입 ZIP 다운로드` 버튼 노출을 확인했다.
- 다운로드된 `개발자-포트폴리오-첫-화면-v1.zip`을 저장한 뒤 `Expand-Archive`로 압축 해제를 확인했다.
- 압축 해제 결과 `package.json`, `index.html`, `src/App.tsx`, `src/index.tsx`, `src/main.tsx`, `src/styles.css`가 포함됐다.

## 결정, 이슈, 리스크

- 별도 다운로드 API를 추가하지 않고, 프론트가 이미 받은 artifact 파일을 ZIP으로 묶는 방식으로 범위를 줄였다.
- 전체 `npm run build`는 기존 `src/App.tsx(316,20): Cannot find namespace 'JSX'` 오류에서 중단되어 이번 변경 파일 단위 lint와 브라우저 동작으로 검증했다.

## 다음 단계

- 전체 프론트 build 검증을 통과시키려면 기존 `src/App.tsx`의 `JSX` namespace 타입 오류를 별도 수정해야 한다.
