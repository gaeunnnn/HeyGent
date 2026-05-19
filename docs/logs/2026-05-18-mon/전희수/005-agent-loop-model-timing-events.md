# Agent loop 모델 호출 타이밍 이벤트 추가

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 또는 PR

- `AI-feat/Agent-K-Skills`

## 작업 목적

- 단일 사용자 요청이 느릴 때 `TaskRun`, `StepRun`, 모델 호출, tool 호출이 각각 몇 초를 쓰는지 DB 이벤트 기준으로 재구성할 수 있게 한다.
- 기존에는 tool 이벤트와 task/step 이벤트는 있었지만 모델 호출 시작/종료 이벤트가 없어 `/v1/responses` 완료 로그만으로 정확한 호출별 소요 시간을 계산하기 어려웠다.

## 변경 요약

- agent loop의 provider 호출 직전에 `model.started` 이벤트를 emit한다.
- provider 응답 직후 `model.completed` 이벤트를 emit하고 `durationMs`, `finishReason`, `toolCallCount`, `messageCount`, `toolSchemaCount`, `usage`를 payload에 남긴다.
- provider 호출 실패 시 `model.failed` 이벤트를 emit하고 오류 타입과 메시지를 남긴다.
- 모델 호출 타이밍 이벤트 계약을 단위 테스트로 검증했다.

## 주요 파일

- `AI/app/domain/orchestration/agent/tool_calling_loop.py`
- `AI/tests/test_agent_tool_guard_loop.py`

## 테스트 또는 확인 내용

- `AI\.venv\Scripts\python.exe -m pytest ai\tests\test_agent_tool_guard_loop.py ai\tests\test_model_loop_contract.py -q`
- 결과: `47 passed`

## 결정, 이슈, 리스크

- 모델 호출 계측은 별도 로그 파일이 아니라 기존 TaskRun 이벤트 스트림에 남긴다.
- 이벤트 payload에는 모델 응답 원문이나 프롬프트 전문을 저장하지 않고, 시간과 크기 중심 메타데이터만 남긴다.
- 실제 병목 분석은 변경 반영 후 동일 프롬프트 실호출 1회로 수행한다.

## 다음 단계

- AI 컨테이너를 재빌드한 뒤 동일 부산 기상 프롬프트를 1회 호출한다.
- DB 이벤트를 시간순으로 추출해 model/tool/step/task 구간별 소요 시간을 계산한다.
