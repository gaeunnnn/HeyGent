# 작업 로그

## 날짜

2026-05-17

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/tool
- PR: 미정

## 작업 목적

- 같은 실행 안에서 실패한 도구 호출을 무제한 반복하지 않도록 run-local failure circuit breaker를 추가한다.
- 모델 provider 호출 실패와 runtime tool 실패를 분리해서 기록하고, 429나 도구 미가용 같은 재시도 무의미 상황을 빠르게 종료한다.

## 변경 요약

- 도구 실패를 분류하고 같은 실행 안에서 실패 서명을 기록하는 `RunLocalToolFailureCircuit`을 추가했다.
- 실제 도구 실행 전에 circuit 상태를 확인하고, 차단 시 실제 runtime을 다시 호출하지 않고 synthetic tool result를 대화 이력에 남기도록 했다.
- 같은 circuit-open 호출이 반복되면 max iteration까지 기다리지 않고 실패 outcome으로 종료한다.
- provider 429/timeout 계열 실패는 tool result로 섞지 않고 provider failure outcome으로 종료한다.

## 주요 파일

- `AI/app/domain/orchestration/agent/tool_failure_circuit.py`
- `AI/app/domain/orchestration/agent/tool_calling_loop.py`
- `AI/tests/test_agent_tool_guard_loop.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\test_agent_tool_guard_loop.py AI\tests\test_model_loop_contract.py AI\tests\domain\session\test_conversation_history.py`
- `AI\.venv\Scripts\python.exe -m compileall AI\app\domain\orchestration\agent\tool_failure_circuit.py AI\app\domain\orchestration\agent\tool_calling_loop.py`
- `git diff --check`

## 결정 / 이슈

- circuit 상태는 현재 agent.loop 실행 안에서만 유지한다.
- guard rejection과 approval 대기는 circuit 실패로 기록하지 않는다.
- 도구 실패는 tool name과 canonical args hash를 기준으로 차단하고, 도구 미가용 계열은 같은 도구명 기준 반복도 차단한다.
- provider 실패는 도구 실패 ledger에 기록하지 않는다.

## 다음 단계

- 실제 프론트 개발용 테스트 로그인 플로우에서 부산 기상 요청을 재실행해 provider 호출 수와 runtime tool 호출 수가 줄었는지 확인한다.
- 단순 생활정보 요청에는 skill-first 지침과 tool budget 축소를 이어서 적용한다.
