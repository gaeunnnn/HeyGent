# 작업 로그

## 날짜

2026-05-15

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-skills
- PR: 미생성

## 작업 목적

- 프로토타입 패널에서 Preview와 Code 탭 내용이 동시에 보이는 문제를 수정합니다.

## 변경 요약

- 탭 전환 시 Sandpack DOM은 유지하되 비활성 탭 콘텐츠는 숨기도록 스타일을 보강했습니다.
- Preview 탭에는 웹사이트 프리뷰만, Code 탭에는 파일 탐색기와 코드 에디터만 보이도록 분리했습니다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`

## 테스트 / 확인

- `npx eslint src/components/prototype/PrototypePanel.tsx`
- `npm run build`

## 결정 / 이슈

- 프리뷰 iframe을 유지하기 위해 `forceMount`는 유지합니다.
- `forceMount`로 DOM이 남더라도 비활성 탭은 `data-state=inactive` 기준으로 숨깁니다.
- Vite 빌드의 대형 chunk 경고는 기존 번들 구성 이슈로 이번 변경과 직접 관련이 없습니다.

## 다음 단계

- 실제 로그인 UI에서 Preview와 Code 탭 전환 시 한쪽 콘텐츠만 보이는지 최종 확인합니다.
