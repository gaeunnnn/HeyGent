# 날짜

2026-05-14

# 작성자

전희수

# 관련 브랜치 또는 PR

AI-feat/AI-Skills-impl

# 작업 목적

Notion 스킬이 여러 보조 문서를 갖는 구조로 확장되면서, 사용자에게 로컬 경로/타입 같은 개발자 메타 정보가 아니라 서비스형 스킬 문서 탐색 UI를 제공한다.

# 변경 요약

- Notion 스킬 본문을 진입점 중심으로 정리하고, 상세 보조 문서를 스킬 폴더 아래에 추가했다.
- 스킬 상세 API에 사용자용 `documents` 응답을 추가해 문서 제목과 내용을 내려주도록 했다.
- 프론트 스킬 상세 모달을 왼쪽 문서 탐색기와 오른쪽 Markdown preview 구조로 개편했다.
- 기존 `키`, `타입`, `경로`, 파일 칩 중심의 개발자용 상세 UI를 제거했다.

# 주요 파일

- `AI/app/skills/integrations/notion/SKILL.md`
- `AI/app/skills/integrations/notion/`
- `AI/app/storage/postgres/skill_repository.py`
- `AI/app/contracts/agents.py`
- `AI/app/api/http/agents.py`
- `frontend/src/components/sessionWorkspace/AgentSkillDetailDialog.tsx`
- `frontend/src/apis/agents.ts`

# 테스트 또는 확인 내용

- `AI\.venv\Scripts\python.exe -m pytest AI\tests\storage\test_skill_repository.py AI\tests\domain\test_agent_templates.py AI\tests\domain\test_capability_resolver.py AI\tests\tools\test_notion_tool.py`
- `npm run build`
- `docker compose up -d --build ai frontend`
- `GET /ai/api/v1/ready`
- dev-login 토큰으로 `GET /ai/api/v1/skills/notion` 호출 후 `documents` 10개와 제목 순서 확인
- Playwright로 팀장 에이전트 스킬 탭에서 Notion 상세 모달 확인
- 데스크톱/모바일 viewport에서 왼쪽 문서 탐색기와 오른쪽 preview 렌더링 확인

# 결정, 이슈, 리스크

- 프론트에 Notion 전용 라벨을 하드코딩하지 않고, Markdown frontmatter의 `title` 또는 기본 문서명 규칙을 API에서 사용자용 제목으로 변환한다.
- `sourcePath`, `sourceType` 같은 로컬/개발자 메타 정보는 상세 모달에서 노출하지 않는다.
- 스킬 런타임은 여전히 `SKILL.md`를 진입점으로 사용하고, 세부 내용은 보조 문서를 필요할 때 읽는 구조로 유지한다.

# 다음 단계

- 다른 스킬에도 보조 문서가 늘어나면 같은 문서 탐색 UI를 재사용한다.
- 스킬 생성/편집 UI를 만들 때 문서 제목, 표시 순서, 연결 상태를 관리하는 서비스용 메타데이터를 별도로 확장한다.
