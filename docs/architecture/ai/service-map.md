# AI 서비스 맵

## 개요

AI 서버는 FastAPI 기반입니다. 사용자의 요청을 TaskRun으로 실행하고, 모델 호출과 도구 실행을 반복하면서 결과를 만듭니다.

기준 위치: `ai/app`

## 엔트리 포인트

- HTTP API: `ai/app/api/http/`
- WebSocket API: `ai/app/api/ws/`
- 실행 도메인: `ai/app/domain/`
- 도구 런타임: `ai/app/tools/`
- 스킬 문서: `ai/app/skills/`

기본 로컬 주소:
- `http://localhost:8000/ai/api/v1`
- WebSocket: `/realtime/user/ws`
- Bridge WebSocket: `/internal/bridge/ws`

## 주요 API

### sessions

역할:
- 채팅 세션 생성
- 세션 메시지 전송
- 세션 목록/상세 조회
- 세션 삭제/복구

### tasks

역할:
- TaskRun 생성
- 실행 목록/상세/flow/steps/events 조회
- resume/cancel 처리

### work

역할:
- 작업 보드 조회/생성
- 작업 상태 변경
- 작업 담당 흐름 변경
- 댓글, 라벨, 문서, 관계, 결과물, 실행 이력 관리

### agents

역할:
- 기본 에이전트 템플릿 조회
- 에이전트 프로필 생성/수정/삭제
- 스킬 목록과 스킬 상세 조회
- agent secret 저장

### providers

역할:
- 모델 provider 상태 확인
- OAuth/API key 기반 provider 연결
- OpenAI/Gemini 실행 설정 연결

### prototypes

역할:
- AI가 만든 프로토타입 결과 조회
- 미리보기와 ZIP 다운로드 지원

## 핵심 도메인

### orchestration

AI 실행의 중심입니다.

- `agent loop`: 모델 호출과 도구 호출을 반복합니다.
- `capabilities`: 어떤 도구/스킬을 현재 요청에서 쓸 수 있는지 결정합니다.
- `runtime planning`: 실행 단계를 계획하고 StepRun 경계를 정리합니다.
- `delegation`: 역할에 맞는 실행 단위로 작업을 넘깁니다.

### tasks

- TaskRun 저장 계약
- StepRun detail
- 실행 lifecycle
- Redis projection과 Postgres durable 저장소 연결

### session

- 대화 기록
- 히스토리 압축
- AgentSession transcript 저장

### agents

- 기본 에이전트 템플릿
- 역할별 에이전트 템플릿
- agent secret 문서
- 스킬/도구 설명 주입

### work

- 작업 보드 모델
- 부모/자식 작업
- wake/recovery
- 작업 실행 결과와 문서/결과물

## 도구 런타임

| 도구 영역 | 설명 |
| --- | --- |
| `terminal` | 셸 명령 실행 |
| `file` | 파일 읽기/쓰기/patch/search |
| `planning` | 작업 단계 계획과 상태 기록 |
| `work` | 작업 보드 생성/수정/실행 |
| `delegation` | 역할 기반 작업 위임 |
| `notion` | Notion API 실행 |
| `gmail` | Gmail 검색/읽기/요약 흐름 |
| `messaging` | Mattermost 메시지 전송 |
| `prototype` | 디자인/프로토타입 생성 결과 관리 |
| `browser` / `web` | 웹 탐색, 검색, 브라우저 도구 |
| `skills` | 스킬 문서에 포함된 스크립트 실행 |

## 스킬 구조

스킬은 AI에게 "이런 작업은 이렇게 처리해라"라고 알려주는 실행 설명서입니다.

예시:
- `k-skills/srt-booking`: SRT 예약 자동화
- `integrations/gmail`: Gmail 작업
- `messaging`: Mattermost 연동
- `design`: 프로토타입/디자인 작업
- `web`: 웹 검색/탐색 작업
