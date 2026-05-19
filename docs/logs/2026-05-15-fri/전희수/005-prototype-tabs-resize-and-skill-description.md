# 프로토타입 탭/리사이즈 및 스킬 설명 보강

- 날짜: 2026-05-15
- 작성자: 전희수
- 관련 브랜치 또는 PR: 로컬 작업 브랜치

## 작업 목적

- 프로토타입 패널의 Preview/Code 탭이 라이트 모드에서도 잘 보이게 한다.
- Code 탭 전환 중 Preview iframe 상태가 사라지지 않게 한다.
- 오른쪽 프로토타입 패널의 좌우 폭을 사용자가 조절할 수 있게 한다.
- 웹사이트/웹페이지/정보성 화면 요청도 DESIGN.md 프로토타입 흐름으로 자연스럽게 들어오게 한다.

## 변경 요약

- Preview/Code 탭 버튼의 활성 상태 배경과 텍스트 색상을 명시했다.
- Preview와 Code 탭 콘텐츠를 강제 마운트해 탭 전환 중 iframe이 언마운트되지 않도록 했다.
- 프로토타입 패널 왼쪽에 드래그 가능한 리사이즈 핸들을 추가했다.
- 채팅의 프로토타입 트리거 키워드에 웹사이트, 웹페이지, 사이트, 페이지를 추가했다.
- DESIGN.md 스킬 설명에 웹사이트/웹페이지/정보성 웹사이트 생성 요청을 포함했다.
- 스킬 결과 보고는 실제 Artifact와 도구 결과를 기준으로 말하도록 지침을 보강했다.

## 주요 파일

- `frontend/src/components/prototype/PrototypePanel.tsx`
- `frontend/src/pages/ChatSessionPage.tsx`
- `ai/app/skills/design/awesome-design/SKILL.md`

## 테스트 또는 확인 내용

- `npx eslint src/components/prototype/PrototypePanel.tsx src/pages/ChatSessionPage.tsx`
- `npm run build`
- `python -m pytest ai\tests\domain\test_capability_resolver.py ai\tests\tools\test_design_runtime_tool.py ai\tests\tools\test_prototype_runtime_tool.py -q`
- `docker compose up -d --build frontend`
- 브라우저에서 Code 탭 전환 중 iframe 유지, Preview 복귀, 패널 리사이즈, 탭 버튼 색상 계산값을 확인했다.

## 결정, 이슈, 리스크

- "부산 기상예보 웹사이트" 같은 요청은 웹사이트 키워드로 프로토타입 패널을 열 수 있다.
- 실제 최신 기상 데이터 수집은 별도 웹 검색/조회 도구 사용 여부에 따라 달라지므로, 프로토타입 저장 경로와 데이터 조회 경로는 분리해서 본다.
- 기존 대화의 Artifact에는 실제 `design_preset_id`가 저장되어 있어, 패널이 뜬 경우에는 Artifact 결과를 근거로 판단해야 한다.

## 다음 단계

- Artifact 상세에 사용된 도구 목록을 저장해 사용자가 "스킬 썼냐"고 물었을 때 더 명확히 확인할 수 있게 한다.
