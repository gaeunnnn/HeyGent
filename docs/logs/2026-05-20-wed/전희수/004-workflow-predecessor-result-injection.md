# 작업 로그

## 날짜

2026-05-20

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-refactor/pipeline-AI
- PR: 미생성

## 작업 목적

- strict workflow에서 후행 하위 작업이 선행 하위 작업 결과를 실제 입력으로 받지 못해 일반적인 플레이스홀더 산출물을 만드는 문제를 수정한다.

## 변경 요약

- workflow child 입력 생성 시 `blocks` 관계의 선행 WorkItem 최신 TaskRun 결과를 수집한다.
- 수집한 선행 결과를 `workflowPredecessorResults`와 child prompt의 `## 선행 하위 작업 결과` 섹션에 주입한다.
- 후행 child가 "앞선 요약을 바탕으로" 같은 지시를 받을 때 실제 선행 산출물을 참고할 수 있게 했다.

## 주요 파일

- `ai/app/domain/orchestration/agent/loop.py`
- `ai/tests/domain/test_skill_driven_work_tracking.py`

## 테스트 / 확인

- `python -m pytest tests/domain/test_skill_driven_work_tracking.py -k workflow_child_input_includes_completed_blocker_result`
- `python -m pytest tests/domain/test_skill_driven_work_tracking.py tests/tools/test_runtime_tools.py tests/domain/test_work_service.py`

## 결정 / 이슈

- 이번 수정은 workflow child 실행 입력 보강에 한정한다.
- 실제 화면 artifact 생성 여부는 child 지시와 사용 가능 toolset 정책에 좌우되므로 별도 확인이 필요하다.

## 다음 단계

- AI 컨테이너를 재빌드한 뒤 같은 workflow를 다시 실행해 `TASK-6` 입력에 `TASK-5` 결과가 포함되는지 확인한다.
