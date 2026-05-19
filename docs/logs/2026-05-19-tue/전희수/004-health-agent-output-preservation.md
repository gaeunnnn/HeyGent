# 작업 로그

## 날짜

2026-05-19

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Health-agent
- PR: 작성 예정

## 작업 목적

- `health-condition-check` 스킬을 가진 세션 에이전트의 건강 데이터 해석 결과가 팀장 최종 답변에서 요약 또는 재작성되며 근거와 제한 문구가 약해지는 문제를 완화한다.

## 변경 요약

- 팀장 agent loop 프롬프트에 도메인 스킬 결과 보존 규칙을 추가했다.
- 보존 대상 스킬을 `health-condition-check`로 명시했다.
- 보존 대상 스킬의 하위 에이전트 본문은 요약하거나 재작성하지 않고 최종 응답 본문으로 그대로 복사하도록 안내했다.
- 필요한 경우 본문 앞에 짧은 안내 문장만 덧붙일 수 있게 했다.

## 주요 파일

- `ai/app/domain/orchestration/prompts/prompt_builder.py`

## 테스트 / 확인

- `python -m py_compile ai\app\domain\orchestration\prompts\prompt_builder.py`
- `docker compose up -d --build ai`
- `heygent-ai` 컨테이너 내부에 보존 규칙 문구가 반영된 것을 확인했다.

## 결정 / 이슈

- 현재는 로직 pass-through가 아니라 프롬프트 규칙으로 먼저 검증한다.
- 팀장이 계속 하위 결과를 재작성하면 보존 대상 스킬 결과를 런타임에서 직접 pass-through하는 로직 변경이 필요할 수 있다.

## 다음 단계

- 웹 세션에서 같은 건강 컨디션 질문으로 팀장 최종 답변이 하위 헬스 에이전트 본문을 보존하는지 확인한다.
