# Gemini 프로바이더 실행 연결 및 선택 UI 추가

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

기존 에이전트 실행 흐름은 OpenAI 계열 provider만 전제로 동작했다.

사용자가 UI에서 Gemini API key를 등록하고 팀장/서브 에이전트별로 Gemini 모델을 선택해 실행할 수 있도록, 기존 OpenAI 흐름 옆에 provider 선택 분기를 추가했다.

기존 OpenAI 실행 흐름은 기본 fallback으로 유지하고, Gemini provider/model이 명시된 경우에만 Gemini runtime을 타도록 구성했다.

## 작업 내용

### 1. AI runtime Gemini provider 추가

- `gemini_api` runtime provider를 추가했다.
- backend credential issue API에서 사용자 저장 Gemini API key를 발급받아 사용하도록 연결했다.
- Gemini `generateContent` 요청/응답 변환을 구현했다.
- Gemini function call 응답을 기존 agent loop tool call 계약에 맞게 변환했다.
- Gemini 사용량 정보를 backend usage 기록으로 전달할 수 있도록 연결했다.

### 2. provider 선택 라우팅 추가

- `openai`, `openai_api_key`, `openai_dev_fallback`은 기존 OpenAI runtime provider로 매핑했다.
- `gemini`, `gemini_api_key`는 신규 Gemini runtime provider로 매핑했다.
- task/profile runtime context의 `provider_name` 또는 Gemini 모델명(`gemini-*`)을 보고 실행 provider를 선택하도록 했다.
- provider 값이 없으면 기존처럼 OpenAI runtime을 기본 provider로 사용한다.

### 3. backend 사용자 API key provider 확장

- `gemini_api_key` provider를 backend provider enum과 모델 목록에 추가했다.
- UI에 등록된 사용자 API key를 credential issue 응답으로 내려주도록 user-managed API key provider 처리를 공통화했다.
- OpenAI 서버 공용 fallback은 명시적으로 `openai_dev_fallback` provider를 탈 때만 사용하도록 정리했다.

### 4. Gemini request schema 보정

- Gemini API key를 URL query string이 아니라 `x-goog-api-key` header로 전달하도록 변경했다.
- Gemini가 거부하는 tool JSON schema 항목을 제거했다.
- schema 정리 후 남은 `properties` 기준으로 `required` 배열을 다시 필터링해 `property is not defined` 오류를 방지했다.
- Gemini HTTP 오류 응답은 API key를 마스킹한 뒤 노출하도록 보정했다.

### 5. FE provider/model 선택 UI 추가

- 팀장 에이전트 설정 화면에 OpenAI/Gemini provider 선택을 추가했다.
- provider 선택에 따라 OpenAI/Gemini 모델 목록을 필터링한다.
- 서브 에이전트 생성/설정 화면도 OpenAI/Gemini provider와 모델 조합을 선택할 수 있게 수정했다.
- Gemini 모델 저장 후 재조회 시 provider가 OpenAI로 돌아가 보이지 않도록 저장 상태를 보정했다.

### 6. 실행 기록 LLM 표시 보정

- runs 탭에서 `openai`로 고정 표시되던 값을 제거했다.
- `taskRun.input_payload.provider_name` / `providerName`과 `model`을 우선 표시하도록 변경했다.
- result payload metadata와 session settings는 fallback으로만 사용한다.
- 팀장 실행 기록과 서브 에이전트 실행 기록 모두 동일한 기준으로 표시한다.

## 주요 커밋

```text
38c8a809 AI-feat : Gemini 프로바이더 실행 연결
972ee6fb AI-feat : provider 모델 조합 보정
677c56aa AI-feat : OpenAI dev fallback 보정
f812aba0 AI-feat : UI 등록 키 우선 사용
bf52a5a9 AI-feat : 메인 공급자 선택 추가
3dd81cc9 AI-feat : Gemini 저장 상태 보정
b960bb62 AI-feat : Gemini 요청 오류 보정
1b563a12 AI-feat : Gemini required 스키마 정리
8c75c809 FE-feat : 실행 기록 LLM 표시 보정
```

## 주요 파일

