# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-fix/agent-병목-개선
- PR: 미생성

## 작업 목적

- 새 세션에서 기본 제공 subagent 생성 시 팀장은 `gpt-5.4`, subagent는 `gpt-5.2`를 쓰도록 생성 기준을 보정한다.
- 부산 기상 요청 실측에서 100초 이상 걸린 원인을 모델 루프, 도구 호출, 토큰 사용량 기준으로 확인한다.

## 변경 요약

- 내장 subagent 템플릿의 기본 모델을 `gpt-5.2`로 변경했다.
- 팀장 기본 모델은 `gpt-5.4`로 유지했다.
- 생성 기준이 유지되는지 테스트를 추가했다.
- AI 컨테이너를 재빌드해 system agent template DB 값이 갱신되는 것을 확인했다.

## 주요 파일

- `ai/app/domain/agents/templates.py`
- `ai/tests/domain/test_agent_templates.py`

## 테스트 / 확인

- `python -m pytest tests/domain/test_agent_templates.py::test_builtin_subagent_templates_default_to_worker_model -q`
- `python -m pytest tests/domain/test_agent_templates.py -q`
- 새 세션 생성 후 `POST /sessions/{sessionId}/agents/defaults` 호출 결과 기본 subagent 4개가 모두 `gpt-5.2`로 생성되는 것을 확인했다.

## 결정 / 이슈

- 이번 변경은 생성 기준만 바꾼다. 이미 만들어진 기존 세션의 subagent 프로필은 기존 모델 값을 유지한다.
- 프론트 subagent 수동 생성 UI 기본값은 별도 하위 규칙상 명시적 프론트 코드 수정 요청이 있을 때 다룬다.
- 100초 실측의 주된 원인은 child TaskRun(사용자 요청에서 위임된 하위 실행)이 `gpt-5.4`로 17회 모델 루프를 돌고, `http_get`을 14회 호출한 흐름이다.

## 다음 단계

- 기존 세션 프로필까지 일괄 보정할지 결정한다.
- K-에이전트의 날씨 조사 흐름에서 `skills.read`와 반복 `http_get` 호출을 줄일 수 있는 실행 정책을 검토한다.
