# 작업 로그

## 날짜

2026-05-17

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미정

## 작업 목적

- runtime tool 노출 정책을 보완한다.
- 제거된 browser/web 추출 계열 도구가 기존 DB 설정이나 코드 잔재 때문에 다시 모델에게 노출되지 않도록 한다.

## 변경 요약

- 알 수 없는 runtime toolset 이 들어와도 실행 전체가 깨지지 않도록 빈 tool 목록으로 처리했다.
- 기존 DB/settings 에 남은 `browser` toolset 을 제거하는 Postgres migration 을 추가했다.
- native runtime registry 와 별개로 남아 있던 `web_runtime.registry` 레거시 파일과 self-register 코드를 제거했다.
- runtime tool availability 진단 함수를 추가해, 숨겨진 도구와 env 요구사항을 확인할 수 있게 했다.

## 주요 파일

- `ai/app/tools/runtime/toolsets.py`
- `ai/app/tools/runtime/registry.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/tools/web_runtime/web_tools.py`
- `ai/app/storage/postgres/migrations.py`
- `ai/tests/tools/test_runtime_tools.py`
- `ai/tests/storage/test_postgres_durable_contracts.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\tools\test_runtime_tools.py AI\tests\storage\test_postgres_durable_contracts.py AI\tests\test_model_loop_contract.py AI\tests\api\test_ws_commands.py::test_ws_main_agent_skill_keeps_default_local_toolsets`
- `AI\.venv\Scripts\python.exe -m compileall AI\app\tools\runtime AI\app\tools\web_runtime AI\app\storage AI\app\domain\orchestration`

## 결정 / 이슈

- 도구별 `check_fn` 결과에 따라 실제 사용 가능한 tool schema만 모델에게 노출한다.
- 선언된 도구와 실제 실행 가능 상태를 분리해서 확인할 수 있도록 availability 진단 surface 를 추가했다.
- browser backend 는 현 제품 범위에서 운영하지 않으므로 fallback stub 없이 제거 방향을 유지한다.

## 다음 단계

- skill prompt 주입 단계에서 실제 사용 가능한 tool/toolset 기준으로 skill 설명을 필터링하는 보완이 남아 있다.
- 단순 생활정보 요청은 별도 budget/fast-path 정책을 이어서 조정해야 한다.
