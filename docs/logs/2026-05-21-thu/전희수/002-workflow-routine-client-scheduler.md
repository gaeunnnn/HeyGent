# 작업 로그

## 날짜

2026-05-21

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: FE-feat/workflow-routine
- PR: 없음

## 작업 목적

- 워크플로우를 루틴 탭에서 지정 시간 실행 대상으로 등록할 수 있게 한다.
- 서버 스케줄러 없이, 웹이 열려 있는 동안 클라이언트에서 지정 시간에 워크플로우 실행을 트리거한다.

## 변경 요약

- 세션 워크스페이스 메뉴와 라우트에 `루틴` 탭을 추가했다.
- 루틴 탭을 루틴 목록형 화면으로 구성하고, 생성 다이얼로그에서 워크플로우와 트리거를 고르는 흐름을 추가했다.
- 한 번 실행은 날짜/시간 단위로 예약하고, 반복 실행은 cron 기반 반복 설정을 사용한다.
- 세션 워크스페이스가 열려 있는 동안 로컬 저장소의 루틴을 확인해 지정 시각 또는 반복 조건에 맞춰 실행하는 러너를 추가했다.
- 워크플로우 수동 실행과 루틴 실행이 같은 실행 유틸을 쓰도록 공통화했다.

## 주요 파일

- `frontend/src/components/sessionWorkspace/SessionWorkspaceMenu.tsx`
- `frontend/src/components/sessionWorkspace/SessionWorkspaceDetailPanel.tsx`
- `frontend/src/components/sessionWorkspace/work/board/WorkflowRoutinePanel.tsx`
- `frontend/src/components/sessionWorkspace/work/board/WorkflowRoutineRunner.tsx`
- `frontend/src/components/sessionWorkspace/work/board/WorkflowRoutineScheduleEditor.tsx`
- `frontend/src/components/sessionWorkspace/work/board/workflowRoutineSchedule.ts`
- `frontend/src/components/sessionWorkspace/work/board/workflowTemplateRunner.ts`

## 테스트 / 확인

- `node --test src\components\sessionWorkspace\work\board\workflowRoutineSchedule.test.mjs`
- `node --test src\components\sessionWorkspace\work\board\workflowAgentChoices.test.mjs`
- `npm run lint`
- `npm run build`
- `docker compose up -d --build frontend`
- Playwright로 `/session/{sessionId}/workspace/routine` 화면에서 루틴 메뉴와 패널 노출 확인

## 결정 / 이슈

- 현재 루틴은 서버 영속 스케줄러가 아니라 브라우저가 열려 있는 동안만 동작하는 MVP로 구현했다.
- 루틴 저장소는 세션별 localStorage를 사용한다.
- 등록된 워크플로우가 없으면 루틴 생성 버튼은 비활성화된다.
- 반복 실행은 클라이언트에서 지원하는 5-field cron 표현식 기준으로 판단한다.

## 다음 단계

- 서버에서 백그라운드 실행이 필요해지면 루틴 저장/실행 API와 서버 스케줄러로 확장한다.
