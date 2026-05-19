# AI 장기기억 보조 호출 사용자 credential 적용

## 날짜

2026-05-16

## 작성자

김상지

## 대상 브랜치

- `AI-fix/memory-runtime-user-credential`

## Jira 작업명

- `[AI] fix : 장기기억 보조 호출 사용자 credential 적용`

## MR 제목

- `[AI] fix : 장기기억 보조 호출 사용자 credential 적용`

## 작업 배경

배포 서버에서 memory recall/writeback/mark-used observation을 확인했을 때, memory 보조 LLM 호출이 다음과 같이 실패했다.

```text
provider_name = openai_api
selected_model = gpt-5.4
provider_status_code = 429
provider_error_message = insufficient_quota
```

일반 agent 응답 생성은 사용자가 저장한 provider API key를 backend credential issue API로 발급받아 사용하고 있었다.

하지만 memory recall planner, memory extractor, mark-used attribution 같은 장기기억 보조 호출은 `runtime_context`를 넘기지 않아 사용자 key가 아니라 AI 서버 env key인 `HEYGENT_OPENAI_API_KEY`를 fallback으로 사용했다.

그 결과 사용자의 실제 응답 모델 호출은 정상이어도 memory 보조 호출만 서버 env key quota 문제로 실패할 수 있었다.

## 문제 원인

### 1. memory provider 호출에 runtime context 누락

기존 일반 agent 응답 경로는 provider 호출 시 다음 context를 전달했다.

- `user_id`
- `provider_name`
- `task_run_id`
- `model`

`OpenAIAPIProvider.respond_async()`는 이 context가 있으면 backend `/internal/ai/credentials/issue`를 호출해 사용자 저장 key를 발급받는다.

반면 memory provider client는 `respond_provider_with_retry()`를 호출하면서 runtime context를 넘기지 않았다.

### 2. OpenAI API provider의 credential 발급 조건이 task usage 기록에 묶여 있음

기존 `OpenAIAPIProvider`는 backend-issued credential을 사용하려면 `task_run_id`까지 필요했다.

memory recall처럼 task usage 기록 대상이 아니거나 session 중심으로 실행되는 보조 호출은 사용자 credential 발급 조건을 만족하기 어려웠다.

### 3. 로컬과 배포 서버의 실패 양상이 다르게 보일 수 있음

로컬 `.env`에 quota가 있는 key를 넣으면 memory 보조 호출이 성공할 수 있다.

하지만 배포 서버 env key quota가 없으면, 사용자가 별도 API key를 저장했더라도 memory 보조 호출은 계속 서버 env key로 실패했다.

## 작업 내용

### 1. memory runtime context helper 추가

memory 보조 호출에서 공통으로 사용할 runtime context 생성 helper를 추가했다.

- 기본 provider는 `openai_api_key`로 설정했다.
- task input과 settings snapshot에서 `provider_name`, `model`, `task_run_id`, `session_id`를 추출한다.
- user id가 있는 실제 task/session 경로에서만 runtime context를 만든다.

### 2. memory recall planner 사용자 credential 연결

- `LlmMemoryRecallPlanner.plan_recall()`에 `runtime_context` 인자를 추가했다.
- `attach_persistent_memory_context()`에서 task input 기반 runtime context를 생성해 recall planner provider에 전달한다.
- recall planner 보조 호출도 backend-issued user credential을 사용하도록 했다.

### 3. memory writeback extractor/reconciler 사용자 credential 연결

- `MemoryExtractionContext`에 `provider_name`, `step_run_id`를 추가했다.
- `MemoryReconciliationContext`에 `session_id`, `task_run_id`, `step_run_id`, `provider_name`, `model`을 추가했다.
- `ProviderMemoryExtractionClient.extract_memory_json()`과 `reconcile_memory_operation_json()`에서 runtime context를 provider 호출에 전달한다.
- WebSocket/HTTP session 완료 후 writeback 호출에서도 task input의 provider 정보를 넘긴다.

### 4. mark-used attribution 사용자 credential 연결

