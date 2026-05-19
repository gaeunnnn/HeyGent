# 작업 로그

## 날짜

2026-05-17

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-K-Skills
- PR: 미정

## 작업 목적

- 병목 테스트에서 확인된 없는 도구 반복 호출 문제를 줄이기 위해 AI runtime tool surface를 정리한다.
- 실제 실행 가능한 도구만 모델에게 노출하는 정책을 적용한다.

## 변경 요약

- Firecrawl, tool-gateway, browser runtime 계열 코드를 기본 runtime에서 제거했다.
- `web` toolset은 `web_search`, `http_get`만 남겼다.
- `browser` toolset과 `browser_*` schema, dispatcher, worker 기본 toolset, DB seed 참조를 제거했다.
- runtime tool definition에 `check_fn`, `requires_env`, `unavailable_reason`을 추가했다.
- `web_search`는 검색 백엔드 키가 확인될 때만 모델 tool 목록에 노출되도록 변경했다.
- 순차 결정 기록은 로컬 임시 문서에만 남기고 공용 문서에는 결과만 요약한다.

## 주요 파일

- `AI/app/tools/runtime/catalog.py`
- `AI/app/tools/runtime/registry.py`
- `AI/app/tools/runtime/toolsets.py`
- `AI/app/tools/web/web_tools.py`
- `AI/app/tools/web_runtime/web_tools.py`
- `AI/app/domain/orchestration/delegation/delegate_runtime.py`
- `AI/app/domain/orchestration/agent/tool_calling_loop.py`
- `AI/app/domain/orchestration/agent/loop.py`
- `AI/app/storage/postgres/schema.py`
- `AI/app/storage/postgres/migrations.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\tools\test_runtime_tools.py AI\tests\test_model_loop_contract.py AI\tests\test_delegate_runtime_handoff.py AI\tests\storage\test_postgres_durable_contracts.py AI\tests\api\test_ws_commands.py::test_ws_main_agent_skill_keeps_default_local_toolsets`
- `AI\.venv\Scripts\python.exe -m compileall AI\app\tools\runtime AI\app\tools\web AI\app\domain\orchestration AI\app\storage AI\app\main.py`

## 결정 / 이슈

- Firecrawl/tool-gateway와 browser 자동화는 조건부 숨김이 아니라 기본 runtime에서 제거한다.
- `http_get`은 k-skill proxy와 공개 API 직접 조회 경로로 유지한다.
- 전체 `AI\tests\api\test_tasks_runtime.py`는 memory recall planner mock이 provider 응답을 먼저 소비하는 별도 실패가 섞여 이번 변경 검증 범위에서는 제외했다.

## 다음 단계

- `mattermost.send`, `notion.execute` 같은 사용자 연결 기반 외부 서비스 도구에 context-aware gate를 추가한다.
- 동일 run 안에서 반복 실패한 도구와 429/rate-limit에 대한 circuit breaker를 설계한다.
- 유사 tool call/query dedupe 정책을 별도 항목으로 확정한다.
