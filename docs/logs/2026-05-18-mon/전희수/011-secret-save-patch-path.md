# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-fix/agent-병목-개선
- PR: 없음

## 작업 목적

- 프론트 설정 화면의 저장 버튼이 사용하는 세션 에이전트 수정 경로에서도 `SECRETS.md` 원문 값이 저장 후 다시 노출되지 않게 한다.

## 변경 요약

- `PATCH /sessions/{sessionId}/agents/{profileId}` 경로에서 `config_snapshot.documents`의 `SECRETS.md`를 저장 전에 마스킹하고 암호화 저장소에 기록하도록 보강했다.
- K-에이전트 `SECRETS.md` 기본 안내 문구를 “저장 시 자동으로 암호화 저장됩니다” 중심으로 명확히 바꿨다.
- SRT 필수값이 모두 저장된 경우 `## srt-booking (암호화 저장 완료)`로 표시하고, 하나라도 비어 있으면 완료 표시를 제거하도록 했다.
- 기존 DB의 `SECRETS.md` 문서와 프로필 설정 JSON을 마스킹/문구 갱신 상태로 복구했다.

## 주요 파일

- `ai/app/domain/agents/templates.py`
- `ai/app/storage/postgres/agent_repository.py`
- `ai/tests/domain/test_agent_templates.py`
- `ai/tests/storage/test_agent_repository_secrets.py`

## 테스트 / 확인

- `python -m pytest tests/domain/test_agent_templates.py tests/domain/test_agent_secret_documents.py tests/storage/test_agent_repository_secrets.py tests/storage/test_postgres_durable_contracts.py -q`
- AI 컨테이너 재빌드 후 health check를 확인했다.
- DB의 지침 문서와 프로필 설정 JSON에서 raw SRT secret 형태가 남지 않았는지 확인했다.

## 결정 / 이슈

- 현재 프론트 저장 버튼은 전용 instruction document API가 아니라 세션 에이전트 전체 수정 API를 사용한다. 따라서 두 저장 경로 모두 secret sanitizing을 유지해야 한다.

## 다음 단계

- 화면에서 저장 직후 에디터의 원문 값이 사라지고 저장 완료 상태가 보이는지 직접 확인한다.
