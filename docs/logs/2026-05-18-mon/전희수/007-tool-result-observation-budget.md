# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: `AI-feat/Agent-K-Skills`
- PR: 미정

## 작업 목적

- 큰 tool 실행 결과가 다음 모델 호출, transcript, 진행 이벤트에 원문 그대로 들어가면서 토큰과 지연 시간이 커지는 문제를 줄인다.

## 변경 요약

- 큰 tool 결과는 별도 raw 저장소에 보관하고, 모델이 받는 observation에는 `preview`, `raw_ref`, 크기/만료 metadata만 넣도록 변경했다.
- `tool_result.read` runtime tool을 추가해 모델이 필요한 경우 `raw_ref` 기준으로 원문 일부를 제한된 크기로 다시 읽을 수 있게 했다.
- 기존 `content` 문자열만 replay하던 경로를 제거하고, 작은 결과는 그대로, 큰 결과는 bounded observation JSON으로 일관되게 replay하도록 정리했다.
- skill 기반 실행에서 `tool-result` toolset이 함께 열리도록 capability resolution을 보강했다.

## 주요 파일

- `AI/app/domain/orchestration/agent/tool_calling_loop.py`
- `AI/app/domain/orchestration/agent/tool_result_store.py`
- `AI/app/tools/runtime/tool_result_tool.py`
- `AI/app/tools/runtime/local_tool_runtime.py`
- `AI/app/tools/runtime/toolsets.py`
- `AI/app/domain/orchestration/capabilities.py`
- `AI/tests/test_agent_tool_guard_loop.py`
- `AI/tests/tools/test_runtime_tools.py`
- `AI/tests/domain/test_capability_resolver.py`
- `AI/tests/api/test_ws_commands.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\test_agent_tool_guard_loop.py AI\tests\tools\test_runtime_tools.py AI\tests\domain\test_capability_resolver.py AI\tests\test_model_loop_contract.py AI\tests\api\test_ws_commands.py::test_ws_new_session_message_augments_toolsets_for_enabled_skill -q`
  - 결과: `96 passed`
- `AI\.venv\Scripts\python.exe -m pytest AI\tests\api\test_tasks_runtime.py -q`
  - 결과: `45 passed`
- 위 범위를 합쳐 다시 실행
  - 결과: `145 passed`
- 추가 WS/API 묶음 실행 중 기존 running guard 관련 3개 실패가 확인됐으며, 이번 tool result 변경 경로와는 별도로 추적이 필요하다.
- 프론트에서 동일 부산 기상 요청을 1회 실행했다.
  - 세션: `session_8c6484ae4fc34422aa3fc61a31d33ac9`
  - root task: `task_0e95120269674fecb3a80345d536b996`, 약 `52.7초`
  - child task: `task_cb337f4179fd4aa69d69e700c0736661`, 약 `34.8초`
  - child tool 호출: `http_get` 8회, `tool_result.read` 3회
  - 큰 tool 결과는 transcript에 원문 대신 preview와 `raw_ref`로 저장되는 것을 확인했다.

## 결정 / 이슈

- 원문이 작은 tool 결과는 기존처럼 그대로 모델 observation에 둔다.
- 원문이 큰 tool 결과는 모델/이벤트/transcript에는 bounded preview와 참조 정보만 남긴다.
- raw 저장소 기본 경로는 AI 하위 `tmp/tool-results`이며, 운영 환경에서는 `HEYGENT_TOOL_RESULT_STORE_DIR`로 별도 경로를 지정할 수 있다.
- 이번 실호출에서는 원문 분리로 16만자급 transcript 재주입은 사라졌지만, K-에이전트가 검색과 raw 재조회 범위를 넓히면서 전체 응답 시간은 아직 목표보다 길다.

## 다음 단계

- 단순 생활정보 요청에서 K-에이전트의 검색 query 수와 `tool_result.read` 횟수 예산을 낮춘다.
- child 결과가 이미 사용자 답변으로 충분한 경우 root 재요약을 줄이는 정책을 검토한다.
- raw 저장소의 보존 기간과 정리 주기를 운영 설정으로 분리할지 결정한다.
