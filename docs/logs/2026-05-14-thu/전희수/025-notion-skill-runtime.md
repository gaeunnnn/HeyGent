# 작업 로그

## 날짜

2026-05-14

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: 현재 작업 브랜치
- PR: 미정

## 작업 목적

- AI 서버에서 연결된 Notion 워크스페이스를 skill 기반으로 사용할 수 있도록 backend internal API와 AI runtime tool을 연결한다.

## 변경 요약

- backend에 AI 내부 인증 토큰으로 호출하는 `POST /internal/ai/notion/execute` 엔드포인트를 추가했다.
- AI runtime에 `notion` toolset과 `notion.execute` 단일 실행 도구를 추가했다.
- Notion skill과 40개 지원 후보 endpoint 목록, 제외 endpoint, 실행 정책 문서를 추가했다.
- 모델 입력의 `userId`는 무시하고 TaskRun owner 기반 사용자 ID만 backend 호출에 사용하게 했다.

## 주요 파일

- `backend/src/main/java/com/ssafy/heygent/domain/notion/controller/AiInternalNotionController.java`
- `ai/app/clients/backend_notion.py`
- `ai/app/tools/notion/notion_tool.py`
- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/tools/runtime/toolsets.py`
- `ai/app/skills/integrations/notion/SKILL.md`
- `ai/app/skills/integrations/notion/`

## 테스트 / 확인

- `AI\.venv\Scripts\python.exe -m pytest tests\tools\test_notion_tool.py tests\clients\test_backend_notion_client.py tests\tools\test_runtime_tools.py::test_runtime_exposes_notion_execute_only_for_notion_toolset tests\tools\test_runtime_tools.py::test_notion_runtime_binds_owner_user_id_and_ignores_model_user_id tests\domain\test_capability_resolver.py -q`
- `backend\gradlew.bat test --tests com.ssafy.heygent.domain.notion.controller.AiInternalNotionControllerTest`
- `docker compose up -d --build backend ai`
- `GET /ai/api/v1/ready` ready 확인
- 컨테이너 내 `notion.execute`로 `POST /v1/search` 검색 smoke 확인
- `테스트용입니다` 임시 Notion 페이지 생성 후 생성된 페이지만 휴지통 처리하는 live smoke 확인

## 결정 / 이슈

- 46개 Notion endpoint를 개별 runtime tool로 만들지 않고 `notion.execute` 하나로 유지한다.
- `GET /v1/views`, file upload send/complete, OAuth token/introspect/revoke 6개는 1차 runtime scope에서 제외한다.
- 위험 작업 hard block은 1차에 넣지 않고 skill 정책으로 확인을 유도하며, 추후 approval 흐름이 안정화되면 확장한다.

## 다음 단계

- Notion 삭제/이동/스키마 변경 명령에 approval 연동 또는 allowlist 정책을 추가한다.
- 실제 프론트 세션 에이전트 선택 흐름에서 `notion` skill이 선택될 때 `notion` toolset이 붙는지 회귀 확인한다.
