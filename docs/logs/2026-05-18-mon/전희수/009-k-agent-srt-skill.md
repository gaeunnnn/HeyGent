# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-fix/agent-병목-개선
- PR: 없음

## 작업 목적

- K-에이전트 기본 구성에 SRT 예매/조회 skill을 먼저 도입한다.
- 계정 정보 입력 문서는 저장 시 원문이 지침 문서에 남지 않도록 마스킹한다.

## 변경 요약

- K-에이전트 기본 skill 목록에 `srt-booking`을 추가했다.
- K-에이전트 기본 문서에 `SECRETS.md`를 추가하고 SRT 계정 정보 입력 칸을 준비했다.
- `SECRETS.md` 저장 시 원문 값을 `<stored>`로 치환하는 파서를 추가했다.
- SRT skill 문서를 내장 skill 카탈로그에 추가했다.

## 주요 파일

- `ai/app/domain/agents/templates.py`
- `ai/app/domain/agents/secret_documents.py`
- `ai/app/storage/postgres/agent_repository.py`
- `ai/app/skills/k-skills/srt-booking/SKILL.md`
- `ai/tests/domain/test_agent_secret_documents.py`
- `ai/tests/storage/test_agent_repository_secrets.py`

## 테스트 / 확인

- `python -m pytest tests/domain/test_agent_secret_documents.py tests/domain/test_agent_templates.py tests/storage/test_agent_repository_secrets.py -q`
- SRT skill 문서가 임시 검토본과 동일한 원문인지 비교 확인했다.

## 결정 / 이슈

- SRT skill 본문은 별도 서비스 맞춤 문구를 섞지 않고 원문 그대로 유지했다.
- 현재 변경은 skill 연결과 비밀값 문서 마스킹까지이며, 저장된 비밀값을 실행 런타임에 안전하게 주입하는 전용 도구는 별도 후속 작업이 필요하다.

## 다음 단계

- SRT 실행 런타임 또는 비밀값 주입 경로를 정해 실제 조회 요청까지 연결한다.
- 새 기본 템플릿이 기존 세션에 동기화되는지 개발 환경에서 확인한다.
