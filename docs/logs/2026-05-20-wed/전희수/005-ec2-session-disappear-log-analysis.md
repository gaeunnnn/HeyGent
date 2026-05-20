# 작업 로그

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-refactor/pipeline-AI
- PR: 없음

## 작업 목적

- EC2 환경에서 최근 생성한 세션이 화면 이동 후 사라지는 것처럼 보인다는 제보를 서버 로그와 DB 기준으로 확인한다.

## 변경 요약

- 코드 변경은 하지 않았다.
- EC2의 Docker 컨테이너 상태, Postgres/Redis 지속성, `agent_sessions`/`agent_messages` 상태, 최근 AI/backend 로그를 읽기 전용으로 점검했다.
- 최근 세션은 삭제되지 않았고 DB에 남아 있음을 확인했다.
- 최근 생성 세션과 기존 조회 세션의 `owner_user_id`가 서로 달라, 현재 인증 사용자 기준 목록 필터링 때문에 사라진 것처럼 보일 가능성이 높다고 판단했다.

## 주요 파일

- `tmp/EC2test/pem.md`
- `ai/app/api/http/sessions.py`
- `ai/app/storage/postgres/session_store.py`
- `frontend/src/store/useChatStore.ts`
- `frontend/src/components/layout/sessionListUtils.ts`

## 테스트 / 확인

- EC2 접속 확인: `ubuntu@k14e105.p.ssafy.io`
- 컨테이너 상태 확인:
  - `heygent-postgres`, `heygent-redis`: 약 46시간 실행, restart count 0
  - `heygent-backend`, `heygent-ai`: 약 3시간 실행
  - `heygent-frontend`: 약 1시간 실행
- Postgres 볼륨:
  - `heygent-deploy_heygent-postgres-data`가 `/var/lib/postgresql/data`에 마운트됨
- Redis 볼륨:
  - `heygent-deploy_heygent-redis-data`가 `/data`에 마운트됨
- DB 확인:
  - `api.session` 총 44개, 삭제 18개, visible 26개
  - 2026-05-20 04:45 UTC 생성 세션 2개는 `owner_user_id=1`, `deleted_at IS NULL`, `archived_at IS NULL`, `message_count=0`
  - 기존에 계속 조회되던 주요 세션은 `owner_user_id=3` 또는 다른 사용자 소유도 존재
- 로그 확인:
  - 2026-05-20 04:45 UTC `POST /ai/api/v1/sessions` 2회 200 OK
  - 이후 해당 세션의 agents/work/artifacts 조회도 200 OK
  - 2026-05-20 03:08 UTC에는 다른 사용자 소유 세션 접근에서 403 Forbidden 기록 확인
  - 여러 시점에 만료/무효 토큰으로 보이는 `INVALID_TOKEN`/401 이후 200 재검증 기록 확인

## 결정 / 이슈

- DB/볼륨 유실 증거는 없다.
- 최근 세션은 실제 삭제되지 않았고, 인증 사용자별 목록 조회 조건 때문에 보이지 않는 현상으로 보는 것이 현재 가장 강한 가설이다.
- 빈 세션(`message_count=0`) 자체는 프론트의 현 목록 필터에서 제거 조건이 아니다.
- 프론트의 새 세션 생성 흐름은 HTTP 생성 후 WebSocket `fetchSessions()`에 의존하므로, 인증 재연결/토큰 전환이 겹치면 사용자가 다른 owner의 세션 목록을 보게 될 수 있다.

## 다음 단계

- 재현 시 브라우저의 현재 `/api/v1/users/me` 응답 사용자 id와 새 세션의 `owner_user_id`를 같이 기록한다.
- 새 세션 생성 직후 사이드바 갱신을 HTTP 응답 기반으로 즉시 upsert하거나, `fetchSessions()` 실패를 사용자에게 노출하는 보강을 검토한다.
- 로그인/토큰 갱신 중 계정이 바뀌는 경로가 있는지 frontend auth store와 backend dev-login/Kakao login 흐름을 추가 점검한다.
