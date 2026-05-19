# AI 장기기억 writeback 안정화 및 provider 계측

## 날짜

2026-05-16

## 작성자

김상지

## 대상 브랜치

- `AI-fix/memory-writeback-target-conflict4`

## 작업 배경

장기기억 writeback에서 다음 두 종류의 실패가 이어서 확인됐다.

- 후보 추출 이후 backend 저장 단계에서 `store_failed`가 발생하고 DB에는 새 memory가 남지 않는 문제.
- 선호/profile 저장 발화에서 `extract_failed`, `candidateCount=0`, `attempted=false`가 발생해 저장 후보 생성 전 단계에서 종료되는 문제.

초기 의심은 단순 provider 오류였지만, 코드와 DB 관측 결과 backend batch transaction 충돌과 memory 보조 LLM provider 설정 문제가 별도로 존재했다.

## 문제 원인

### 1. batch target 변경 충돌

한 사용자 발화에서 여러 memory 후보가 생성되고, `MemoryOperationReconciler`가 각각을 기존 memory `UPDATE` 후보로 바꾸는 경우가 있었다.

예시 흐름:

```text
candidate 1 -> targetMemoryId = 10 UPDATE
candidate 2 -> targetMemoryId = 10 또는 candidate 1의 additionalTargetMemoryIds와 겹침
```

backend `UserMemoryService.createCandidates()`는 후보 list를 하나의 transaction에서 순차 처리한다.

첫 UPDATE가 기존 target memory를 `INACTIVE` 처리한 뒤, 같은 batch의 다음 UPDATE가 같은 target 또는 이미 inactive 처리된 target 계열을 다시 변경하려 하면 `validateTargetCanChange()`에서 실패하고 transaction 전체가 rollback된다.

### 2. 저장 후보 생성 LLM 호출 실패

`Writeback.status=extract_failed`, `attempted=false`, `candidateCount=0`인 경우는 backend 저장 API까지 가지 않은 상태다.

이 경우 직접 원인은 memory extractor LLM 호출 실패다.

### 3. memory 보조 호출 provider/model 경로 불명확

기존 observation은 `memory_extractor_error`, `llm_planner_http_error` 정도만 보여줘 실제 어떤 provider/model로 몇 번 시도했는지 확인하기 어려웠다.

계측 추가 후 다음 값이 확인됐다.

```text
provider_name = openai_api
selected_model = gpt-5.4
retry_attempts = 3
provider_error_message = insufficient_quota 계열 오류
```

따라서 최종 런타임 실패는 저장 정책이나 target 충돌이 아니라 memory 보조 LLM 호출 provider/model/API key 설정 문제로 확정했다.

## 작업 내용

### 1. AI writeback target deconflict

- reconciled candidates 중 `UPDATE/MERGE/INVALIDATE`가 같은 `targetMemoryId` 또는 `additionalTargetMemoryIds`를 공유하면 뒤쪽 target-changing candidate를 skip한다.
- skip된 target과 candidate 수를 writeback observation에 남긴다.
- `ADD` 후보는 target 변경이 아니므로 유지한다.

### 2. backend batch 방어

- `UserMemoryService.createCandidates()`에서 batch 내부 target 변경 후보를 추적한다.
- 이미 같은 batch에서 변경된 target memory를 다시 변경하려는 후보는 skip한다.
- AI side deconflict가 누락되거나 다른 client가 중복 후보를 보내도 transaction 전체 rollback을 막는다.

### 3. backend error detail 관측

- `BackendMemoryClientError`가 HTTP status, backend error code, response message를 보존하도록 보강했다.
- writeback observation에 backend error detail을 노출해 `backend_memory_client_error`만으로 끝나지 않게 했다.

### 4. LLM-only 저장 판단 유지

- 단순 preference rule fallback 저장 시도는 요구사항과 맞지 않아 제거했다.
- 저장 후보 생성은 LLM extractor 판단만 사용한다.
- rule fallback은 recall planner의 조회 보정에만 남아 있으며, writeback 저장 판단에는 사용하지 않는다.

### 5. extractor prompt 보강

LLM이 durable memory를 더 잘 판단하도록 prompt 예시와 기준을 보강했다.

