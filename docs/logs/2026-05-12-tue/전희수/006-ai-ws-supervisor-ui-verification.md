# AI WS supervisor UI 검증

- 날짜: 2026-05-12
- 작성자: 전희수
- 관련 브랜치 또는 PR: 로컬 작업 브랜치

## 작업 목적

- `session.message.create` 처리 중 화면은 답변을 받지만 작업 상태가 진행 중으로 남거나 동일 task 실행이 중복되는 문제를 확인하고 수정한다.
- Docker 재빌드 후 실제 프론트 화면에서 새 대화 -> 기본 제공 에이전트 경로를 검증한다.

## 변경 요약

- WebSocket 메시지 생성/재시도 명령이 queue enabled 환경에서 직접 background task를 실행하지 않고 `TaskExecutionSupervisor.submit`으로 durable queue에 등록하도록 조정했다.
- supervisor 완료 콜백 오류가 TaskRun 실행 실패로 전파되지 않도록 분리했다.
- queue supervisor 완료 콜백 실패 회귀 테스트를 추가했다.
- AI env example을 현재 Docker/backend credential 기반 설정에 맞게 정리했다.

## 주요 파일

- `ai/app/api/ws/commands.py`
- `ai/app/domain/orchestration/task_execution_supervisor.py`
- `ai/tests/domain/test_task_execution_supervisor.py`
- `ai/.env.example`

## 테스트 또는 확인 내용

- `python -m py_compile ai/app/domain/orchestration/task_execution_supervisor.py ai/app/api/ws/commands.py`
- `python -m pytest ai/tests/domain/test_task_execution_supervisor.py ai/tests/api/test_ws_commands.py -q`
  - 결과: 21 passed
- `docker compose up -d --build ai`
- 실제 화면 검증:
  - `http://localhost:5173/`에서 새 작업 요청 -> 기본 제공 에이전트 -> 새 채팅 생성
  - 메시지: `콜백 패치 후 검증입니다. OK라고만 답해주세요.`
  - 화면 결과: AI 응답 `OK`, 상태 `답변 완료`
- DB 확인:
  - 신규 `run_anchors` 1건 증가
  - 신규 task `task_99e0f85f3af746a0ae43ec110f2bc81e`
  - `queue_status=terminal`, `durable_status=TERMINAL`, `attempts=1`
  - task event count: `task.created=1`, `task.started=1`, `task.completed=1`
  - 신규 usage record 1건 증가

## 결정, 이슈, 리스크

- listener는 durable queue 등록만 하고 실행 소유권은 queue/supervisor가 갖는 방향으로 맞췄다.
- 서버 공용 OpenAI fallback key는 사용하지 않고 backend provider credential에서 사용자 API key를 발급받는 흐름을 기준으로 검증했다.
- memory planner는 서버 공용 provider 미연결 상태에서 fallback 경고를 남기지만 채팅 완료는 막지 않았다.
- 브릿지 코드는 수정하지 않았다.

## 다음 단계

- 필요 시 memory planner가 backend credential 기반 provider를 쓰도록 별도 이슈로 분리한다.
- 전체 테스트는 기존 pytest 장시간 실행 이슈가 있어 이번 변경 범위의 대상 테스트와 실제 UI 검증으로 제한했다.
