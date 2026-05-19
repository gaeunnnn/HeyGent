# 장기기억 보조 호출 Gemini provider 선택 보정

## 날짜

2026-05-16

## 작성자

김상지

## 대상 브랜치

- `AI-feat/ai-provider-selection`

## Jira 작업명

- `[AI] feat : Gemini 프로바이더 연결 및 에이전트 공급자 선택`

## MR 제목

- `[AI/FE] feat : Gemini 프로바이더 실행 연결 및 공급자 선택 UI 추가`

## 작업 배경

Gemini 모델로 팀장 실행을 테스트했을 때 본 실행은 Gemini로 처리됐지만, 장기기억 recall/writeback 보조 LLM 호출에서 provider/model이 섞이는 문제가 확인됐다.

관찰 로그에서는 `fallback_provider_name`이 `openai_api`인데 `fallback_selected_model`은 `gemini-2.5-flash`였다. 이 상태에서 Gemini API key가 OpenAI Responses API로 전달되어 `invalid_api_key` 401 오류가 발생했다.

## 원인

- 장기기억 recall planner, extraction/reconciliation, mark-used attribution provider가 `ProviderRegistry`를 들고 있었지만 실제 호출 provider는 항상 `preferred_model_provider()`로 선택했다.
- `preferred_model_provider()`는 기존 OpenAI 기본 provider를 반환한다.
- 반면 runtime context에는 Gemini provider/model이 들어올 수 있어 OpenAI provider가 Gemini key/model로 호출되는 혼합 상태가 생겼다.

## 작업 내용

- memory runtime context에서 provider가 없고 모델이 `gemini-*`이면 `gemini_api_key`로 추론하도록 추가했다.
- memory recall planner가 runtime context의 provider/model 기준으로 `ProviderRegistry.model_provider_for()`를 사용하도록 변경했다.
- memory extraction/reconciliation provider도 context의 provider/model 기준으로 OpenAI/Gemini provider를 선택하도록 변경했다.
- memory usage attribution provider도 runtime context의 provider/model 기준으로 provider를 선택하도록 변경했다.
- writeback API에서 provider 이름이 비어 있고 모델만 있는 경우에도 provider를 모델 기준으로 추론하도록 변경했다.
- Gemini memory 보조 호출이 OpenAI provider로 전달되지 않도록 회귀 테스트를 추가했다.

## 주요 파일

- `ai/app/domain/orchestration/agent/memory/runtime_context.py`
- `ai/app/domain/orchestration/agent/memory/memory_recall_planner_provider.py`
- `ai/app/domain/orchestration/agent/memory/memory_extraction_provider.py`
- `ai/app/domain/orchestration/agent/memory/memory_usage_attribution_provider.py`
- `ai/app/api/memory_writeback.py`
- `ai/tests/test_memory_provider_selection.py`

## 테스트 / 확인

```powershell
cd ai
.\.venv\Scripts\python.exe -m pytest tests\test_memory_provider_selection.py tests\api\test_memory_context.py tests\test_memory_writeback.py tests\api\test_memory_mark_used.py tests\providers\test_gemini_provider.py tests\providers\test_openai_provider.py
```

결과:

```text
53 passed
```

## 결정 / 이슈

- provider 값이 없고 모델도 없으면 기존처럼 OpenAI provider를 기본값으로 유지한다.
- provider 값이 없지만 모델이 `gemini-*`이면 Gemini provider를 사용한다.
- memory 보조 호출도 본 실행의 provider/model 선택을 따라가도록 정리했다.

## 다음 단계

- 배포 후 Gemini 모델로 장기기억 recall/writeback/mark-used observation에서 provider가 `gemini_api`로 표시되는지 확인한다.
- OpenAI 모델 선택 시 기존 OpenAI memory 보조 호출이 유지되는지 함께 확인한다.
