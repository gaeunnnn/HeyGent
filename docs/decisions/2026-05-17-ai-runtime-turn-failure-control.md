# AI 런타임 대화 턴과 실패 반복 제어

## 날짜

2026-05-17

## 상태

채택

## 배경

부산 기상 조사 요청 재현에서 단순 생활 정보성 요청이 긴 agent loop로 확장되는 현상이 확인됐다.
실행 기록상 큐 대기나 Docker 리소스 부족보다는 모델 호출, 검색 429, 사용할 수 없는 도구 호출 실패가 같은 run 안에서 반복되는 쪽이 병목에 가까웠다.

또한 세션의 과거 공개 대화가 다음 실행 입력에 그대로 섞이면, 이미 끝난 사용자 요청이 현재 turn의 실행 지시처럼 다시 해석될 수 있다.

## 결정

AI 런타임은 다음 두 문제를 분리해서 다룬다.

1. 과거 요청 재실행 방지
   - 과거 공개 대화는 실행 지시가 아니라 참고 맥락으로만 전달한다.
   - 현재 실행 대상은 `current_turn`으로 명시한다.
   - 과거 user 메시지를 provider native `user` message 배열로 그대로 재주입하지 않는다.
   - 오래된 첫 user 요청을 별도로 보호하는 history 압축 경로는 두지 않는다.

2. 같은 run 안의 실패 반복 방지
   - 실패 이력은 대화 history가 아니라 runtime state로 관리한다.
   - provider API 실패와 runtime tool 실패는 별도 ledger로 분리한다.
   - 동일 tool, 동일 args, 동일 실패 유형이 반복되면 실제 runtime 호출 전에 차단한다.
   - unknown/unavailable tool은 args가 바뀌어도 tool name 기준 반복을 별도로 감지한다.
   - 429/rate-limit은 일반 실패와 분리해 첫 실패 이후 같은 run에서 즉시 재시도 루프로 빠지지 않게 한다.
   - 차단된 tool call도 provider tool-call 흐름을 깨지 않도록 synthetic tool result를 반환한다.
   - 반복 실패 차단은 `max_iterations_exceeded`가 아니라 명시적인 실패 사유로 종료한다.

## 적용 현황

현재 반영된 내용:

- `conversation_history` 참고 블록과 `current_turn` 실행 블록 분리
- 과거 `user` / `assistant` history의 native message 재주입 제거
- 오래된 head 메시지 보호 경로 제거
- 관련 단위 테스트 추가 및 갱신

후속으로 반영할 내용:

- run-local failure ledger
- unavailable tool / 동일 실패 반복 circuit breaker
- 429/rate-limit error classification
- circuit-open synthetic tool result 포맷
- provider API 실패와 runtime tool 실패 분리
- circuit breaker 적용 후 실제 부산 기상 요청 재측정

## 테스트 기준

- 과거 부산 기상 요청이 다음 요약/분석 turn에서 다시 tool call을 만들지 않아야 한다.
- 새 turn은 이전 tool transcript를 replay하지 않아야 하고, resume/approval 재개는 기존 replay 흐름을 유지해야 한다.
- 같은 unavailable tool 또는 같은 429 search call은 정책 threshold 이후 실제 runtime 호출을 반복하지 않아야 한다.
- 429/rate-limit은 threshold 반복을 기다리지 않고 같은 run 동일 signature 재호출을 차단해야 한다.
- unknown/unavailable tool은 args가 바뀌어도 같은 tool name 반복으로 감지되어야 한다.
- 반복 실패로 종료할 때는 `max_iterations_exceeded`까지 끌지 않고 명시적인 blocked 또는 실패 응답으로 끝나야 한다.

## 제외 범위

- 다중 credential pool 전체
- provider 자동 fallback chain
- cross-session persistent rate-limit guard
- 외부 서버 단위 circuit breaker 전체
- generic repeat를 즉시 hard block하는 정책

## 관련 문서

- `docs/logs/2026-05-17-sun/전희수/005-ai-current-turn-history-boundary.md`
