# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미정

## 작업 목적

- 기본 제공 세션 에이전트가 `gpt-5.2`로 생성된 뒤 backend credential 정책에서 차단되는 문제를 수정합니다.
- SRT 실제 예약 테스트 중 K-agent 실행이 시작 전 실패한 원인을 기록합니다.

## 변경 요약

- backend OpenAI 기본 허용 모델 목록에 `gpt-5.2`를 추가했습니다.
- OpenAI API Key provider와 개발용 fallback provider의 기본 모델 목록에도 `gpt-5.2`를 추가했습니다.
- `gpt-5.2` credential 발급이 허용되는 테스트를 추가했습니다.

## 주요 파일

- `backend/src/main/resources/application.yaml`
- `backend/src/main/java/com/ssafy/heygent/domain/ai/openai/config/OpenAiProperties.java`
- `backend/src/main/java/com/ssafy/heygent/domain/ai/openai/model/OpenAiProviderName.java`
- `backend/src/test/java/com/ssafy/heygent/domain/ai/openai/service/OpenAiCredentialIssueServiceTest.java`

## 테스트 / 확인

- `backend`에서 `./gradlew.bat test --tests com.ssafy.heygent.domain.ai.openai.service.OpenAiCredentialIssueServiceTest` 통과.
- backend 컨테이너를 재빌드/재기동했습니다.
- 내부 credential 발급 API에서 `gpt-5.2` 요청이 `200`으로 통과하는 것을 확인했습니다.

## 결정 / 이슈

- SRT 예약 채팅 요청은 1회만 실행했습니다.
- 해당 요청은 K-agent 모델 호출 전에 `OPENAI_MODEL_NOT_ALLOWED`로 실패했으며, 실제 SRT 예약은 생성되지 않았습니다.
- 사용자 인증 정보 원문은 문서에 기록하지 않았습니다.

## 다음 단계

- 사용자가 재시도를 승인하면 같은 세션 또는 새 세션에서 SRT 실제 예약 요청을 다시 한 번 실행해 K-agent와 `srt-booking` runtime tool까지 이어지는지 확인합니다.