- `ai/app/domain/providers/model/gemini_api.py`
- `ai/app/domain/providers/registry/provider_registry.py`
- `ai/app/domain/orchestration/agent/tool_calling_loop.py`
- `ai/app/domain/orchestration/agent/loop.py`
- `ai/app/api/ws/commands.py`
- `ai/app/api/session_agent_profiles.py`
- `backend/src/main/java/com/ssafy/heygent/domain/ai/openai/model/OpenAiProviderName.java`
- `backend/src/main/java/com/ssafy/heygent/domain/ai/openai/service/OpenAiCredentialIssueService.java`
- `frontend/src/components/sessionWorkspace/SessionWorkspaceDetailPanel.tsx`
- `frontend/src/components/sessionWorkspace/subAgents/SubAgentDraftForm.tsx`
- `frontend/src/components/sessionWorkspace/subAgents/subAgentConfigOptions.ts`
- `frontend/src/components/sessionWorkspace/agentRuns/AgentRunsPanel.tsx`
- `frontend/src/components/sessionWorkspace/subAgents/SubAgentDetailView.tsx`

## 테스트 / 확인

Backend credential issue 테스트:

```powershell
cd backend
.\gradlew.bat test --tests "com.ssafy.heygent.domain.ai.openai.service.OpenAiCredentialIssueServiceTest"
```

AI provider/agent loop 관련 테스트:

```powershell
cd ai
.\.venv\Scripts\python.exe -m pytest tests\providers\test_openai_provider.py tests\providers\test_gemini_provider.py tests\test_model_loop_contract.py tests\test_agent_tool_guard_loop.py tests\tools\test_agent_loop_registry.py
```

결과:

```text
51 passed
```

Frontend build:

```powershell
cd frontend
npm run build
```

결과:

```text
성공
```

## MR 작업내용

- Gemini API key provider와 Gemini runtime provider를 추가했다.
- 팀장/서브 에이전트 설정에서 OpenAI/Gemini provider와 모델을 선택할 수 있게 했다.
- provider/model 설정을 task runtime context에 전달해 실행 시 OpenAI 또는 Gemini provider를 선택하도록 했다.
- Gemini function calling 요청 schema를 Gemini API 요구사항에 맞게 정리했다.
- Gemini API 오류 응답을 key 노출 없이 확인할 수 있도록 보정했다.
- backend credential issue에서 UI에 등록된 사용자 API key를 provider별로 발급하도록 정리했다.
- runs 탭의 사용 LLM 표시가 실제 task provider/model을 반영하도록 수정했다.

## MR 확인 포인트

- 기존 OpenAI provider를 선택하면 기존 OpenAI runtime provider를 사용한다.
- Gemini provider와 `gemini-2.5-pro` 또는 `gemini-2.5-flash` 모델을 선택하면 Gemini runtime provider를 사용한다.
- 배포 환경에서는 사용자가 배포 DB에 Gemini API key를 UI로 다시 등록해야 한다.
- 배포 frontend의 `VITE_AI_API_BASE_URL`, `VITE_AI_WS_BASE_URL`이 localhost로 남아 있으면 안 된다.
- AI 서버 CORS/WS allowed origins에 배포 frontend origin이 포함되어야 한다.
- AI 서버 컨테이너에서 Google Gemini API로 outbound HTTPS 요청이 가능해야 한다.
- 서버 공용 OpenAI fallback은 `openai_dev_fallback` provider를 명시적으로 사용할 때만 탄다.
- memory 보조 호출의 완전한 Gemini-only 전환은 이번 작업 범위가 아니다.

## 결정 / 이슈

- 기존 OpenAI-only 기본 실행 흐름을 유지하기 위해 provider 값이 없으면 OpenAI runtime을 기본값으로 둔다.
- Gemini는 user-managed API key provider(`gemini_api_key`)로만 연결한다.
- Gemini API key는 문서와 로그에 남기지 않는다.
- Claude provider enum/UI 등록 형태는 일부 열려 있지만, Claude runtime provider 구현은 이번 작업 범위가 아니다.

## 다음 단계

- MR 생성 시 위 MR 제목과 작업내용을 사용한다.
- 배포 서버에서 backend/ai/frontend 이미지를 모두 재빌드한다.
- 배포 계정으로 Gemini API key를 UI에서 등록한 뒤 팀장/서브 에이전트 Gemini 실행을 확인한다.
- 필요하면 memory 보조 호출 provider도 Gemini 선택을 따르도록 후속 작업으로 분리한다.
