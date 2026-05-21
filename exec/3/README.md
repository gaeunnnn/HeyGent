# 3. DB 덤프 파일

HeyGent의 DB 데이터는 사용자가 서비스를 실행하면서 생성되는 대화, 작업 실행 기록, 에이전트 설정, 외부 서비스 연결 상태가 중심입니다. 이 데이터들은 시연 시점에 생성되어 화면과 에이전트 흐름에서 소비되므로, 제출 시점에 별도로 모아 복원해야 할 고정 기준 데이터는 없습니다.

따라서 제출용 DB 덤프는 pgvector 확장만 보장하는 최소 덤프 형태로 제공합니다. 애플리케이션을 실행하면 Hibernate `ddl-auto=update`로 스키마가 생성되고, 시연에 필요한 데이터는 화면에서 직접 생성하면 됩니다.

## 파일

| 파일 | 설명 |
| --- | --- |
| [empty-db-dump.sql](./empty-db-dump.sql) | pgvector extension만 보장하는 최소 DB 덤프 |

## 적용 방법

Docker Compose로 DB를 띄운 뒤 실행합니다.

```powershell
docker compose -f compose.yml up -d postgres
docker compose -f compose.yml cp exec/3/empty-db-dump.sql postgres:/tmp/empty-db-dump.sql
docker compose -f compose.yml exec postgres psql -U heygent -d heygent -f /tmp/empty-db-dump.sql
```

로컬 `psql`을 사용할 경우:

```powershell
psql -h localhost -p 5432 -U heygent -d heygent -f exec/3/empty-db-dump.sql
```

## 데이터 정책

- 실제 사용자 대화, OAuth 토큰, API key, Mattermost token, Gmail/Notion credential은 덤프에 포함하지 않습니다.
- 시연용 데이터는 서비스 실행 후 화면에서 직접 생성합니다.
- 장기기억, 작업 기록, 에이전트 설정은 실행 흐름에 따라 새로 생성하는 것을 기준으로 합니다.
- DB에 저장되는 값은 기능 동작 과정의 상태와 기록이므로, 별도 seed 데이터 없이 서비스 흐름을 확인합니다.
