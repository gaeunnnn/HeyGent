# 작업 로그

## 날짜

2026-05-15

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-skills
- PR: 미생성

## 작업 목적

- 다른 세션이나 페이지로 이동했다가 돌아와도 채팅 실행 상태와 프로토타입 패널 표시가 자연스럽게 복원되도록 보강합니다.

## 변경 요약

- 메시지 재조회 시 기존 streaming/waiting assistant placeholder를 서버 저장 메시지 목록과 병합하도록 수정했습니다.
- user 메시지에 같은 TaskRun ID가 있어도 assistant 진행 placeholder를 추가할 수 있게 조건을 수정했습니다.
- 채팅 화면 재진입 시 live TaskRun이 보이면 assistant 진행 placeholder를 복구하도록 보강했습니다.
- 프로토타입 Preview/Code 탭은 `activeTab` 기준으로 직접 표시/숨김을 제어해 두 탭 내용이 동시에 보이지 않도록 수정했습니다.
- DESIGN.md 스킬 사용 여부 답변은 추정이나 의도 분류가 아니라 실제 도구 호출 결과를 근거로 말하도록 스킬 지침을 보강했습니다.

## 주요 파일

- `frontend/src/store/useChatStore.ts`
- `frontend/src/pages/ChatSessionPage.tsx`
- `frontend/src/components/prototype/PrototypePanel.tsx`
- `ai/app/skills/design/awesome-design/SKILL.md`

## 테스트 / 확인

- `npx eslint src/store/useChatStore.ts src/pages/ChatSessionPage.tsx src/components/prototype/PrototypePanel.tsx`
- `npm run build`
- `node src/utils/taskRunStatusView.test.mjs`
- `python -m pytest ai\tests\tools\test_design_runtime_tool.py ai\tests\tools\test_prototype_runtime_tool.py ai\tests\domain\test_skill_driven_work_tracking.py -q`

## 결정 / 이슈

- 상태 복원은 프론트 의도 분류가 아니라 서버 TaskRun/Artifact 상태와 클라이언트 live placeholder 병합으로 처리합니다.
- 이미 생성된 부산 오늘 예보 Artifact는 DB에 저장되어 있으며, 패널은 해당 세션의 active Artifact 조회로 복원될 수 있습니다.
- Vite 빌드의 대형 chunk 경고는 기존 번들 구성 이슈로 이번 변경과 직접 관련이 없습니다.

## 다음 단계

- 프론트 컨테이너를 새 코드로 재기동한 뒤 실제 UI에서 세션 이동 후 진행 상태와 Preview/Code 탭 표시를 확인합니다.
