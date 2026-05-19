# 작업 로그

## 날짜

2026-05-19

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Health-agent
- PR: 없음

## 작업 목적

- AI 서버의 active TaskRun(사용자 요청 실행 묶음) 조회가 Postgres `run_anchors` 전체 JSON payload를 반복 로드하지 않도록 최적화합니다.
- 프론트 polling 주기는 변경하지 않고 서버 조회 비용만 줄입니다.

## 변경 요약

- `count_tasks_by_statuses`를 전체 TaskRun 로드 후 Python count 방식에서 SQL `COUNT(*)` 방식으로 변경했습니다.
- `list_tasks_by_statuses`가 `run_anchors` 전체를 `SELECT *`로 읽지 않고, status/session/owner 조건을 SQL `WHERE`로 내려 필요한 row와 column만 읽도록 변경했습니다.
- WebSocket `taskRuns.active.list`와 HTTP active 조회에서 인증 owner 필터를 repository 호출까지 전달하도록 변경했습니다.
- stale direct run은 복구 정책은 유지하되, WebSocket active 목록에는 노출하지 않도록 보정했습니다.
- 회귀 테스트에 SQL 전체 로드 방지와 owner filter 전달 검증을 추가했습니다.

## 주요 파일

- `ai/app/storage/postgres/durable_repository.py`
- `ai/app/api/ws/commands.py`
- `ai/app/api/http/tasks.py`
- `ai/app/domain/tasks/repository/contracts.py`
- `ai/tests/storage/test_postgres_durable_contracts.py`
- `ai/tests/api/test_ws_commands.py`
- `ai/tests/fakes.py`

## 테스트 / 확인

- `python -m py_compile`로 수정 Python 파일 컴파일 확인
- `pytest tests/domain/test_run_lifecycle.py tests/storage/test_postgres_durable_contracts.py ...active list 관련 테스트`
- 실제 Docker AI 서버 rebuild 후 `/ai/api/v1/health` 확인
- 실제 세션 메시지 생성 요청으로 기본 세션 에이전트 seed 확인
- HTTP `/taskRuns/active?sessionId=...` 조회 확인
- WebSocket `taskRuns.active.list` 요청 확인
- `EXPLAIN`으로 active 조회 SQL이 `owner_key`, `session_key`, `queue_status` 조건을 포함하고, seqscan 비활성화 시 `idx_run_anchors_active_owner_session` 인덱스를 탈 수 있음을 확인

## 결정 / 이슈

- 프론트 polling 주기는 실시간 복구 동작에 영향을 줄 수 있어 변경하지 않았습니다.
- 실제 모델 응답은 backend AI credential 발급이 400을 반환해 실패했지만, 이번 수정 범위인 세션 생성, 기본 에이전트 seed, active 조회 경로는 확인했습니다.

## 다음 단계

- 운영 데이터에서 `pg_stat_statements` 또는 컨테이너 네트워크 사용량으로 `run_anchors` payload 반복 전송 감소를 확인합니다.
