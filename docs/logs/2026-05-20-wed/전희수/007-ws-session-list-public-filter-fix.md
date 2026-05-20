# 작업 로그

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-refactor/pipeline-AI
- PR: 없음

## 작업 목적

- WebSocket `session.list` 응답에서 공개 AI 세션이 갑자기 누락되어 프론트 화면에서 사라지는 문제를 재발 방지한다.

## 변경 요약

- WS `session.list`가 `agent.loop` 등 내부 세션을 먼저 10개 가져온 뒤 사후 필터링하던 동작을 수정했다.
- 세션 저장소 목록/카운트 조회에 `source` 필터를 추가하고, Postgres SQL 조건에서 `api.session`만 먼저 필터링한 뒤 `LIMIT/OFFSET`을 적용하도록 했다.
- 내부 세션이 최신 10개 이상 존재해도 공개 세션이 목록에 남는 회귀 테스트를 추가했다.

## 주요 파일

- `ai/app/api/ws/commands.py`
- `ai/app/storage/postgres/session_store.py`
- `ai/app/domain/session/sessions/transcript_store.py`
- `ai/tests/fakes.py`
- `ai/tests/api/test_ws_commands.py`

## 테스트 / 확인

- `pytest ai/tests/api/test_ws_commands.py::test_ws_session_list_filters_public_sessions_before_limit -q`
- `pytest ai/tests/api/test_ws_commands.py::test_ws_list_snapshot_and_replay_happy_path ai/tests/api/test_ws_commands.py::test_ws_session_list_filters_public_sessions_before_limit -q`
- `pytest ai/tests/api/test_ws_commands.py -q -k "session_list or list_snapshot"`
- `pytest ai/tests/api/test_ws_commands.py -q`

## 결정 / 이슈

- 프론트 reconcile이 누락된 세션을 화면에서 제거하는 것은 증상을 드러낸 계기이고, 직접 원인은 WS 목록 응답이 공개 세션을 누락한 것이다.
- 토큰/세션 종속 문제보다는 세션 목록 조회 필터와 limit 순서 문제가 핵심 원인이다.
- 전체 WS 테스트 파일 타임아웃은 session-agent 테스트의 fake model sequence가 memory recall planner 호출에 먼저 소비되는 테스트 안정성 문제였고, 테스트 helper가 planner 호출을 별도 처리하도록 정리했다.

## 다음 단계

- Docker/CI 환경에서도 동일 테스트 파일을 한 번 더 확인한다.
