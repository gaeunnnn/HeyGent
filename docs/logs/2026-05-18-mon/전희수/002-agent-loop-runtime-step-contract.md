# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-K-Skills
- PR: 미정

## 작업 목적

- agent loop가 사용자 가시 StepRun을 모델의 `step` 도구 호출에 의존하지 않도록 실행 anchor를 서버가 먼저 만들게 한다.
- 작업 종료 상태를 `work_disposition` 도구가 아니라 최종 assistant 응답의 `workDisposition` 계약으로 반영한다.
- 단순 실행에서 불필요한 LLM memory recall planner 호출을 기본 비활성화해 호출 수를 줄인다.

## 변경 요약

- TaskRun 시작 시 runtime-owned StepRun을 먼저 생성하고, tool/worker/session-agent 이벤트를 같은 StepRun에 누적하게 했다.
- assistant 응답의 `progressUpdate`, `workDisposition`, `text` envelope를 provider 공통 계약으로 파싱한다.
- `step` runtime tool과 `work_disposition` runtime tool 등록, toolset 노출, local handler를 제거했다.
- prompt는 진행 상태를 `progressUpdate`로, 작업 종료 상태를 `workDisposition`으로 남기도록 바꿨다.
- LLM memory recall planner는 `HEYGENT_MEMORY_RECALL_LLM_PLANNER_ENABLED=true`일 때만 켜지게 했다.
- 테스트 fixture에 남아 있던 fake `step` tool call도 제거해 새 실행 계약만 검증하게 했다.
- 기본 제공 에이전트 실호출에서 parent 실행 중 child 완료 wake가 추가 parent TaskRun을 만들 수 있는 흐름을 확인했고, `session_agent_task` root work를 parent TaskRun active run으로 연결해 중복 wake를 막았다.

## 주요 파일

- `ai/app/domain/orchestration/agent/loop.py`
- `ai/app/domain/orchestration/agent/tool_calling_loop.py`
- `ai/app/domain/providers/model/base.py`
- `ai/app/domain/providers/model/gemini_api.py`
- `ai/app/tools/runtime/toolsets.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/tools/planning/step_tool.py`
- `ai/app/tools/work/session_agent_tool.py`
- `ai/tests/api/test_tasks_runtime.py`
- `ai/tests/api/test_ws_commands.py`
- `ai/tests/tools/test_runtime_tools.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest ai/tests/test_model_loop_contract.py ai/tests/tools/test_runtime_tools.py ai/tests/domain/test_work_service.py ai/tests/domain/test_skill_driven_work_tracking.py ai/tests/api/test_tasks_runtime.py ai/tests/api/test_memory_context.py ai/tests/core/test_config.py -q`
- 결과: 171 passed
- 추가 확인: `ai/tests/api/test_ws_commands.py::test_ws_list_snapshot_and_replay_happy_path`, `ai/tests/api/test_ws_commands.py::test_ws_session_agent_task_child_taskrun_can_be_subscribed_snapshotted_and_replayed` 통과
- 추가 확인: `AI\.venv\Scripts\python.exe -m pytest ai/tests/api/test_tasks_runtime.py -q`
- 결과: 45 passed
- 추가 확인: `AI\.venv\Scripts\python.exe -m pytest ai/tests/api/test_tasks_runtime.py ai/tests/providers/test_openai_provider.py ai/tests/providers/test_gemini_provider.py ai/tests/tools/test_runtime_tools.py -q`
- 결과: 95 passed
- 추가 확인: `AI\.venv\Scripts\python.exe -m pytest ai/tests/test_model_loop_contract.py ai/tests/tools/test_runtime_tools.py ai/tests/domain/test_work_service.py ai/tests/domain/test_skill_driven_work_tracking.py ai/tests/api/test_tasks_runtime.py ai/tests/api/test_memory_context.py ai/tests/core/test_config.py ai/tests/providers/test_openai_provider.py ai/tests/providers/test_gemini_provider.py -q`
- 결과: 184 passed
- 실환경 확인: 개발용 테스트 로그인 후 기본 제공 에이전트 새 세션에서 `부산 기상 관련 일주일 소식을 조사하고 나한테 말해줘` 1회 전송
- 실환경 결과: K-에이전트 child work는 호출됐고, StepRun은 각 TaskRun당 1개 runtime-owned anchor로 생성됐다.
- 실환경 이슈: OpenAI hosted web search가 429 재시도에 걸렸고, child 완료 후 parent wake가 추가 TaskRun을 만들었다. 이 로그를 바탕으로 parent active run 연결 패치를 추가했다.

## 결정 / 이슈

- 새 실행 경로에서는 StepRun을 모델 tool 선언으로 만들지 않는다.
- `workDisposition`이 없는 완료 run은 기존처럼 작업 상태를 추측하지 않고 확인 요청 경로로 보낸다.
- `session_agent_task`가 만든 root work는 현재 parent TaskRun이 실행 중인 동안 active run을 유지해야 한다. 그래야 child 완료 wake가 parent 중복 실행으로 번지지 않는다.
- `ai/tests/api/test_ws_commands.py` 전체 실행에는 기존 orphaned running guard 관련 실패가 남아 있다. 이번 변경 범위와 직접 관련 있는 snapshot/session-agent 테스트는 별도 통과 확인했다.

## 다음 단계

- hosted web search 429가 같은 run에서 반복될 때 즉시 circuit breaker로 검색 재시도를 줄인다.
- 모델 health check가 반복적으로 `/v1/models`를 호출하는 경로를 캐시하거나 실행 중복을 줄인다.
