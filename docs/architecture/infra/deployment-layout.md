# Infra 배포 구조

## 개요

루트 `compose.yml`은 로컬/개발용 전체 서비스를 한 번에 실행하기 위한 Docker Compose 구성입니다.

## 서비스 구성

| 서비스 | 포트 | 설명 |
| --- | --- | --- |
| `postgres` | `5432` | PostgreSQL + pgvector. 사용자/메모리/실행 기록 등 저장 |
| `redis` | `6379` | cache, projection, pub/sub |
| `mosquitto` | `1883` | MQTT broker. IoT display 이벤트 전달 |
| `backend` | `8080` | Spring Boot API |
| `ai` | `8000` | FastAPI AI 서버 |
| `frontend` | `5173` | Vite 웹 앱 |

## 컨테이너 의존성

```text
postgres ┐
redis    ├─> backend ─> ai
mosquitto┘              |
                        └─ frontend는 브라우저에서 backend/ai 호출
```

## AI workspace mount

`compose.yml`은 프로젝트 루트를 AI 컨테이너의 `/workspace`로 마운트합니다.

이유:
- AI file tool이 프로젝트 파일을 읽고 쓸 수 있어야 합니다.
- Windows 절대 경로가 들어와도 `S14P31E105` 기준으로 `/workspace` 하위 경로로 정규화할 수 있습니다.

## 환경 파일

저장소에는 예시 파일만 포함됩니다.

- 루트 `.env.example`
- `backend/.env`
- `ai/.env`
- `frontend/.env.example`
- `bridge/.env.example`
- `mobile/secrets.properties.example`

민감 값은 저장소에 넣지 않습니다.

## 실행

```powershell
docker compose -f compose.yml up -d --build
```

볼륨까지 초기화하려면:

```powershell
docker compose -f compose.yml down -v
docker compose -f compose.yml up -d --build
```
