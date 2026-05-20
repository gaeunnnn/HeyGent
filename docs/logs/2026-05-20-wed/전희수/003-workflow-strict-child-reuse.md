# 작업 로그

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미생성

## 작업 목적

- 워크플로우 실행이 팀장 root WorkItem에 묶이고, 실행 중 새 child WorkItem을 만들지 않도록 강제한다.
- 시각화 페이지와 IoT 구현은 제외하고, AI 실행 계약과 워크플로우 실행 프론트만 검증한다.

## 변경 요약

- workflow instantiate 응답을 `rootWorkId`, `childWorkIds`, `childrenBySlotKey`, `children` 계약으로 변경했다.
- `session_agent_task` strict workflow 모드에서 기존 child WorkItem만 선택 실행하도록 막았다.
- child TaskRun input/event에 workflow context를 전달하도록 했다.
- workflow child TaskRun이 성공하면 child WorkItem은 부모가 소비할 중간 산출물이므로 `done`으로 닫도록 정리했다.
- 워크플로우 실행 버튼에서 `sendMessage`에 root `workId`와 strict workflow payload를 넣도록 수정했다.
- 기본 제공 에이전트 fallback과 `default` 템플릿 예외를 정리했다.

## 주요 파일

- `ai/app/api/http/workflow_templates.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/domain/orchestration/agent/loop.py`
- `frontend/src/components/sessionWorkspace/work/board/WorkflowTemplateEditor.tsx`
- `frontend/src/utils/workflowRunPayload.ts`
- `tmp/workflow/2026-05-20-workflow-parent-child-manual-run-log.md`

## 테스트 / 확인

- `python -m pytest tests/tools/test_runtime_tools.py tests/api/test_workflow_templates.py tests/domain/test_skill_driven_work_tracking.py`
- `npm run lint`
- `npm run build`
- `node src/utils/workflowRunPayload.test.mjs`
- Docker compose로 AI/backend/frontend 재기동 후 워크플로우 페이지에서 실제 실행 1회 검증

## 결정 / 이슈

- legacy flat `workIds` 응답은 남기지 않는다.
- child TaskRun은 유지하되, workflow child는 root 아래 기존 WorkItem 실행으로만 취급한다.
- 선행 child WorkItem이 `in_review`여도 최신 TaskRun이 `COMPLETED`이고 active run이 없으면 다음 child 실행을 허용한다.
- 후속 정리로 workflow child 성공 결과는 `in_review`가 아니라 `done`으로 정규화한다.
- 웹 시각화와 FCM/IoT 알림 정책은 이번 구현에서 수정하지 않고 후속 범위로 남겼다.

## 다음 단계

- 웹 TaskRun 시각화 페이지에서 workflow child TaskRun을 top-level 대표 실행으로 보여주지 않는지 별도 검증한다.
- FCM/웹 알림과 IoT 표시를 root 중심 정책으로 맞출지 후속 설계한다.
