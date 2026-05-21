# 1. 포팅 매뉴얼

이 문서는 GitLab에서 HeyGent 소스코드를 받은 뒤 로컬 또는 개발 서버에서 실행하기 위한 절차입니다.

## 1. 실행 환경

| 구분 | 버전 또는 제품 |
| --- | --- |
| OS | Windows 11 또는 Linux |
| JDK | 17 이상 |
| Node.js | 20 LTS 권장 |
| Python | 3.10 이상 |
| Docker | Docker Engine / Docker Desktop |
| DB | PostgreSQL 16 + pgvector |
| Cache | Redis 7 |
| MQTT | Eclipse Mosquitto 2 |
| IDE | IntelliJ IDEA, VS Code 등 |

## 2. 프로젝트 구조

```text
S14P31E105/
├─ frontend/     # React/Vite 웹 클라이언트
├─ backend/      # Spring Boot API 서버
├─ ai/           # FastAPI AI 런타임 서버
├─ mobile/       # Android 모바일 앱
├─ bridge/       # 사용자 PC 로컬 브릿지
├─ docker/       # Mosquitto 등 인프라 설정
├─ docs/         # 협업 로그 및 아키텍처 문서
├─ exec/         # 제출 산출물
└─ compose.yml   # 통합 실행용 Docker Compose
```

## 3. 저장소 클론

```powershell
git clone <TEAM_GITLAB_REPOSITORY_URL> S14P31E105
cd S14P31E105
```

제출 환경에서는 실제 팀 GitLab URL로 `<TEAM_GITLAB_REPOSITORY_URL>`을 교체합니다.

## 4. 환경변수 준비

로컬 실행에 필요한 기본 URL과 포트는 아래 값을 기준으로 설정합니다. API key, token, secret, encryption key 원문은 제출 문서에 포함하지 않습니다.

### 4.1 루트 `.env`

루트의 `.env.example`을 `.env`로 복사합니다.

```powershell
Copy-Item .env.example .env
```

예시:

```env
POSTGRES_DB=heygent
POSTGRES_USER=heygent
POSTGRES_PASSWORD=changeme
```

### 4.2 Backend `.env`

`backend/.env` 파일을 생성합니다.

```env
SPRING_DATASOURCE_URL=jdbc:postgresql://127.0.0.1:5432/heygent
SPRING_DATASOURCE_USERNAME=heygent
SPRING_DATASOURCE_PASSWORD=changeme
SPRING_DATA_REDIS_HOST=localhost
SPRING_DATA_REDIS_PORT=6379

KAKAO_CLIENT_ID=<kakao-rest-api-key>
KAKAO_CLIENT_SECRET=<kakao-client-secret>
KAKAO_REDIRECT_URI=http://localhost:5173/auth/kakao/callback

COMPOSIO_API_KEY=<composio-api-key>
COMPOSIO_NOTION_REDIRECT_URI=http://localhost:5173/auth/notion/callback
COMPOSIO_NOTION_INTEGRATION_ID=<composio-notion-integration-id>
COMPOSIO_GMAIL_REDIRECT_URI=http://localhost:5173/auth/gmail/callback
COMPOSIO_GMAIL_INTEGRATION_ID=<composio-gmail-integration-id>

JWT_SECRET=<32-byte-or-longer-random-secret>
CORS_ALLOWED_ORIGINS=http://localhost:5173

AI_INTERNAL_TOKEN=<backend-ai-shared-token>

MEMORY_EMBEDDING_ENABLED=true
MEMORY_EMBEDDING_API_KEY=<openai-api-key>
OPENAI_API_KEY=<openai-api-key>
OPENAI_CREDENTIAL_ENCRYPTION_KEY=<32-byte-encryption-key>

IOT_MQTT_ENABLED=true
IOT_MQTT_HOST=localhost
IOT_MQTT_PORT=1883
```

Docker Compose 내부에서 backend가 MQTT broker에 붙을 때는 `IOT_MQTT_HOST=mosquitto`를 사용합니다. Docker 밖에서 backend를 직접 실행할 때는 `localhost`를 사용합니다.

### 4.3 AI `.env`

`ai/.env.example`을 `ai/.env`로 복사한 뒤 값을 조정합니다.

```powershell
Copy-Item ai/.env.example ai/.env
```

중요 항목:

```env
HEYGENT_BACKEND_BASE_URL=http://backend:8080
HEYGENT_BACKEND_AUTH_VERIFY_URL=http://backend:8080/internal/ai/auth/validate
HEYGENT_BACKEND_BRIDGE_AUTH_VERIFY_URL=http://backend:8080/internal/bridge/auth/validate
HEYGENT_REDIS_URL=redis://redis:6379/0
HEYGENT_INTERNAL_SERVICE_TOKEN=<backend-ai-shared-token>
HEYGENT_OPENAI_RESPONSE_MODEL=gpt-5.4
HEYGENT_TASK_EXECUTION_QUEUE_ENABLED=true
```

로컬에서 AI 서버를 Docker 밖에서 직접 실행할 때는 `backend` 호스트명을 `localhost`로 바꿉니다.

### 4.4 Frontend `.env`

```powershell
Copy-Item frontend/.env.example frontend/.env
```

