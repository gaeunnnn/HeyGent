# 작업 로그

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-refactor/pipeline-AI
- PR: 없음

## 작업 목적

- 김상지 계정의 토큰 상태가 세션 목록 혼선과 관련 있는지 EC2 Redis/Postgres 기준으로 확인한다.

## 변경 요약

- 코드 변경은 하지 않았다.
- access token, refresh token, bridge token, provider token 저장 구조를 확인했다.
- 김상지 계정은 DB에서 `user_id=3`, Kakao id `4889054134`로 확인했다.

## 주요 파일

- `backend/src/main/java/com/ssafy/heygent/domain/auth/service/AuthService.java`
- `backend/src/main/java/com/ssafy/heygent/global/config/jwt/JwtProvider.java`

## 테스트 / 확인

- access token:
  - 30분 만료 JWT이며 서버 DB/Redis에 저장하지 않는다.
  - 따라서 서버 저장소만으로 김상지 access token 개수를 직접 열거할 수 없다.
- refresh token:
  - 로그인 시 UUID refresh token을 Redis key로 저장하고 value는 user id로 저장한다.
  - 현재 Redis에서 `value=3`인 refresh-token-like string key는 0개였다.
  - 다른 user id 1~6도 현재 같은 방식의 refresh-token-like key는 0개였다.
- WebSocket 연결 registry:
  - 현재 AI Redis registry에 user 1 연결 1개, user 3 연결 1개가 살아 있었다.
- bridge token:
  - 김상지(user 3)의 `bridge_devices` 행은 0개였다.
- OpenAI provider credential:
  - 김상지(user 3)는 `openai_api_key` 연결 1개가 있었다.
  - encrypted access token은 존재하고 refresh token은 없었다.
- `provider_tokens` 테이블:
  - 현재 행 0개였다.

## 결정 / 이슈

- 김상지 계정에 현재 여러 refresh token이 남아 있는 증거는 없다.
- access token은 stateless JWT라 저장소에 남지 않으므로 과거에 몇 개 발급됐는지는 현재 DB/Redis만으로 확인할 수 없다.
- 다만 user 1과 user 3의 WebSocket 연결이 동시에 살아 있어, 앞선 세션 혼선은 “김상지 토큰이 여러 개라서”라기보다 브라우저/탭/재연결 중 인증 사용자가 달라진 흐름으로 보는 것이 더 타당하다.

## 다음 단계

- 재현 시 브라우저의 현재 사용자 id와 `POST /ai/api/v1/sessions`로 생성된 세션의 `owner_user_id`를 즉시 대조한다.
- 필요하면 access token 검증 로그에 user id와 request path만 남기는 임시 진단 로그를 추가한다. 토큰 원문은 기록하지 않는다.
