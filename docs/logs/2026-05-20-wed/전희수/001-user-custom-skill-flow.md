# 사용자 스킬 추가 흐름

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 또는 PR

AI-feat/Heygent

## 작업 목적

사용자가 에이전트 스킬 탭에서 직접 스킬을 만들거나 SKILL.md 본문을 가져와 등록한 뒤, 바로 해당 에이전트에 연결할 수 있게 한다.

## 변경 요약

- 사용자 정의 스킬 생성 API를 추가했다.
- 커스텀 스킬 본문과 참고 문서를 DB metadata에 저장하고, 런타임 registry에 즉시 등록하도록 연결했다.
- `skills.read_file`, `skill.execute inspect`가 파일시스템에 없는 커스텀 스킬 문서도 읽을 수 있게 했다.
- 에이전트 스킬 검색 영역 오른쪽에 스킬 추가 버튼과 생성 다이얼로그를 추가했다.
- 생성한 스킬은 현재 팀장/서브 에이전트의 선택 목록에 즉시 포함되도록 했다.

## 주요 파일

- `AI/app/api/http/agents.py`
- `AI/app/contracts/agents.py`
- `AI/app/storage/postgres/skill_repository.py`
- `AI/app/tools/runtime/local_tool_runtime.py`
- `frontend/src/components/sessionWorkspace/AgentDetailPanels.tsx`
- `frontend/src/components/sessionWorkspace/SessionWorkspaceDetailPanel.tsx`
- `frontend/src/components/sessionWorkspace/subAgents/SubAgentDetailView.tsx`
- `frontend/src/apis/agents.ts`

## 테스트 또는 확인 내용

- `AI\.venv\Scripts\python.exe -m py_compile AI\app\storage\postgres\skill_repository.py AI\app\api\http\agents.py AI\app\main.py AI\app\tools\runtime\local_tool_runtime.py`
- `AI\.venv\Scripts\python.exe -m pytest AI\tests\storage\test_skill_repository.py AI\tests\tools\test_runtime_tools.py -q`
- `npm run build`
- `docker compose up -d --build ai frontend`
- `docker compose up -d --build frontend`
- `GET http://localhost:8000/ai/api/v1/ready`
- `POST http://localhost:8000/ai/api/v1/skills`로 smoke 스킬 생성 후 상세 조회
- Playwright로 `http://localhost:5173/login` 렌더링 및 콘솔 error 0건 확인

## 결정, 이슈, 리스크

- 커스텀 스킬은 컨테이너 파일시스템에 쓰지 않고 DB metadata에 저장한다. Docker 재빌드로 파일이 사라지는 문제를 피하기 위한 결정이다.
- Git 레포 직접 import, zip import, 다중 참고 문서 편집은 이번 범위에서 제외했다.
- 프론트 빌드 전 `node_modules`에 lockfile 기준 의존성이 일부 빠져 있어 `npm install`로 복구했다.

## 다음 단계

- 필요하면 Git URL/zip import와 다중 참고 문서 관리를 별도 작업으로 확장한다.
- 실제 에이전트 실행까지 이어지는 E2E는 별도 시나리오로 추가 확인한다.
