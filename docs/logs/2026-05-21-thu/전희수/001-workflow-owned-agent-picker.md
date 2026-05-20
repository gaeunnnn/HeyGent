# 작업 로그

## 날짜

2026-05-21

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: FE-feat/workflow-routine
- PR: 미정

## 작업 목적

- 워크플로우 작업 추가 시 세션에 보유하지 않은 제공 에이전트가 선택지에 노출되는 문제를 정리합니다.

## 변경 요약

- 워크플로우 에이전트 선택지를 세션 보유 에이전트 기준으로만 생성하도록 분리했습니다.
- 하드코딩 제공 선택지였던 기본 에이전트, 보안 에이전트와 기타 fallback 제공 에이전트 노출을 제거했습니다.
- 동일 선택지 로직을 검증하는 단위 테스트를 추가했습니다.

## 주요 파일

- `frontend/src/components/sessionWorkspace/work/board/workflowAgentChoices.ts`
- `frontend/src/components/sessionWorkspace/work/board/workflowAgentChoices.test.mjs`
- `frontend/src/components/sessionWorkspace/work/board/WorkflowTemplateEditor.tsx`
- `frontend/src/components/sessionWorkspace/work/board/WorkFlowDiagram.tsx`
- `frontend/src/components/sessionWorkspace/work/board/WorkflowPanel.tsx`

## 테스트 / 확인

- `node --test src/components/sessionWorkspace/work/board/workflowAgentChoices.test.mjs`
- `npm run lint`
- `npm run build`

## 결정 / 이슈

- 워크플로우 추가 모달은 팀장 에이전트와 제공 템플릿 목록을 보여주지 않고, 현재 세션에 보유한 에이전트만 표시합니다.
- 기존 템플릿에 assignee 없이 templateKey만 남아 있는 노드는 일반 `에이전트`로 표시됩니다.

## 다음 단계

- 실제 브라우저에서 워크플로우 추가 모달을 열어 보유 에이전트 목록만 노출되는지 최종 확인합니다.