```env
VITE_API_BASE_URL=http://localhost:8080
VITE_AI_API_BASE_URL=http://localhost:8000/ai/api/v1
VITE_AI_WS_BASE_URL=ws://localhost:8000/ai/api/v1/realtime/user/ws
VITE_KAKAO_CLIENT_ID=<kakao-rest-api-key>
VITE_KAKAO_REDIRECT_URI=http://localhost:5173/auth/kakao/callback
VITE_FIREBASE_PROJECT_ID=<firebase-project-id>
```

FCM 웹 설정을 사용하는 경우 `VITE_FIREBASE_API_KEY`, `VITE_FIREBASE_AUTH_DOMAIN`, `VITE_FIREBASE_STORAGE_BUCKET`, `VITE_FIREBASE_MESSAGING_SENDER_ID`, `VITE_FIREBASE_APP_ID`, `VITE_FIREBASE_VAPID_KEY`도 함께 설정합니다.

### 4.5 Bridge `.env`

```powershell
Copy-Item bridge/.env.example bridge/.env
```

```env
BRIDGE_ENVIRONMENT=local
BRIDGE_AI_WS_URL=ws://localhost:8000/ai/api/v1/internal/bridge/ws
BRIDGE_WORKSPACE_ROOT=C:\Users\YOUR_USER\Desktop\heygent-workspace
```

브릿지 토큰은 웹에서 페어링 코드를 발급받아 GUI에 입력하면 로컬에 저장됩니다.

### 4.6 Mobile `secrets.properties`

```powershell
Copy-Item mobile/secrets.properties.example mobile/secrets.properties
```

```properties
KAKAO_NATIVE_APP_KEY=<kakao-native-app-key>
BASE_URL=http://<backend-host>:8080/
```

배포 서버에 연결하는 APK를 만들 때는 `BASE_URL=https://k14e105.p.ssafy.io/` 형식을 사용합니다.

Firebase FCM을 사용하는 경우 `mobile/app/google-services.json`을 Firebase 콘솔에서 받은 파일로 교체합니다.

Android package name은 `com.example.mob`입니다.

## 5. Docker Compose 통합 실행

루트에서 전체 서비스를 실행합니다.

```powershell
docker compose -f compose.yml up -d --build
```

주요 접속 URL:

| 서비스 | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| Backend API | http://localhost:8080 |
| Backend Swagger | http://localhost:8080/swagger-ui/index.html |
| AI API | http://localhost:8000/ai/api/v1 |
| PostgreSQL | localhost:5432 |
| Redis | localhost:6379 |
| MQTT | localhost:1883 |

로그 확인:

```powershell
docker compose -f compose.yml logs -f backend
docker compose -f compose.yml logs -f ai
docker compose -f compose.yml logs -f frontend
```

초기화 후 재실행:

```powershell
docker compose -f compose.yml down -v
docker compose -f compose.yml up -d --build
```

## 6. 개별 실행

### 6.1 Backend

```powershell
cd backend
./gradlew bootRun
```

### 6.2 AI

```powershell
cd ai
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m app
```

### 6.3 Frontend

```powershell
cd frontend
npm install
npm run dev -- --host 0.0.0.0
```

### 6.4 Bridge

```powershell
cd bridge
pip install -r requirements.txt
python -m bridge.tray
```

브릿지 실행 후 웹에서 발급한 페어링 코드를 입력하고, 허용할 PC 폴더를 `BRIDGE_WORKSPACE_ROOT`로 지정합니다.

### 6.5 Mobile

Android Studio에서 `mobile` 프로젝트를 열고 `mobile/app` 구성을 실행합니다.

필수 확인:

- `mobile/secrets.properties`의 `BASE_URL` 끝에 `/`가 포함되어 있어야 합니다.
- Kakao Android 키 해시가 Kakao Developers에 등록되어야 합니다.
- FCM을 확인하려면 Firebase 프로젝트의 `google-services.json`이 필요합니다.

## 7. 정상 동작 확인

1. `http://localhost:5173` 접속
2. dev-login 또는 Kakao 로그인
3. OpenAI API key 등록 또는 서버 fallback key 설정 확인
4. 새 세션 생성
5. 채팅에서 다음 요청 실행

```text
오늘 받은 뉴스레터를 요약해서 Mattermost에 공유해줘.
```

브릿지 확인 요청:

```text
내 PC 작업 폴더에 hello.txt 파일을 만들고 내용을 적어줘.
```

정상이라면 웹 화면에서 작업 진행 상태가 보이고, 브릿지 워크스페이스 폴더에 파일이 생성됩니다.

## 8. 자주 발생하는 문제

| 증상 | 확인 내용 |
| --- | --- |
| Frontend에서 API 호출 실패 | `VITE_API_BASE_URL`, CORS 허용 origin 확인 |
| WebSocket 연결 실패 | `VITE_AI_WS_BASE_URL`, AI 서버 포트, 로그인 토큰 확인 |
| AI가 backend 인증 실패 | `AI_INTERNAL_TOKEN`과 `HEYGENT_INTERNAL_SERVICE_TOKEN` 값 일치 확인 |
| Gmail/Notion 연결 실패 | Composio API key, integration id, redirect URI 확인 |
| 장기기억 검색 실패 | OpenAI embedding key, pgvector DB 연결 확인 |
| 브릿지가 컨테이너에서 실행되는 것처럼 보임 | PC 브릿지 프로그램 실행 및 페어링 상태 확인 |
| 모바일 로그인 실패 | Kakao native key, Android key hash, backend URL 확인 |
