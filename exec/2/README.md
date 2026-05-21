# 2. 외부 서비스 정보

HeyGent는 외부 인증, 생성형 AI, 생산성 도구, 모바일 푸시, 헬스 데이터, IoT 표시를 함께 사용합니다. 실제 키와 토큰은 저장소에 포함하지 않습니다.

## 외부 서비스 목록

| 서비스 | 사용 위치 | 용도 | 설정 위치 |
| --- | --- | --- | --- |
| Kakao Developers | Web, Mobile, Backend | 사용자 로그인 | `frontend/.env`, `backend/.env`, `mobile/secrets.properties` |
| OpenAI API | Backend, AI | 에이전트 응답 생성, 임베딩, 장기기억 검색 | `backend/.env`, `ai/.env`, 사용자별 provider credential |
| Composio | Backend | Gmail, Notion OAuth 및 API 프록시 | `backend/.env` |
| Gmail | AI Skill | 뉴스레터 검색, 메일 요약 | Composio Gmail integration |
| Notion | AI Skill | 페이지 생성, 뉴스 정리 저장 | Composio Notion integration |
| Mattermost | AI Skill | 작업 결과 채널 공유 | 사용자별 integration credential |
| Firebase Cloud Messaging | Mobile, Backend | 모바일 작업 완료 알림 | `mobile/app/google-services.json`, backend FCM 설정 |
| Samsung Health | Mobile | 수면, 심박 등 건강 데이터 수집 | Android 권한 및 Samsung Health SDK |
| Eclipse Mosquitto MQTT | Backend, IoT | IoT 디스플레이 상태 전달 | `compose.yml`, `docker/mosquitto` |
| Local Bridge | Bridge, AI | 사용자 PC 파일/터미널 작업 위임 | `bridge/.env`, 웹 페어링 |

## 비민감 기본 설정

로컬 개발 환경은 다음 값을 기준으로 설정합니다. 비밀값 원문은 제출 문서에 포함하지 않습니다.

| 항목 | 확인 값 |
| --- | --- |
| Local Frontend | `http://localhost:5173` |
| Local Backend | `http://localhost:8080` |
| Local AI API | `http://localhost:8000/ai/api/v1` |
| Local AI WebSocket | `ws://localhost:8000/ai/api/v1/realtime/user/ws` |
| Bridge WebSocket | `ws://localhost:8000/ai/api/v1/internal/bridge/ws` |
| PostgreSQL | `jdbc:postgresql://127.0.0.1:5432/heygent` |
| Redis | `redis://redis:6379/0` |
| MQTT | `mosquitto:1883` 또는 로컬 직접 실행 시 `localhost:1883` |
| Mobile 배포 API | `https://k14e105.p.ssafy.io/` |
| Firebase project id | `e105-d54d1` |
| Android package name | `com.example.mob` |

다음 민감값은 각 서비스 콘솔 또는 로컬 환경변수에 설정합니다.

| 항목 | 상태 |
| --- | --- |
| Kakao REST API key / client secret | 설정됨 |
| Kakao Native app key | 설정됨 |
| Composio API key | 설정됨 |
| Gmail / Notion integration id | 설정됨 |
| JWT secret | 설정됨 |
| Backend-AI internal token | 설정됨 |
| OpenAI API key | AI, frontend 개발용, mobile 설정에 존재 |
| OpenAI credential encryption key | 설정됨 |
| Firebase Web config / VAPID key | 설정됨 |
| Bridge token | 설정됨 |

## Kakao 로그인

필요 항목:

- REST API key
- Native app key
- Client secret
- Web redirect URI: `http://localhost:5173/auth/kakao/callback`
- Android key hash

설정 위치:

```env
# frontend/.env
VITE_KAKAO_CLIENT_ID=<kakao-rest-api-key>
VITE_KAKAO_REDIRECT_URI=http://localhost:5173/auth/kakao/callback

# backend/.env
KAKAO_CLIENT_ID=<kakao-rest-api-key>
KAKAO_CLIENT_SECRET=<kakao-client-secret>
KAKAO_REDIRECT_URI=http://localhost:5173/auth/kakao/callback
```

```properties
# mobile/secrets.properties
KAKAO_NATIVE_APP_KEY=<kakao-native-app-key>
```

## OpenAI

사용 목적:

- 에이전트 대화 및 작업 계획
- 장기기억 writeback 판단
- 장기기억 임베딩 생성
- 사용자별 모델 provider credential 저장 및 사용

