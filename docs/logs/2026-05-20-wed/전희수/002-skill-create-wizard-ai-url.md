# 스킬 생성 wizard 개선

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 또는 PR

AI-feat/Heygent

## 작업 목적

스킬 추가 화면을 내부 포맷 작성 폼이 아니라, 사용자가 이해하기 쉬운 `AI로 만들기`와 `URL로 가져오기` 흐름으로 바꾼다.

## 변경 요약

- 스킬 추가 진입점을 `AI로 만들기`, `URL로 가져오기` 두 개로 정리했다.
- 초안 생성 후 편집 화면을 `이름과 용도`, `작업 방식`, `참고 자료`, `최종 확인` 단계로 나눴다.
- 기본 화면에서 `스킬 키`, `SKILL.md`, `references/...` 같은 내부 용어를 숨기고, `고급 원문 보기`에서만 원문을 편집하게 했다.
- `POST /skills/draft`, `POST /skills/import-url` 초안 API를 추가했다.
- 초안 응답이 기존 `POST /skills` 저장 요청으로 바로 이어질 수 있게 계약을 맞췄다.
- 사용자 생성 스킬만 상세 모달에서 삭제할 수 있게 하고, 삭제 시 사용자 설정과 에이전트 연결도 함께 정리한다.

## 주요 파일

- `AI/app/api/http/agents.py`
- `AI/app/contracts/agents.py`
- `AI/tests/api/test_skill_draft_api.py`
- `AI/tests/fakes.py`
- `AI/app/storage/postgres/skill_repository.py`
- `AI/app/domain/orchestration/prompts/skill_prompt.py`
- `frontend/src/apis/agents.ts`
- `frontend/src/components/sessionWorkspace/AgentDetailPanels.tsx`
- `frontend/src/components/sessionWorkspace/AgentSkillDetailDialog.tsx`
- `frontend/src/components/sessionWorkspace/SessionWorkspaceDetailPanel.tsx`
- `frontend/src/components/sessionWorkspace/subAgents/SubAgentDetailView.tsx`

## 테스트 또는 확인 내용

- `AI\.venv\Scripts\python.exe -m py_compile AI\app\api\http\agents.py AI\app\contracts\agents.py AI\tests\fakes.py AI\tests\api\test_skill_draft_api.py`
- `AI\.venv\Scripts\python.exe -m pytest AI\tests\api\test_skill_draft_api.py AI\tests\storage\test_skill_repository.py AI\tests\tools\test_runtime_tools.py -q`
- `npm run build`
- `docker compose up -d --build ai frontend`
- `GET http://localhost:8000/ai/api/v1/ready`
- `GET http://localhost:5173/login`
- Playwright로 실제 세션의 `스킬` 탭에서 `스킬 추가` → `AI로 만들기` → 예시 선택 → `초안 만들기` 실행
- 실제 프론트 요청 `POST http://localhost:8000/ai/api/v1/skills/draft` 200 확인
- Docker AI 로그에서 사용자 인증 후 OpenAI `/v1/responses` 200 및 `/skills/draft` 200 확인
- `AI\.venv\Scripts\python.exe -m pytest AI\tests\api\test_skill_draft_api.py AI\tests\storage\test_skill_repository.py AI\tests\tools\test_runtime_tools.py -q`

## 결정, 이슈, 리스크

- 직접 작성 진입점은 제거했다. 원문 편집은 최종 확인의 고급 기능으로만 둔다.
- 초안 생성은 인증 사용자 credential 경로를 타야 한다. env fallback key로 호출하면 채팅과 다른 키를 사용하게 되어 실패 원인 판단이 흐려진다.
- AI 초안 생성은 20초 고정 제한 대신 모델 호출 설정을 기준으로 최대 120초까지 기다리게 했다.
- 삭제는 `sourceType=custom` 스킬에만 허용한다. 기본 제공 스킬은 삭제하지 않고 사용/미사용만 관리한다.
- URL 가져오기는 공개 URL만 허용하고 localhost URL은 차단한다.

## 다음 단계

- URL 가져오기에서 GitHub 폴더 후보 탐색과 다중 참고 자료 자동 묶기는 별도 작업으로 확장한다.
