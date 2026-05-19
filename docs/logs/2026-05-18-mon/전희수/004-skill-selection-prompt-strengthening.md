# Skill 선택 지침 강화

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 또는 PR

- `AI-feat/Agent-K-Skills`

## 작업 목적

- 에이전트가 사용 가능한 skill 목록을 먼저 확인하고, 요청에 맞는 skill을 최대한 우선 후보로 삼도록 프롬프트 지침을 강화한다.
- 별도 의도분류나 강제 실행 규칙은 추가하지 않고, 모델 판단 흐름만 skill 우선 확인 방향으로 보정한다.

## 변경 요약

- skill catalog 프롬프트에 작업 시작 시 skill 후보를 먼저 확인하라는 문구를 추가했다.
- 사용자 입력을 처리할 수 있는 skill이 있으면 일반 도구보다 해당 skill을 우선 후보로 삼도록 문구를 조정했다.
- 관련 skill 후보를 선택한 경우 `skills.read` 또는 `skill.execute`로 본문을 먼저 확인하도록 지침을 강화했다.
- 세션 에이전트 후보의 skill 설명은 위임 판단용이며, 현재 실행 에이전트가 직접 보유한 skill이 아니면 `skills.read`로 읽지 않도록 라우팅 지침을 추가했다.
- 세션 에이전트 후보 skill 설명은 라우팅 용도에 맞게 80자로 줄이고, root 본인의 직접 실행 skill catalog 설명 길이는 유지했다.
- 프롬프트 계약 테스트 기대 문구를 현재 지침에 맞게 갱신했다.

## 주요 파일

- `AI/app/domain/orchestration/prompts/skill_prompt.py`
- `AI/app/domain/orchestration/prompts/prompt_builder.py`
- `AI/tests/test_model_loop_contract.py`

## 테스트 또는 확인 내용

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\test_model_loop_contract.py -q`
- 결과: `28 passed`

## 결정, 이슈, 리스크

- skill 사용을 강제하지는 않는다.
- 요청과 관련된 skill 후보가 있을 때 먼저 확인하고 우선 후보로 삼는 방향만 명시한다.
- root는 세션 에이전트 후보의 skill 설명을 보고 위임 판단만 하며, 실제 skill 본문 확인은 해당 skill을 보유한 에이전트가 수행한다.
- 실제 런타임에서 `skills.read` 호출 빈도가 충분히 개선되는지는 다음 실호출 테스트로 확인해야 한다.

## 다음 단계

- 동일한 부산 기상 요청으로 실호출 1회를 수행해 `skills.read`, `http_get`, `/v1/responses`, `/v1/models`, 작업 상태 변화를 확인한다.
