# AI 장기기억 사용자 fact/event 저장 고도화

## 날짜

2026-05-16

## 작성자

김상지

## 대상 브랜치

- `AI-feat/memory-user-fact-event-storage`

## Jira 작업명

- `[AI] feat : 사용자 fact/event 장기기억 저장 고도화`

## MR 제목

- `[AI] feat : 사용자 fact/event 장기기억 저장 고도화`

## 작업 배경

장기기억 저장 안정화 이후, 단순 profile/preference 저장은 정상화됐지만 agent 서비스에서 자주 발생하는 요청 패턴을 더 정확하게 분류할 필요가 있었다.

특히 다음 케이스를 구분해야 했다.

- 현재 task 요청 자체는 장기기억으로 저장하지 않아야 한다.
- task 요청 안에 사용자 상태, 선호, profile fact, 향후 지시가 섞여 있으면 그 부분만 분리해 저장해야 한다.
- agent/tool 실행 결과가 성공했을 때는 요청 intent가 아니라 완료된 outcome만 event 또는 task state로 저장해야 한다.
- 반복 workflow는 새 task history가 아니라 `PROCEDURE`/`INSTRUCTION`으로 저장하거나 recall해야 한다.

## 작업 내용

### 1. 요청 기준일 context 전달

- `MemoryExtractionContext`에 `request_date`를 추가했다.
- memory writeback 호출 시 요청 기준일을 extractor context로 전달한다.
- provider payload의 `context.requestDate`에 요청 기준일을 포함해 LLM이 상대 날짜와 현재 상태 fact를 판단할 수 있게 했다.

### 2. 사용자 fact/event 저장 판단 보강

- LLM extractor prompt에 task 요청 안의 사용자 상태 fact를 분리해 저장하도록 기준을 추가했다.
- 예시:
  - `나 백엔드 면접 준비중인데 면접 준비 계획서 만들어줘`
  - 저장 대상: `사용자는 2026-05-16 기준 백엔드 면접을 준비 중이다.`
  - 저장 제외: `면접 준비 계획서 만들어줘`
- 사용자 경험, 일정, 현재 상태, 임시 제약, 건강/식단 제한, 여행 상태, 면접/구직 상태는 `FACT / AGENT_MEMORY / GLOBAL`로 저장하도록 가이드했다.

### 3. 현재 task request 비저장 기준 보강

- 미완료 현재 작업 요청은 장기기억으로 저장하지 않도록 prompt에 명시했다.
- 예시:
  - `오늘 이 부분 코드 개발해줘`
  - `부산 가는 KTX 예약해줘`
  - `이 문서 요약해줘`
- 단발 task request를 history처럼 저장해 memory가 오염되는 문제를 방지한다.

### 4. 완료된 agent 작업만 task state로 저장

- user request만으로는 project state를 저장하지 않는다.
- assistant 결과가 파일 변경, 테스트 통과, 커밋 생성, 구현 완료를 확인한 경우에만 완료된 작업 결과를 저장한다.
- 완료된 코드 작업은 `FACT / AGENT_MEMORY / WORKSPACE`, metadata category `task_state` 또는 `event`로 저장하도록 기준을 추가했다.

### 5. 예약/일정/도구 실행 성공 결과 저장

- 예약, 구매, 일정 등록, 이메일, 티켓, 파일 변경, 코드 변경 요청은 요청만으로 저장하지 않는다.
- assistant 또는 tool 결과가 성공을 확인하면 confirmed outcome만 `FACT / AGENT_MEMORY`로 저장한다.
- 예약/일정 결과는 다음 metadata를 사용하도록 가이드했다.
  - `metadata.eventTime`: 실제 일정/출발/예약 대상 시각
  - `metadata.sourceTimestamp`: 예약 완료 또는 확인 시각
  - `expiresAt`: 일정이 지난 뒤 stale 처리할 수 있는 시각
- 예시:
  - 요청: `부산 가는 KTX 예약해줘`
  - 성공 결과: `2026-05-20 09:00 서울역 출발 부산행 KTX 예약이 완료됐습니다.`
  - 저장: `사용자는 2026-05-20 09:00 서울역 출발 부산행 KTX를 예약했다.`

### 6. task 안에 섞인 preference/profile 분리 저장

- task 요청에 durable preference/profile fact가 함께 포함되면 task는 저장하지 않고 durable 부분만 저장하도록 했다.
- 예시:
  - `나는 짧은 답변 좋아하니까 이 문서 요약해줘`
  - 저장 대상: `사용자는 짧은 답변을 선호한다.`
  - 저장 제외: `이 문서 요약해줘`

### 7. 반복 instruction/procedure 저장 및 recall 보강

