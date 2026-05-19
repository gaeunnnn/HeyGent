# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-K-Skills
- PR: 미생성

## 작업 목적

- 단일 사용자 요청에서 동일 작업이 여러 TaskRun 또는 WorkItem으로 증폭되는 문제를 줄인다.
- 직접 실행 TaskRun과 supervisor queue 실행 TaskRun의 소유권을 분리한다.
- 같은 턴에서 같은 `session_agent_task`가 반복 호출될 때 child work와 child TaskRun이 중복 실행되지 않게 한다.

## 변경 요약

- direct 실행 전용 TaskRun 생성 경로를 추가하고, supervisor claim 및 stale recovery 대상에서 제외했다.
- `run_claimed()`는 supervisor가 이미 claim한 작업만 실행하도록 계약을 검증한다.
- `session_agent_task` child TaskRun을 direct 실행으로 저장하고, deterministic `client_request_id`로 같은 턴의 중복 child work 생성을 막았다.
- 이미 생성된 child work가 재사용될 때 executor를 다시 호출하지 않도록 `startExecution=false` 경로를 추가했다.
- public session message 기반 실행 입력에 `prompt_message_id`를 포함해 같은 사용자 턴을 안정적으로 식별하도록 했다.

## 주요 파일

- `ai/app/domain/tasks/repository/contracts.py`
- `ai/app/storage/postgres/durable_repository.py`
- `ai/app/storage/redis/projecting_repository.py`
- `ai/app/domain/orchestration/agent/loop.py`
- `ai/app/domain/orchestration/agent/tool_calling_loop.py`
- `ai/app/domain/orchestration/run_lifecycle.py`
- `ai/app/api/http/sessions.py`
- `ai/app/api/ws/commands.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/tests/domain/test_run_lifecycle.py`
- `ai/tests/domain/test_task_execution_supervisor.py`
- `ai/tests/storage/test_postgres_durable_contracts.py`
- `ai/tests/tools/test_runtime_tools.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\domain\test_run_lifecycle.py AI\tests\storage\test_postgres_durable_contracts.py AI\tests\domain\test_task_execution_supervisor.py AI\tests\tools\test_runtime_tools.py AI\tests\domain\test_skill_driven_work_tracking.py`
  - 결과: 86 passed
- `git diff --check`
  - 결과: 공백 오류 없음
- Docker AI 재빌드 후 ready 확인
  - `GET /ai/api/v1/ready` 정상
- 프론트 개발 로그인 후 기본 제공 에이전트 세션에서 실 호출 1회 확인
  - 프롬프트: `부산 기상 관련 일주일 소식을 조사하고 나한테 말해줘`
  - 결과: 완료 응답 수신
  - TaskRun: root 1개, child 1개
  - WorkItem: parent 1개, child 1개
  - 동일 요청에서 작업 4개 이상으로 증폭되는 현상은 재현되지 않음
  - OpenAI Responses 로그: 총 23회, 200 응답 14회, 429 응답 9회

## 결정 / 이슈

- 이번 수정으로 TaskRun 실행 경계 중복과 child work 중복 실행은 줄어든 것으로 확인했다.
- 남은 병목은 provider 429와 hosted web search 재시도 쪽에 남아 있다.
- 단일 실 호출 완료까지 약 2분 이상 걸렸으므로, 다음 단계에서는 rate-limit/search circuit breaker 보강이 필요하다.
- `AI\tests\api\test_ws_commands.py::test_ws_session_agent_task_child_taskrun_can_be_subscribed_snapshotted_and_replayed` 단일 테스트는 120초와 240초에서 타임아웃되어 이번 확인 범위에서 완료하지 못했다.

## 다음 단계

- provider/tool 429 circuit breaker를 보강한다.
- 검색 실패 또는 rate limit 발생 시 같은 run 안에서 반복 검색을 차단하는 정책을 추가한다.
- 동일 프롬프트 반복 테스트는 circuit breaker 반영 후 5회 기준으로 다시 측정한다.
