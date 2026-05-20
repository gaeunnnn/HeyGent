# 작업 로그

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-refactor/pipeline-AI
- PR: 미정

## 작업 목적

- 시각화 말풍선 현재 작업 제목에 `agent loop 실행`, `도구 실행`, `작업 진행 중` 같은 내부/임시 문구가 노출되는 문제를 정리한다.
- 말풍선은 `summary_message`나 프론트 하드코딩 fallback이 아니라 실제 `StepRun.title`을 기준으로 표시한다.

## 변경 요약

- AI planner가 `agent.loop` TaskRun/StepRun을 만들 때 내부 handler title보다 `workContext.title`, `workTitle`, `title`, `prompt` 순서의 사용자용 제목을 먼저 사용하도록 변경했다.
- StepRun 최초 생성 이벤트의 `stepTitle`도 위 제목을 따라가므로, 진행 시작 직후 realtime placeholder가 `agent loop 실행`으로 잡히지 않는다.
- 프론트 realtime placeholder title 추론에서 `summary_message`, `goal`, `도구 실행`, `자료 확인`, `답변 진행 단계` fallback을 제거했다.
- 프론트 현재 작업 말풍선은 active StepRun의 `title`이 있을 때만 그 값을 그대로 사용한다.
- `agent loop` 문자열을 프론트에서 필터링해 숨기는 방식은 남기지 않았다.
- TaskRun이 아직 `RUNNING`/`WAITING`/`BLOCKED`이면 `step.completed`로 active StepRun이 잠깐 비어도 직전 StepRun 말풍선을 유지한다.
- 다음 active StepRun이 시작되면 새 StepRun title로 교체하고, TaskRun 자체가 terminal이 될 때만 말풍선을 내린다.
- 동일한 agent info/currentTask 갱신은 store에서 무시해 같은 말풍선이 반복 fade-in 되는 현상을 줄였다.

## 주요 파일

- `ai/app/domain/orchestration/runtime_planning/planner.py`
- `ai/tests/test_task_plan.py`
- `ai/tests/api/test_tasks_runtime.py`
- `frontend/src/hooks/useAgentInfoSync.ts`
- `frontend/src/store/useTaskRunStore.ts`
- `frontend/src/store/useAgentVisualizationStore.ts`
- `frontend/src/utils/agentCurrentTask.ts`
- `frontend/src/utils/taskRunStatusView.test.mjs`

## 테스트 / 확인

- `python -m pytest ai\tests\test_task_plan.py -q` 통과
- `python -m pytest ai\tests\test_model_loop_contract.py -q` 통과
- `node frontend\src\utils\taskRunStatusView.test.mjs` 통과
- `npm run lint` 통과
- `npm run build` 통과
- `python -m pytest ai\tests\api\test_tasks_runtime.py -q`는 현재 memory recall planner가 `_patch_respond` mock 응답을 먼저 소비하는 문제로 다수 실패한다. 이번 변경과 직접 관련된 기존 기대값은 `agent loop 실행`에서 사용자용 StepRun title로 수정했다.

## 결정 / 이슈

- `summary_message`는 진행 설명/이벤트 로그 성격으로 유지하고, 말풍선 제목 소스로 쓰지 않는다.
- 하드코딩으로 `agent loop`를 숨기지 않는다. 새 실행에서 내부명이 보이면 백엔드 StepRun title 생성 또는 이벤트 payload 문제로 다시 추적한다.
- prompt만 있는 일반 실행은 work title이 없으므로 초기 StepRun title이 prompt 축약값이 될 수 있다.
- 말풍선은 StepRun 단위 종료 이벤트가 아니라 TaskRun terminal 상태를 기준으로 내린다. 이 사이 공백 구간에서는 이전 StepRun title을 유지한다.

## 다음 단계

- AI 컨테이너를 재빌드한 뒤 워크플로우를 1회 실행해 `step.created`/`step.started` payload의 `stepTitle`과 시각화 말풍선을 같이 확인한다.
