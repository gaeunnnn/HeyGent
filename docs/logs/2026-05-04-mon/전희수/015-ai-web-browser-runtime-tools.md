# 작업 로그

## 날짜

2026-05-04

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미정

## 작업 목적

- AI runtime에서 실제 웹 검색/웹 추출/브라우저 도구를 사용할 수 있게 하고, 루트 `ai/tools`가 아니라 `ai/app/tools` 아래로 구조화한다.
- 가져온 도구 코드의 주석과 패키지명을 출처 중심 표현이 아니라 실제 역할 중심 표현으로 정리한다.

## 변경 요약

- `app.tools.web_runtime` 패키지를 추가해 웹 검색, 웹 추출, 브라우저 실행 구현체와 support 모듈을 한곳에 배치했다.
- public runtime adapter는 `app.tools.web`와 `app.tools.browser`에 유지하고, 실제 실행만 `app.tools.web_runtime`으로 위임하도록 정리했다.
- web/browser toolset을 runtime catalog, local runtime, delegate worker 기본 toolset에 연결했다.
- 검색 공급자 키가 없는 개발 환경에서도 OpenAI API 키로 웹 검색이 가능하도록 OpenAI hosted web search fallback을 추가했다.
- worker 위임 시 모델이 `web_search`, `web_extract` 같은 도구 이름을 toolset으로 넣어도 `web` toolset으로 정규화하도록 보강했다.
- 출처나 임시 호환 중심 표현을 새 tool 코드와 테스트명에서 제거하고, 상단 주석을 도구 역할 중심 설명으로 바꿨다.

## 주요 파일

- `ai/app/tools/web_runtime/...`
- `ai/app/tools/web/web_tools.py`
- `ai/app/tools/browser/browser_tool.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/tools/runtime/registry.py`
- `ai/app/tools/runtime/toolsets.py`
- `ai/app/domain/orchestration/delegation/delegate_runtime.py`
- `ai/pyproject.toml`
- `ai/Dockerfile`
- `ai/tests/tools/test_runtime_tools.py`

## 테스트 / 확인

- `py -3.11 -m compileall -q app\tools\web_runtime app\tools\web app\tools\browser`
- `py -3.11 -m pytest tests\tools\test_runtime_tools.py -q`
- `py -3.11 -m pytest tests -q`
  - 결과: 290 passed, 6 failed
  - 실패는 기존 환경/기대값 이슈로 보이는 Redis 필수 설정 테스트 1건과 CLI base URL 기대값 5건이다.
- `docker compose up -d --build ai`
- 컨테이너에서 `web_search` backend가 `openai`로 잡히고 실제 검색 결과가 성공으로 반환되는 것을 확인했다.
- Playwright에서 dev-login 상태로 실제 프론트 입력을 보내 `web_runtime_smoke.md` 파일 저장과 StepRun 완료 표시를 확인했다.

## 결정 / 이슈

- `ai/tools`, `ai/tool_support` 같은 루트 패키지는 만들지 않고 `app.tools.web_runtime` 아래로 통합했다.
- `browser` toolset은 명시적으로 요청될 때만 쓰고, 기본 `local-core`에는 `web`만 포함했다.
- 긴 subagent 검증 시 기존 worker launch timeout 문제가 드러나 tool 이름을 toolset으로 정규화하는 보강을 추가했다.

## 다음 단계

- `web_extract`도 검색 공급자 키가 없는 환경에서 더 풍부한 fallback을 제공할지 검토한다.
- 기존 전체 테스트 실패 6건은 별도 작업에서 환경 정책과 테스트 기대값을 맞춰야 한다.
