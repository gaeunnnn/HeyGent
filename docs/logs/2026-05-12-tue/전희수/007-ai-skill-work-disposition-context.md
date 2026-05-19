# 날짜

2026-05-12

# 작성자

전희수

# 관련 브랜치 또는 PR

AI-feat/skills-impl

# 작업 목적

k-skill 응답은 완료됐지만 2차 사이드바의 작업 보드에서 skill 작업이 `진행 중`으로 남는 문제를 수정한다.

# 변경 요약

- skill 실행 중 동적으로 생성된 work 연결 정보를 tool runtime context에 즉시 반영하도록 수정했다.
- `work_disposition` 도구가 자동 생성된 skill work의 `workId`를 읽지 못해 `work_context_required`로 실패하던 원인을 막았다.
- 동적 work 연결 정보가 `task_input`과 tool runtime context에 모두 동기화되는 단위 테스트를 추가했다.

# 주요 파일

- `ai/app/domain/orchestration/agent/tool_calling_loop.py`
- `ai/tests/test_model_loop_contract.py`

# 테스트 또는 확인 내용

- `python -m py_compile ai\app\domain\orchestration\agent\tool_calling_loop.py`
- `python -m pytest ai\tests\test_model_loop_contract.py ai\tests\tools\test_runtime_tools.py ai\tests\domain\test_work_service.py -q`
- `docker compose up -d --build ai`
- 실제 화면에서 k-skill 강남역 지하철 도착정보 요청을 실행하고, 신규 `TASK-2`가 작업 보드에서 `완료`로 표시되는 것을 확인했다.
- DB에서 신규 work item 상태가 `done`이고, run anchor의 `workDisposition.status`가 `done`으로 저장되는 것을 확인했다.

# 결정, 이슈, 리스크

- work 종료 상태가 없으면 확인 요청으로 남기는 정책은 유지했다.
- 이번 문제는 정책 자체가 아니라, 동적으로 붙은 work context가 tool runtime에 전달되지 않아 종료 상태 도구가 실패한 것이 원인이었다.
- 패치 전 생성된 기존 work item은 자동 보정하지 않는다.

# 다음 단계

- 서버 공용 fallback model provider가 없는 환경에서 memory recall/extraction 로그가 noisy하게 남는 별도 이슈는 필요 시 분리해서 처리한다.
