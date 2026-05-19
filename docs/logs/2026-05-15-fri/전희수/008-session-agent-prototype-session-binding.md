# 작업 로그

## 날짜

2026-05-15

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Agent-skills
- PR: 미생성

## 작업 목적

- 세션 에이전트가 프로토타입 Artifact를 만들 때 부모 채팅 세션의 오른쪽 패널에 저장되도록 실행 문맥을 보강합니다.

## 변경 요약

- 세션 에이전트 실행 입력에 부모 채팅 `sessionId`를 전달하도록 수정했습니다.
- 사용자 메시지와 Artifact 버전을 연결할 수 있도록 `promptMessageId`도 자식 실행 입력에 전달합니다.
- 부모 세션 바인딩이 자식 실행에 유지되는지 회귀 테스트를 추가했습니다.

## 주요 파일

- `ai/app/domain/orchestration/agent/loop.py`
- `ai/tests/domain/test_skill_driven_work_tracking.py`

## 테스트 / 확인

- `python -m pytest ai\tests\domain\test_skill_driven_work_tracking.py ai\tests\tools\test_prototype_runtime_tool.py ai\tests\domain\test_capability_resolver.py -q`
- `python -m pytest ai\tests\tools\test_runtime_tools.py -q`

## 결정 / 이슈

- 다른 채팅이나 다른 화면으로 이동한 뒤 돌아와도 프론트는 해당 채팅의 active Artifact를 다시 조회합니다.
- 이번 부산 날씨 요청은 화면 이동 문제가 아니라 자식 실행의 Artifact 저장 대상 세션 바인딩 누락으로 실제 Artifact가 생성되지 않은 것이 원인이었습니다.
- 이미 완료된 실패 실행은 자동으로 Artifact가 생성되지 않으므로 같은 요청은 수정 반영 후 다시 실행해야 합니다.

## 다음 단계

- AI 컨테이너를 새 코드로 재기동한 뒤 같은 유형의 화면 생성 요청에서 Artifact가 생성되는지 확인합니다.