- 이름/호칭/역할은 `PROFILE`.
- 음식/응답 스타일/작업 방식 선호는 `PREFERENCE`.
- 반복되는 작업 습관은 성격에 따라 `PROFILE`, `INSTRUCTION`, `PROCEDURE`.
- 미완료 현재 task 요청은 저장하지 않음.
- 완료 또는 명시적으로 확인된 event는 `FACT/EVENT` 후보 가능.

### 6. 현재 요청 모델 전달

- recall planner provider에 task input의 `model`을 전달한다.
- writeback extractor context에 task input의 `model`을 전달한다.
- WebSocket/HTTP session 완료 후 writeback 호출에도 task model을 넘긴다.

### 7. provider retry 및 계측

- memory provider 호출에 retry/backoff를 적용했다.
- 실패 예외와 서버 로그에 다음 값을 남긴다.
  - `selected_model`
  - `provider_name`
  - `retry_attempts`
  - `max_attempts`
  - `provider_status_code`
  - `provider_error_message`
- `Recall.planner`, `Writeback`, `Mark Used.attribution` observation에 provider/model/retry/error detail을 노출한다.

### 8. WebSocket observation 반영 보강

- WebSocket 경로에서 writeback/mark_used observation 저장 후 최신 `taskRun.snapshot.result`를 다시 전송한다.
- UI가 최초 completed snapshot만 보고 `Writeback {}` / `Mark Used {}`처럼 오래된 값을 표시하는 문제를 줄였다.

## 주요 커밋

```text
ff9bdd71 AI-feat : 장기기억 target 충돌 방지
de0de985 AI-feat : 장기기억 호출 복구 강화
8e667abc AI-feat : 장기기억 LLM 자동 저장 판단
50277d0b AI-feat : 장기기억 LLM 판단 유지
3da60a81 AI-feat : 장기기억 recall 현재 모델 사용
4c957da9 AI-feat : 장기기억 writeback 현재 모델 사용
cd2a8b7f AI-feat : 장기기억 provider 계측 추가
```

## 주요 파일

- `ai/app/api/memory_writeback.py`
- `ai/app/api/memory_context.py`
- `ai/app/api/memory_mark_used.py`
- `ai/app/api/memory_observation.py`
- `ai/app/api/ws/commands.py`
- `ai/app/api/http/sessions.py`
- `ai/app/clients/backend_memory.py`
- `ai/app/domain/orchestration/agent/memory/memory_extractor.py`
- `ai/app/domain/orchestration/agent/memory/memory_extraction_provider.py`
- `ai/app/domain/orchestration/agent/memory/memory_recall_planner_provider.py`
- `ai/app/domain/orchestration/agent/memory/memory_usage_attribution_provider.py`
- `ai/app/domain/orchestration/agent/memory/provider_retry.py`
- `backend/src/main/java/com/ssafy/heygent/domain/memory/service/UserMemoryService.java`

## 검증

AI memory 관련 테스트:

```powershell
cd ai
.\.venv\Scripts\python.exe -m pytest tests/test_memory_extractor.py tests/test_memory_provider_retry.py tests/test_memory_writeback.py tests/api/test_memory_context.py tests/api/test_memory_mark_used.py tests/api/test_ws_commands.py tests/test_model_loop_contract.py
```

결과:

```text
107 passed
```

backend memory service 테스트:

```powershell
.\gradlew.bat test --tests "com.ssafy.heygent.domain.memory.service.UserMemoryServiceTest"
```

결과: 통과

## 최종 결과

- 같은 batch 안에서 동일 target memory를 여러 번 변경해 transaction 전체가 rollback되는 문제를 방지했다.
- 저장 후보 생성은 rule fallback 없이 LLM 판단으로 유지했다.
- memory 보조 호출의 provider/model/retry/error detail을 observation에서 확인할 수 있게 했다.
- provider credential/model 설정 수정 후 profile/preference 저장이 정상 동작하는 것을 확인했다.

## 남은 확인

- memory 보조 호출도 메인 응답 생성과 동일한 backend-issued credential/runtime context를 타도록 통합할지 검토가 필요하다.
- query-less recall fallback 결과가 넓게 들어오는 경우 rerank 또는 relevance cutoff가 필요할 수 있다.
