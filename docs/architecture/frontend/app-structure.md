# Frontend 구조

## 개요

프론트엔드는 React 19, Vite, TypeScript 기반 웹 앱입니다. 채팅, 작업 보드, 에이전트 오케스트레이션 설정, 에이전트 시각화, 브릿지 설정 화면을 제공합니다.

## 라우트 구조

위치: `frontend/src/App.tsx`

| 경로 | 화면 |
| --- | --- |
| `/login` | 로그인 |
| `/auth/kakao/callback` | Kakao 로그인 callback |
| `/auth/notion/callback` | Notion 연결 callback |
| `/auth/gmail/callback` | Gmail 연결 callback |
| `/` | 대시보드 |
| `/new-chat` | 새 채팅 |
| `/session/:sessionId/*` | 세션 채팅과 작업 공간 |
| `/agent-status` | 내 사무실/건물 시각화 |
| `/agent-status/:sessionId` | 특정 대화 세션의 에이전트 시각화 |
| `/settings/bridge` | 로컬 브릿지 설정 |

## 주요 계층

### pages

- `DashboardPage`: 전체 대시보드
- `ChatSessionPage`: 세션 채팅 화면
- `AgentStatusPage`: 에이전트 이동/상태 시각화
- `BuildingOverviewPage`: 층과 세션 매핑 화면
- `BridgeSettingsPage`: 브릿지 연결/페어링 화면

### components

- `chat`: 채팅 메시지, 입력창, 실행 상태 표시
- `layout`: 좌측 사이드바와 공통 레이아웃
- `office`: 건물/사무실 시각화와 팀장 명령 UI
- `sessionWorkspace`: 에이전트 설정, 작업 보드, 실행 기록 패널
- `taskRuns`: StepRun 활동 패널과 실행 상태 UI
- `prototype`: AI가 만든 프로토타입 미리보기와 ZIP 다운로드
- `settings`: API key, provider, 외부 연동 설정

### store

Zustand로 전역 상태를 관리합니다.

- `useAuthStore`: 로그인과 토큰 상태
- `useChatStore`: 세션과 메시지
- `useTaskRunStore`: TaskRun/StepRun 실행 상태
- `useWorkStore`: 작업 보드 상태
- `useAgentVisualizationStore`: 에이전트 위치/상태 시각화
- `useBuildingMappingStore`: 층과 세션 매핑

### realtime

- AI WebSocket 연결
- TaskRun 이벤트 구독
- 세션 채팅 상태 복구
- 시각화 화면 상태 동기화

## UI 특징

- 좌측 사이드바 + 세션 작업 공간 중심 구조
- 채팅과 작업 보드가 같은 세션 컨텍스트를 공유
- 시각화 패널은 언마운트하지 않고 숨김 처리하여 에이전트 이동 상태를 유지
- FCM provider를 통해 모바일/웹 알림 흐름과 연결