- 향후 assistant가 지켜야 하는 지시는 `INSTRUCTION`으로 저장한다.
- 반복 가능한 workflow 또는 프로젝트 절차는 `PROCEDURE`로 저장한다.
- 예시:
  - `앞으로 MR 정리할 때 테스트 결과 먼저 써줘` -> `INSTRUCTION / AGENT_MEMORY / GLOBAL`
  - `이 프로젝트에서는 항상 기능별 브랜치로 나눠서 작업해줘` -> `PROCEDURE / AGENT_MEMORY / WORKSPACE`
  - `우리 프로젝트 API 명세서 계속 Notion에 정리해줘` -> `PROCEDURE / AGENT_MEMORY / WORKSPACE`
- `지난번처럼 docs/logs 작업하고 커밋해줘`는 새 memory 후보를 만들기보다 기존 `PROCEDURE/INSTRUCTION` recall 대상으로 보도록 recall planner prompt와 테스트를 보강했다.

## 주요 커밋

```text
c029a5fd AI-feat : 장기기억 요청일 컨텍스트 전달
f1c8686b AI-feat : 사용자 fact 저장 판단 보강
8f31ac18 AI-feat : 사용자 fact recall 판단 보강
e2484edb AI-feat : 현재 task 요청 저장 제외 보강
8467909e AI-feat : 완료된 코드 작업 기억 기준 보강
78be0f7e AI-feat : 예약 성공 결과 기억 보강
e971fdfe AI-feat : agent 요청 분리 저장 기준 보강
fdf6ff29 AI-test : agent 반복 절차 기억 테스트 보강
```

## 주요 파일

- `ai/app/domain/orchestration/agent/memory/memory_extractor.py`
- `ai/app/domain/orchestration/agent/memory/memory_extraction_provider.py`
- `ai/app/api/memory_writeback.py`
- `ai/app/api/memory_context.py`
- `ai/tests/test_memory_extractor.py`
- `ai/tests/test_memory_writeback.py`
- `ai/tests/api/test_memory_context.py`

## 검증

Extractor 및 recall planner 테스트:

```powershell
cd ai
.\.venv\Scripts\python.exe -m pytest tests/test_memory_extractor.py tests/api/test_memory_context.py
```

결과:

```text
47 passed
```

브랜치 작업 중 전체 관련 회귀 확인:

```powershell
cd ai
.\.venv\Scripts\python.exe -m pytest tests/test_memory_extractor.py tests/api/test_memory_context.py tests/test_memory_writeback.py tests/api/test_memory_mark_used.py tests/api/test_ws_commands.py tests/test_model_loop_contract.py
```

결과:

```text
107 passed
```

## MR 작업내용

- 장기기억 extractor에 요청 기준일 `requestDate` context를 전달하도록 보강했다.
- task 요청 안에 포함된 사용자 fact/event/current state를 LLM이 분리해 저장할 수 있도록 prompt와 정규화 테스트를 추가했다.
- 미완료 task request, 단발 문서 요약/리서치/분석 요청은 저장하지 않도록 기준을 명확히 했다.
- task 요청 안에 섞인 preference/profile은 task와 분리해 durable memory만 저장하도록 보강했다.
- agent/tool 실행 성공 결과는 confirmed outcome만 `FACT/event` 또는 `FACT/task_state`로 저장하도록 보강했다.
- 완료된 코드 작업은 assistant 결과가 구현/테스트/커밋 완료를 확인한 경우에만 workspace `task_state`로 저장하도록 했다.
- 반복 workflow와 향후 지시는 `PROCEDURE`/`INSTRUCTION`으로 저장하고, `지난번처럼 docs/logs...` 같은 요청에서는 기존 절차 memory를 recall하도록 보강했다.
- extractor와 recall planner 테스트를 agent 요청 패턴별로 추가했다.

## MR 확인 포인트

- 저장 판단은 rule fallback이 아니라 LLM extractor 판단을 전제로 한다.
- 테스트의 fake provider는 LLM 응답을 흉내 내는 장치이며, rule 기반 후보 생성을 추가한 것이 아니다.
- `FACT` 아래 세부 분류는 새 `memory_type`을 추가하지 않고 `metadata.category`, `tags`, `ttl`, `scopeType`으로 처리한다.
- 미완료 요청 intent는 저장하지 않고, assistant/tool이 확인한 완료 outcome만 저장한다.

## 최종 결과

- agent 서비스에서 자주 발생하는 task request, user fact, preference, instruction, procedure, tool success outcome을 장기기억 정책으로 구분할 수 있게 됐다.
- memory 오염을 유발하는 단발 요청 저장을 방지하면서, 실제로 미래 응답 품질에 필요한 사용자 상태와 반복 절차는 저장/recall할 수 있게 됐다.
