# 작업 로그

## 날짜

2026-05-17

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미정

## 작업 목적

- AI 런타임에서 과거 사용자 요청이 다음 대화 turn의 실행 지시처럼 다시 해석될 수 있는 구조를 줄입니다.
- 단순 조사 요청이 불필요하게 확장되어 병목으로 이어지는 원인을 분리해, 후속 실패 반복 차단 작업의 기준을 마련합니다.

## 변경 요약

- 공개 대화 history를 provider native `user` / `assistant` message 배열로 그대로 재주입하던 방식을 중단했습니다.
- 과거 대화는 단일 user message 안의 `conversation_history` 참고 블록으로 낮추고, 실제 실행 대상은 `current_turn` 블록으로 명시했습니다.
- 오래된 첫 user 요청을 별도 보호하는 압축 경로를 제거하고, history는 요약과 최신 tail 중심으로 유지하도록 정리했습니다.
- 관련 단위 테스트를 새 정책 기준으로 갱신했습니다.

## 주요 파일

- `ai/app/domain/orchestration/prompts/prompt_builder.py`
- `ai/app/domain/session/history_compaction.py`
- `ai/tests/test_model_loop_contract.py`
- `ai/tests/domain/session/test_conversation_history.py`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\test_model_loop_contract.py AI\tests\domain\session\test_conversation_history.py`
- 결과: 35 passed

## 결정 / 이슈

- 과거 대화는 삭제하지 않고 참고 맥락으로 유지하되, 실행 후보로 보이지 않게 강등합니다.
- 이번 변경은 과거 요청 재실행 위험을 줄이는 1차 작업입니다.
- 동일 tool 실패, 429, unavailable tool 반복 호출은 별도 runtime failure state와 circuit breaker로 막아야 합니다.

## 다음 단계

- run-local failure ledger를 추가해 동일 tool + 동일 args + 동일 실패 유형 반복을 runtime 실행 전에 차단합니다.
- 429/rate-limit을 일반 실패와 분리해 같은 run 안에서 즉시 재시도 루프에 빠지지 않게 합니다.
- 실제 부산 기상 요청 smoke에서 호출 횟수, 실패 유형, 종료 시간을 다시 기록합니다.
