# 작업 로그

## 날짜

2026-05-19

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-setting
- PR: 미정

## 작업 목적

- 루트 `README.md`를 HeyGent 프로젝트 소개 문서로 바꾼다.
- 루트 README에서 링크할 수 있는 `docs/architecture/` 구조를 새로 만든다.

## 변경 요약

- `README.md`를 기존 짧은 실행 안내에서 HeyGent 상세 소개 문서로 교체했다.
- 커밋 로그와 기존 협업 문서 기준으로 7명 팀원별 담당 영역을 정리했다.
- 내부 용어인 TaskRun, StepRun, agent loop, tool runtime, bridge 등을 쉬운 설명과 함께 정리했다.
- `docs/architecture/` 아래에 overview, frontend, backend, ai, mobile, bridge, infra 문서를 추가했다.
- 팀원 프로필 이미지는 `docs/image/profiles/` 실제 파일로 연결했다.
- Playwright로 실제 개발 서버에 로그인하고 사용자 요청을 보낸 뒤 서비스 화면 이미지를 `docs/image/service/`에 추가했다.
- ERD 이미지는 `docs/image/db/erd-overview.png`로 정리하고 README Data Modeling 섹션에 연결했다.
- 이미지 폴더와 파일명은 `db`, `service`, `profiles`와 영어 kebab-case 기준으로 통일했다.
- README 본문에서 이미지 경로 안내, "추후 추가 예정" 같은 내부 관리용 문구를 제거했다.
- README 주요 기능 표의 채팅, 작업 보드, 오피스 시각화, 브릿지 화면을 실제 이미지로 연결했다.
- 기능 GIF, ERD, 아키텍처 이미지와 데모 링크는 추후 교체할 수 있도록 placeholder로 남겼다.

## 주요 파일

- `README.md`
- `docs/architecture/README.md`
- `docs/architecture/overview/system-overview.md`
- `docs/architecture/frontend/app-structure.md`
- `docs/architecture/backend/domain-map.md`
- `docs/architecture/ai/service-map.md`
- `docs/architecture/mobile/app-structure.md`
- `docs/architecture/bridge/local-bridge.md`
- `docs/architecture/infra/deployment-layout.md`
- `docs/image/db/erd-overview.png`
- `docs/image/service/dashboard.png`
- `docs/image/service/chat-real-request.png`
- `docs/image/service/answer-progress.png`
- `docs/image/service/office-visualization.png`
- `docs/image/service/bridge-settings.png`
- `docs/image/service/work-board.png`
- `docs/image/service/memory-1.png`
- `docs/image/service/memory-2.png`
- `docs/image/service/external-service-skills.png`
- `docs/image/profiles/`

## 테스트 / 확인

- `http://localhost:5173`에 Playwright로 접속해 dev-login 토큰을 설정하고 대시보드, 채팅, 진행 상태, 에이전트 상태, 브릿지 설정 화면을 캡처했다.
- 실제 요청 `HeyGent가 어떤 서비스인지 README용으로 쉬운 말로 3줄만 요약해줘.`를 보내고 AI 답변이 표시되는 것을 확인했다.
- 서브에이전트로 캡처 이미지가 설명과 맞는지 판독했다.
- Markdown 링크 경로와 이미지 파일 존재 여부를 확인했다.

## 결정 / 이슈

- `theundergroundt` 작성자 커밋은 동일 이메일 흐름을 고려해 김상지 작업 묶음에 포함했다.
- 기능 GIF, ERD, 아키텍처 이미지는 아직 실제 파일이 없으므로 placeholder로 유지했다.
- README 링크 대상은 루트 `docs/architecture/` 문서만 포함한다.
- `office-visualization.png`는 사용자가 추가한 오피스 시각화 이미지로 교체했고 README 기능 표의 "실시간 실행 시각화" 항목에 연결했다.
- `bridge-settings.png`는 브릿지 연결 전 화면이므로 "연결 성공"이 아니라 "다운로드와 새 연결 설정" 화면으로 설명했다.
- `chat-original.png`, `dashboard-original.png`는 README에서 사용하지 않는 이전 보관 이미지라 제거했다.

## 다음 단계

- 팀원별 역할 설명을 각 팀원이 직접 검토한다.
- 시연/아키텍처 이미지를 `docs/image/` 아래의 용도별 폴더에 추가한 뒤 README 경로를 교체한다.
- 브릿지 연결 성공 화면과 모바일/워치/IoT 실제 화면이 준비되면 README의 남은 placeholder를 교체한다.
