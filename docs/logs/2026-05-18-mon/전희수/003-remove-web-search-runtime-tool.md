# web_search 런타임 도구 제거

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 또는 PR

AI-feat/Agent-K-Skills

## 작업 목적

OpenAI hosted web search fallback이 검색 전용 키 없이도 `web_search` 도구를 노출하고, 실행 중 OpenAI Responses API quota 429를 유발하던 경로를 제거한다.

## 변경 요약

- 런타임 tool catalog에서 `web_search` 등록을 제거했다.
- `web` toolset은 `http_get`만 포함하도록 변경했다.
- `LocalToolRuntime`의 `web_search` handler 연결과 delegate toolset 정규화 매핑을 제거했다.
- OpenAI `web_search_preview` fallback 호출 경로를 제거했다.
- 더 이상 참조되지 않는 `ai/app/tools/web_runtime` 레거시 패키지를 제거했다.
- 검색 fallback용 DuckDuckGo skill 문서를 제거하고, 관련 skill 문서의 `web_search` 안내를 정리했다.
- 테스트 기대값을 `web_search` 미노출 기준으로 바꿨다.

## 주요 파일

- `ai/app/tools/web/web_tools.py`
- `ai/app/tools/web_runtime/...`
- `ai/app/tools/runtime/toolsets.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/skills/web/web-search-fallback/SKILL.md`
- `ai/tests/tools/test_runtime_tools.py`
- `ai/tests/api/test_tasks_runtime.py`
- `ai/tests/test_model_loop_contract.py`

## 테스트 또는 확인 내용

- `AI\.venv\Scripts\python.exe -m pytest ai/tests/tools/test_runtime_tools.py ai/tests/api/test_tasks_runtime.py ai/tests/test_model_loop_contract.py ai/tests/domain/session/test_conversation_history.py -q`
- 결과: 115 passed
- `ai/app` 기준 `web_search_handler`, `_run_web_search`, `web_search_preview`, OpenAI hosted search 문자열이 남지 않는 것을 확인했다.
- `ai/app` / `ai/tests`에서 `app.tools.web_runtime` 참조가 남지 않는 것을 확인했다.
- `docker compose -f compose.yml up -d --build ai`
- `GET /ai/api/v1/ready` 결과: ready

## 결정, 이슈, 리스크

- 검색 전용 backend가 없는 현재 환경에서는 `web_search`를 사용할 수 없는 도구로 본다.
- 날씨와 공공 데이터성 요청은 `http_get`과 task-specific skill을 우선 사용한다.
- 향후 검색 기능이 필요하면 별도 검색 provider를 명시적으로 추가하고 새 도구 계약으로 도입한다.

## 다음 단계

- 관련 테스트를 실행해 `web_search`가 모델에게 노출되지 않는지 확인한다.
