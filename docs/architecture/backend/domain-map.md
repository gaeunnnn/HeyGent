# Backend 도메인 맵

## 개요

백엔드는 Spring Boot 기반 API 서버입니다. 사용자 인증, provider credential, 장기기억, 외부 서비스 연동, IoT/브릿지 기기 관리를 담당합니다.

기준 위치: `backend/src/main/java/com/ssafy/heygent/domain`

## 도메인 구성

### auth / user

역할:
- Kakao 로그인
- 모바일 Kakao 로그인
- 개발용 로그인
- refresh/logout
- 내 프로필 조회/수정

대표 경로:
- `POST /api/v1/auth/kakao`
- `POST /api/v1/auth/kakao/mobile`
- `POST /api/v1/auth/dev-login`
- `POST /api/v1/auth/refresh`
- `POST /api/v1/auth/logout`
- `GET /api/v1/users/me`
- `PATCH /api/v1/users/me`

### ai

역할:
- OpenAI/Gemini provider 연결 상태 관리
- API key 저장/삭제
- 사용 가능한 모델 목록 조회
- AI 서버가 사용할 credential 발급
- AI command usage 저장/조회

대표 경로:
- `GET /api/v1/ai/providers`
- `GET /api/v1/ai/providers/models`
- `POST /api/v1/ai/providers/{providerName}/api-key`
- `DELETE /api/v1/ai/providers/{providerName}/api-key`
- `GET /api/v1/ai/usages/me/commands`
- `POST /internal/ai/credentials/issue`
- `POST /internal/ai/auth/validate`

### memory

역할:
- 사용자 장기기억 저장
- 기억 후보 저장
- recall 조회
- 기억 이벤트 조회
- 사용된 기억 표시

대표 경로:
- `POST /api/v1/memories`
- `POST /api/v1/memories/candidates`
- `GET /api/v1/memories`
- `GET /api/v1/memories/recall`
- `GET /api/v1/memories/{memoryId}/events`
- `POST /api/v1/memories/{memoryId}/used`
- `GET /internal/ai/memories/recall`
- `POST /internal/ai/memories/candidates`

### integrations

역할:
- Notion, Gmail, Mattermost 같은 외부 서비스 연결
- OAuth 연결 URL과 상태 조회
- AI 내부 도구 실행용 API 제공

대표 경로:
- `GET /api/v1/notion/connect-url`
- `GET /api/v1/notion/status`
- `POST /api/v1/notion/execute`
- `GET /api/v1/gmail/connect-url`
- `POST /api/v1/gmail/execute`
- `GET /api/v1/mattermost/channels`
- `POST /api/v1/mattermost/messages`
- `POST /internal/ai/notion/execute`
- `POST /internal/ai/gmail/execute`
- `POST /internal/ai/mattermost/messages`

### bridge

역할:
- 로컬 브릿지 페어링
- 사용자별 브릿지 기기 조회/해제
- 브릿지 내부 인증 검증

대표 경로:
- `POST /api/v1/bridge/pairing`
- `GET /api/v1/bridge/devices`
- `DELETE /api/v1/bridge/devices/{deviceId}`
- `POST /internal/bridge/auth/validate`

### iot

역할:
- IoT 기기 등록/조회/삭제
- 페어링 시작과 상태 조회
- MQTT display event 발행
- 기기 interaction 처리

대표 경로:
- `POST /api/v1/iot/devices`
- `GET /api/v1/iot/devices`
- `POST /api/v1/iot/devices/pair`
- `PATCH /api/v1/iot/devices/{deviceId}/status`
- `POST /api/v1/iot/display/events`
- `POST /api/v1/iot/pairing/start`
- `POST /internal/iot/display/events`

### health

역할:
- Samsung Health 기반 모바일 건강 데이터 저장
- 사용자 최신 건강 요약 조회

대표 경로:
- `GET /api/v1/health/me/latest`
- `POST /api/v1/health/samsung`

### building

역할:
- 내 사무실/건물 페이지에서 층과 세션 매핑 관리

대표 경로:
- `GET /api/v1/building/mappings`
- `PUT /api/v1/building/mappings/{floor}`
- `DELETE /api/v1/building/mappings/{floor}`

## 공통 계층

- `global/config`: security, Swagger, Redis, CORS 등 공통 설정
- `global/exception`: 공통 응답과 예외 처리
- `global/security`: 인증 필터와 내부 API 인증
- `global/dto`: 공통 응답 DTO