- `LlmMemoryUsageAttributionVerifier.verify_usage()`에 `runtime_context` 인자를 추가했다.
- `mark_used_recalled_memories()`에서 task input 기반 runtime context를 생성해 attribution provider에 전달한다.
- memory attribution 보조 호출도 사용자 저장 key를 사용하도록 했다.

### 5. OpenAI API provider credential 조건 완화

- backend-issued credential 발급 조건을 `user_id + provider_name`으로 완화했다.
- `task_run_id`가 있는 경우에만 usage recording을 수행한다.
- memory 보조 호출처럼 task usage 기록이 없는 경로도 사용자 credential로 provider 호출을 할 수 있게 했다.

### 6. runtime context가 있는 api-key provider의 env health check 우회

- `openai_api_key` provider는 env key가 없어도 사용자 runtime credential로 호출할 수 있다.
- runtime context가 있는 경우 provider live check가 env key 부재 때문에 실패하지 않도록 조정했다.

## 주요 커밋

```text
63fde29d AI-fix : 장기기억 사용자 credential 적용
```

## 주요 파일

- `ai/app/domain/orchestration/agent/memory/runtime_context.py`
- `ai/app/domain/orchestration/agent/memory/memory_extraction_provider.py`
- `ai/app/domain/orchestration/agent/memory/memory_recall_planner_provider.py`
- `ai/app/domain/orchestration/agent/memory/memory_usage_attribution_provider.py`
- `ai/app/domain/orchestration/agent/memory/memory_extractor.py`
- `ai/app/domain/orchestration/agent/memory/memory_reconciler.py`
- `ai/app/domain/providers/model/openai_api.py`
- `ai/app/api/memory_context.py`
- `ai/app/api/memory_writeback.py`
- `ai/app/api/memory_mark_used.py`
- `ai/app/api/ws/commands.py`
- `ai/app/api/http/sessions.py`

## 검증

memory credential propagation 관련 테스트:

```powershell
cd ai
.\.venv\Scripts\python.exe -m pytest -q tests/test_memory_writeback.py tests/api/test_memory_context.py tests/api/test_memory_mark_used.py tests/providers/test_openai_provider.py
```

결과:

```text
46 passed
```

참고:

- 더 넓은 회귀 테스트 묶음은 실행 중 중단되어 완료하지 못했다.

## 최종 결과

- localhost와 배포 서버의 일반 task/session 실행 경로에서 memory recall/writeback/mark-used 보조 LLM 호출이 사용자 저장 API key를 사용한다.
- 사용자 key가 backend에 저장되어 있고 AI 서버가 backend credential issue API에 접근 가능하면 memory 보조 호출은 env key를 타지 않는다.
- runtime context 없이 provider를 직접 호출하는 내부/테스트성 경로는 기존 env fallback이 남아 있다.
- 배포 서버에서 memory만 `HEYGENT_OPENAI_API_KEY` quota에 묶여 실패하던 구조를 제거했다.

## MR 작업내용

- 장기기억 보조 LLM 호출에 task/session/user/provider/model runtime context를 전달하도록 수정했다.
- memory recall planner, extractor, reconciler, mark-used attribution provider가 backend-issued user credential을 사용하도록 연결했다.
- OpenAI API provider의 credential 발급 조건을 task usage 기록과 분리했다.
- task usage 기록은 `task_run_id`가 있는 경우에만 수행하도록 조정했다.
- `openai_api_key` provider가 runtime credential 경로에서는 env key health check에 막히지 않도록 보강했다.
- memory context/writeback/mark-used API 테스트와 OpenAI provider credential 테스트를 추가했다.

## MR 확인 포인트

- 운영 task/session 경로에서는 memory 보조 호출이 사용자 저장 key를 사용한다.
- env fallback은 runtime context가 없는 직접 호출 경로에만 남아 있다.
- provider credential 발급 실패와 provider 호출 실패는 기존 observation detail로 확인할 수 있다.
- 이 변경은 장기기억 보조 호출 credential 경로만 다루며, worker/task 실행 개념 자체는 변경하지 않았다.
