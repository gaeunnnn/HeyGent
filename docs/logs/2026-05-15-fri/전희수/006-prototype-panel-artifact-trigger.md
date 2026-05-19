# 작업 로그

## 날짜

2026-05-15

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-skills
- PR: 미생성

## 작업 목적

- 프로토타입 패널을 사용자 문장 키워드가 아니라 실제 프로토타입 Artifact 생성 결과에 맞춰 열리도록 조정합니다.

## 변경 요약

- 채팅 입력 내용에서 디자인/웹사이트/페이지 키워드를 검사해 패널을 미리 여는 로직을 제거했습니다.
- 답변 실행 중에는 프로토타입 Artifact API를 백그라운드로 확인하고, 실제 Artifact가 확인될 때만 패널을 표시하도록 분리했습니다.
- Artifact가 확인된 시점에 2차 사이드바를 세션당 한 번 접도록 변경했습니다.

## 주요 파일

- `frontend/src/pages/ChatSessionPage.tsx`
- `frontend/src/components/prototype/PrototypePanel.tsx`

## 테스트 / 확인

- `npx eslint src/pages/ChatSessionPage.tsx src/components/prototype/PrototypePanel.tsx`
- `npm run build`
- `python -m pytest ai\tests\tools\test_prototype_runtime_tool.py -q`

## 결정 / 이슈

- 스킬 호출 판단은 AI의 skill description과 runtime tool 흐름에 맡기고, 프론트는 실제 Artifact 존재 여부만 패널 표시 기준으로 삼습니다.
- `npm run lint -- --file ...`은 현재 ESLint 설정에서 지원하지 않는 옵션이라 대상 파일 직접 실행 방식으로 확인했습니다.
- Vite 빌드의 대형 chunk 경고는 기존 번들 구성 이슈로 이번 변경과 직접 관련이 없습니다.

## 다음 단계

- 실제 채팅에서 `prototype.create_artifact` 호출 직후 패널이 뜨는지 UI 흐름을 추가 확인합니다.