설정 위치:

```env
OPENAI_API_KEY=<openai-api-key>
MEMORY_EMBEDDING_API_KEY=<openai-api-key>
OPENAI_DEFAULT_MODEL=gpt-5.4
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

AI 서버는 backend에서 검증된 사용자 credential을 받아 사용합니다. 서버 공용 fallback key는 운영상 필요한 경우에만 설정합니다.

장기기억 임베딩을 backend에서 직접 생성하려면 backend 쪽 `MEMORY_EMBEDDING_API_KEY`를 설정합니다. AI 서버에서 fallback key를 사용할 경우 `HEYGENT_OPENAI_API_KEY`를 설정합니다.

## Composio, Gmail, Notion

Composio는 외부 서비스 OAuth와 API 호출을 중계합니다.

필요 항목:

- Composio API key
- Gmail integration id
- Notion integration id
- 각 서비스 redirect URI

설정 위치:

```env
COMPOSIO_API_KEY=<composio-api-key>
COMPOSIO_GMAIL_REDIRECT_URI=http://localhost:5173/auth/gmail/callback
COMPOSIO_GMAIL_INTEGRATION_ID=<composio-gmail-integration-id>
COMPOSIO_NOTION_REDIRECT_URI=http://localhost:5173/auth/notion/callback
COMPOSIO_NOTION_INTEGRATION_ID=<composio-notion-integration-id>
```

시연 기준 사용 흐름:

1. 사용자가 웹에서 Gmail 또는 Notion 연결을 시작합니다.
2. Composio OAuth 화면에서 권한을 승인합니다.
3. backend가 연결 상태와 credential 참조를 저장합니다.
4. AI runtime은 `gmail.execute`, `notion.execute` 도구를 통해 backend 프록시를 호출합니다.

## Mattermost

Mattermost는 시연 결과 공유 채널로 사용합니다.

필요 항목:

- Mattermost server URL
- 사용자 또는 bot token
- target channel alias 또는 channel id

사용 흐름:

1. 사용자가 Mattermost credential을 등록합니다.
2. 에이전트가 `mattermost-send` 스킬을 통해 채널 alias를 해석합니다.
3. 작업 결과를 지정 채널에 마크다운 메시지로 전송합니다.

민감한 token은 저장소 문서에 적지 않고, 서비스 credential 저장 화면 또는 로컬 환경변수로만 관리합니다.

## Firebase Cloud Messaging

모바일 앱은 FCM으로 작업 완료 알림을 받습니다.

필요 항목:

- Firebase Android app 등록
- `mobile/app/google-services.json`
- backend에서 FCM 토큰 등록 API 사용

Firebase project id는 `e105-d54d1`, Android package name은 `com.example.mob`입니다.

동작 흐름:

1. 모바일 앱 시작 시 FCM token을 발급받습니다.
2. 앱이 backend에 token을 등록합니다.
3. AI 작업 완료 이벤트가 발생하면 backend가 모바일로 알림을 보냅니다.

## Samsung Health

모바일 앱은 Samsung Health SDK를 통해 건강 데이터를 수집합니다.

사용 데이터 예:

- 수면 시간
- 심박수
- 활동 데이터

시연에서는 건강 에이전트가 최근 건강 데이터를 기반으로 사용자의 컨디션을 요약하는 흐름을 사용합니다.

## MQTT / IoT Display

IoT 디스플레이는 MQTT broker를 통해 작업 상태를 수신합니다.

로컬 기본값:

```env
IOT_MQTT_ENABLED=true
IOT_MQTT_HOST=localhost
IOT_MQTT_PORT=1883
IOT_MQTT_TOPIC_PREFIX=devices
```

Docker Compose 실행 시 `mosquitto` 서비스가 `1883` 포트로 열립니다.

## Local Bridge

브릿지는 클라우드 AI와 사용자 PC의 허용 폴더를 연결합니다.

설정 위치:

```env
BRIDGE_ENVIRONMENT=local
BRIDGE_WORKSPACE_ROOT=C:\Users\YOUR_USER\Desktop\heygent-workspace
```

연결 절차:

1. 웹에서 브릿지 페어링 코드를 발급합니다.
2. PC에서 `python -m bridge.tray`를 실행합니다.
3. GUI에 페어링 코드와 디바이스 이름을 입력합니다.
4. 연결 후 에이전트가 허용된 폴더 안에서 파일 생성, 파일 읽기, 명령 실행을 위임합니다.
