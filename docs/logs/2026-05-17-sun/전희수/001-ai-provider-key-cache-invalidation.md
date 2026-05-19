# 작업 로그

## 날짜

2026-05-17

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-K-Skills
- PR: 미정

## 작업 목적

- provider API key를 새로 저장하거나 삭제해도 AI 런타임이 기존 credential cache를 TTL 동안 계속 사용해 OpenAI 429가 반복될 수 있는 문제를 해결한다.

## 변경 요약

- AI 서버에 내부 credential cache 무효화 API를 추가했다.
- BackendAiClient와 ProviderRegistry에 user/provider/model 기준 credential cache 제거 경로를 추가했다.
- 백엔드 provider key 저장/삭제 트랜잭션 commit 이후 AI 내부 무효화 API를 호출하도록 연결했다.
- AI 내부 호출 실패는 key 저장 성공을 막지 않도록 best-effort로 처리했다.
- cache 무효화 동작과 백엔드 key 저장/삭제 후 호출 여부를 테스트로 보강했다.

## 주요 파일

- `AI/app/api/http/credential_cache_internal.py`
- `AI/app/api/router.py`
- `AI/app/clients/backend_ai.py`
- `AI/app/domain/providers/registry/provider_registry.py`
- `backend/src/main/java/com/ssafy/heygent/domain/ai/openai/client/OpenAiCredentialCacheClient.java`
- `backend/src/main/java/com/ssafy/heygent/domain/ai/openai/service/OpenAiApiKeyService.java`
- `backend/src/main/java/com/ssafy/heygent/global/config/security/AiInternalProperties.java`
- `backend/src/main/resources/application.yaml`
- `AI/tests/api/test_credential_cache_internal.py`
- `AI/tests/clients/test_backend_ai_client.py`
- `backend/src/test/java/com/ssafy/heygent/domain/ai/openai/service/OpenAiApiKeyServiceTest.java`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\clients\test_backend_ai_client.py AI\tests\api\test_credential_cache_internal.py`
- `backend\gradlew.bat test --tests com.ssafy.heygent.domain.ai.openai.service.OpenAiApiKeyServiceTest`
- `docker compose up -d --build backend ai`
- `GET http://localhost:8000/ai/api/v1/ready` 응답 `ready` 확인
- 프론트 개발용 테스트 로그인 후 실제 채팅 `테스트 캐시 확인` 전송, TaskRun 완료 확인
- AI 로그에서 내부 cache 무효화 API 200 응답과 OpenAI Responses API 200 응답 확인

## 결정 / 이슈

- credential cache TTL은 유지하되, provider key 저장/삭제 시점에는 즉시 무효화한다.
- DB commit 전에 cache를 지우면 동시 호출이 이전 DB 값을 다시 cache할 수 있어 afterCommit 이후 호출하도록 했다.
- AI 서버 일시 장애로 cache 무효화 호출이 실패해도 provider key 저장 자체는 실패시키지 않는다.
- 기존 `.gitignore` 변경은 이번 작업 범위가 아니므로 커밋 대상에서 제외한다.

## 다음 단계

- 같은 패턴이 다른 provider credential 저장 경로에도 추가되는지 후속 구현 시 확인한다.
