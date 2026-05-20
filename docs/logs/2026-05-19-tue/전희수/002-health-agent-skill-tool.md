# 작업 로그

## 날짜

2026-05-19

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Health-agent
- PR: 미생성

## 작업 목적

- 기본 제공 세션 에이전트에 헬스 에이전트를 추가하고, 헬스 스킬과 전용 runtime tool을 연결한다.
- 사용자의 컨디션/건강 데이터 참고 코칭 요청이 별도 의도분류 코드 없이 기존 세션 에이전트 라우팅 구조로 헬스 에이전트에 배정되도록 한다.

## 변경 요약

- `health-condition-check` 스킬과 참고 문서를 추가했다.
- `health.execute` runtime tool과 backend `/internal/ai/health/execute` 프록시를 추가했다.
- 기본 제공 에이전트 목록에 `health_agent`를 추가하고 `health-condition-check` 스킬을 연결했다.
- 헬스 toolset이 skill metadata 기반으로 runtime tool에 노출되도록 capability/runtime 등록을 확장했다.
- 헬스 에이전트와 스킬 설명을 발표/업무 중심 표현에서 사용자 건강정보, 생활 활동, 회복 상태, 활력 징후, 체성분을 아우르는 표현으로 확장했다.
- 헬스 스킬 description과 헬스 에이전트 description에 피로감, 운동 가능 여부, 하루 페이스 조절, 건강 데이터 추세 해석 같은 넓은 건강정보 요청 표현을 추가했다.
- 헬스 스킬 참고 문서를 한국어로 정리하고 수면, 활동량, 심박, 혈압, 체성분 관련 실제 연구/공공기관 링크를 추가했다.
- 수면, 활동량/칼로리, 심박/혈압, 체성분/안전문구 관점으로 나눠 서브에이전트 조사를 받은 뒤, 답변에서 근거를 짧게 언급할 수 있는 근거 라이브러리 형태로 정리했다.
- 헬스 스킬 기본 출력 형식을 `건강 데이터 요약`, `근거`, `주의할 점`, `추천 행동`, `참고` 순서로 정리하고, 근거 섹션은 "사용자 데이터 → 짧은 해석" 형태를 따르도록 했다.
- 프론트엔드 스킬 상세 모달 본문과 설명 영역에 텍스트 선택을 허용해 문서 내용을 복사할 수 있게 했다.
- 사용하지 않는 `docs/superpowers` 문서 디렉터리를 삭제했다.

## 주요 파일

- `ai/app/domain/agents/templates.py`
- `ai/app/skills/health/condition-check/SKILL.md`
- `ai/app/tools/health/health_tool.py`
- `ai/app/clients/backend_health.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/skills/health/condition-check/references/evidence-map.md`
- `ai/app/skills/health/condition-check/references/health-api-basics.md`
- `ai/app/skills/health/condition-check/references/response-policy.md`
- `frontend/src/components/sessionWorkspace/AgentSkillDetailDialog.tsx`
- `frontend/src/components/settings/SettingsDialog.tsx`
- `backend/src/main/java/com/ssafy/heygent/domain/health/controller/AiInternalHealthController.java`
- `backend/src/main/java/com/ssafy/heygent/domain/health/service/HealthService.java`
- `ai/tests/domain/test_agent_templates.py`
- `ai/tests/domain/test_capability_resolver.py`
- `ai/tests/tools/test_runtime_tools.py`
- `backend/src/test/java/com/ssafy/heygent/domain/health/controller/AiInternalHealthControllerTest.java`

## 테스트 / 확인

- `pytest tests/domain/test_capability_resolver.py -q`
- `pytest tests/tools/test_runtime_tools.py::test_runtime_exposes_health_execute_only_for_health_toolset tests/tools/test_runtime_tools.py::test_health_runtime_binds_owner_user_id_and_ignores_model_user_id -q`
- `pytest tests/domain/test_agent_templates.py -q`
- `./gradlew.bat test --tests com.ssafy.heygent.domain.health.controller.AiInternalHealthControllerTest`
- Docker compose 재빌드 후 Playwright로 `health routing verify` 세션을 열고 기본 제공 에이전트에 `헬스 에이전트`가 표시되는 것을 확인했다.
- Playwright 채팅 입력 `나 오늘 컨디션 좋은데 발표 마무리 잘 할수 있겠지?` 실행 결과, `TASK-2 · 오늘 컨디션 점검` 하위 작업이 생성되고 담당 `assigneeAgentId`가 `health_agent` 프로필과 일치하는 것을 API로 확인했다.

## 결정 / 이슈

- 별도 의도분류 로직은 추가하지 않았다. 기존 팀장 프롬프트의 세션 에이전트 라우팅 기준과 skill 설명 기반 배정 흐름을 그대로 사용했다.
- 로컬 검증 계정에 실제 OpenAI provider 연결이 없어, Playwright 라우팅 검증은 임시 mock Responses API와 테스트용 provider key로 수행한 뒤 정리했다.
- 전체 `ai/tests/domain/test_agent_templates.py` 중 기존 `gmail_agent` 설정과 충돌하던 테스트가 있었으나, 현재 변경 범위와 직접 관련 없는 기존 상태로 판단했다.
- 의료 진단, 치료 판단, 확정적 위험 판정은 금지하고 건강정보 기반 참고 코칭으로만 답하도록 스킬 참고 문서의 응답 정책을 정리했다.
- "의학적 조언"이라고 표현하지 않고 "일반 건강정보 참고이며 의학적 진단이나 치료 조언을 대체하지 않는다"로 제한한다.
- `tmp/AGENTS.md` 기준으로 커밋은 명시 승인이 있을 때만 진행한다.

## 다음 단계

- 실제 provider 연결 계정에서 mock 없이 같은 Playwright 흐름을 한 번 더 확인한다.
- 헬스 데이터 조회 endpoint가 늘어나면 `health.execute`에서 허용 endpoint와 스킬 참고 문서를 함께 확장한다.
