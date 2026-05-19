# 부산 기상 요청 병목 타이밍 분석

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 또는 PR

- `AI-feat/Agent-K-Skills`

## 작업 목적

- 부산 기상 요청 1회 실호출을 기준으로 `TaskRun`, `StepRun`, 모델 호출, tool 호출별 소요 시간을 분리해 병목 원인을 확인한다.

## 변경 요약

- 모델 호출 타이밍 이벤트 반영 후 동일 프롬프트를 프론트에서 1회 실행했다.
- DB 이벤트와 Docker 로그를 대조해 모델 호출, tool 호출, task/work 완료 시간을 계산했다.
- 상세 결과는 로컬 분석 파일에 남겼다.

## 주요 파일

- `tmp/병목TEST/model-timing-test-20260518.md`

## 테스트 또는 확인 내용

- 프론트 경로: `새 작업 요청하기` -> `기본 제공 에이전트`
- 입력: `부산 기상 관련 일주일 소식을 조사하고 나한테 말해줘`
- 세션: `session_020b4e85c345432dba06e4f1f10e7ee9`
- root task: `task_c1ac5c67a05b490e979b11f55c83c880`
- child task: `task_6b5a01579a6144229e1732f8111dc247`
- root work: `done`
- child work: `done`

## 결정, 이슈, 리스크

- 429, `/v1/models`, `web_search`는 이번 실행의 병목이 아니었다.
- 가장 큰 병목은 child 3번째 모델 호출이다.
  - duration: `29.267s`
  - input tokens: `66,027`
  - 원인: `http_get` 결과 원문이 agent transcript에 `167,137자`로 저장되어 다음 모델 입력에 그대로 들어갔다.
- child의 실제 `http_get` 호출은 `1.631s`로 짧았다.
- root 최종 재요약 모델 호출도 `8.643s`를 추가했다.
- task 완료 이후 memory writeback으로 추정되는 OpenAI 호출이 1회 더 있었다.

## 다음 단계

- tool result를 transcript에 넣기 전에 크기 제한 또는 요약을 적용한다.
- K-skill proxy 결과는 전체 raw JSON 대신 모델이 필요한 요약 형태로 줄인다.
- child 결과가 사용자 전달 가능하면 root 재요약을 줄이는 정책을 검토한다.
- memory writeback은 사용자 응답 후 비동기 후처리로 분리할 수 있는지 확인한다.
