# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-fix/agent-병목-개선
- PR: 없음

## 작업 목적

- `SECRETS.md` 저장 시 원문을 마스킹만 하고 버리지 않고, 실제 비밀값 저장소에 암호화해 보관한다.

## 변경 요약

- AI 서버에 agent secret 암호화 유틸과 설정값을 추가했다.
- `ai_agent_secret_values` 테이블과 마이그레이션을 추가했다.
- `SECRETS.md` 저장 시 원문 값은 암호화 테이블에 저장하고, 지침 문서에는 `<stored>`만 남기도록 연결했다.
- 암호화 저장소가 설정되지 않은 상태에서 raw secret 저장을 시도하면 저장을 거부하도록 했다.

## 주요 파일

- `ai/app/domain/agents/secret_store.py`
- `ai/app/storage/postgres/agent_repository.py`
- `ai/app/storage/postgres/schema.py`
- `ai/app/storage/postgres/migrations.py`
- `ai/app/core/config.py`
- `ai/app/api/http/agents.py`
- `ai/tests/storage/test_agent_repository_secrets.py`
- `ai/tests/storage/test_postgres_durable_contracts.py`

## 테스트 / 확인

- `python -m pytest tests/domain/test_agent_secret_documents.py tests/domain/test_agent_templates.py tests/storage/test_agent_repository_secrets.py tests/storage/test_postgres_durable_contracts.py -q`
- AI 컨테이너 재빌드 후 health check를 확인했다.
- `0020_agent_secret_values` 마이그레이션과 `ai_agent_secret_values` 테이블 생성 여부를 확인했다.
- 컨테이너 안에서 암호화/복호화 왕복 동작을 확인했다.

## 결정 / 이슈

- Java backend 코드는 수정하지 않았다. 지침 문서 저장 API와 agent profile 저장소가 AI 서버에 있으므로 AI 서버에서 처리한다.
- 로컬 개발 환경에는 별도 agent secret 암호화 키를 추가했다. 해당 값은 git ignore 대상이며 문서에 원문을 남기지 않는다.

## 다음 단계

- SRT runtime/tool이 필요해지면 `get_agent_secret_values`를 통해 저장된 값을 런타임에만 주입하고, 모델 프롬프트에는 원문을 노출하지 않도록 연결한다.
