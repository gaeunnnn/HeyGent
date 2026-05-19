# 프로토타입 프리뷰 패널 UX 보강

- 날짜: 2026-05-15
- 작성자: 전희수
- 관련 브랜치 또는 PR: 로컬 작업 브랜치

## 작업 목적

- 프로토타입 렌더링 화면과 코드 화면이 오른쪽 패널 세로 공간을 충분히 사용하도록 한다.
- 라이트 모드에서도 코드 영역이 흰색 배경에 묻히지 않게 한다.
- 프로토타입 패널을 닫은 뒤 접힌 2차 사이드바에서 다시 열 수 있게 한다.

## 변경 요약

- 프로토타입 패널, Preview 탭, Code 탭, 내부 실행 iframe, 코드 에디터의 높이 체인을 `h-full/min-h-0` 기준으로 정리했다.
- Code 탭 내부 파일 탐색기와 코드 에디터 배경/텍스트 색상을 명시해 앱 테마와 무관하게 읽히도록 했다.
- UI 상태 저장소에 세션별 프로토타입 패널 열기 요청 상태를 추가했다.
- 접힌 2차 사이드바 상단에 팔레트 버튼을 추가해 프로토타입 패널을 다시 열 수 있게 했다.
- 디자인 요청 시 2차 사이드바는 세션당 최초 1회만 자동으로 접히도록 조정했다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`
- `frontend/src/components/sessionWorkspace/SessionWorkspaceMenu.tsx`
- `frontend/src/pages/ChatSessionPage.tsx`
- `frontend/src/store/useUIStore.ts`

## 테스트 또는 확인 내용

- `npx eslint src/components/prototype/PrototypePanel.tsx src/pages/ChatSessionPage.tsx src/components/sessionWorkspace/SessionWorkspaceMenu.tsx src/store/useUIStore.ts`
- `npm run build`
- `docker compose up -d --build frontend`
- 브라우저에서 프로토타입 패널 닫기, 접힌 2차 사이드바 팔레트 버튼 표시, 팔레트 버튼 재오픈을 확인했다.
- Code 탭의 탭패널/파일 탐색기/에디터 높이와 배경/텍스트 색상 계산값을 확인했다.

## 결정, 이슈, 리스크

- 프로토타입 패널 닫기는 Artifact를 숨길 뿐 세션의 재오픈 버튼은 유지한다.
- Artifact가 이미 로드된 뒤에는 계속 polling하지 않도록 했다.

## 다음 단계

- 패널 너비 조절이나 전체화면 보기 옵션을 추가할지 결정한다.
