# 시스템 개요

## 개요

HeyGent는 `frontend`, `backend`, `ai`, `mobile`, `bridge`를 하나의 저장소에서 관리하는 모노레포입니다.

사용자는 웹 또는 모바일에서 요청을 보냅니다. 백엔드는 인증, 사용자 정보, 외부 연동, 기기 정보를 관리합니다. AI 서버는 사용자의 요청을 `TaskRun`으로 실행하고, 실행 과정은 WebSocket으로 화면에 전달됩니다. 로컬 브릿지는 사용자의 PC에서 실행되어 AI가 제한된 범위의 파일/터미널 작업을 위임할 수 있게 합니다.

## 시스템 구성

| 영역 | 위치 | 책임 |
| --- | --- | --- |
| Frontend | `frontend/` | 웹 채팅, 대시보드, 작업 보드, 에이전트 시각화, 설정 화면 |
| Backend | `backend/` | 인증, 사용자, provider credential, memory, IoT, bridge, 외부 연동 API |
| AI | `ai/` | TaskRun/StepRun 실행, agent loop, 스킬/도구 런타임, realtime gateway |
| Mobile | `mobile/` | Android 채팅, 건강 데이터, FCM, 음성 입력 |
| Bridge | `bridge/` | 사용자 PC에서 로컬 파일/터미널 도구 실행 |
| Infra | `compose.yml`, `docker/` | Postgres, Redis, Mosquitto, 서비스 컨테이너 구성 |

## 대표 요청 흐름

### AI 채팅 실행

1. 사용자가 웹/모바일 채팅에서 요청합니다.
2. 프론트가 AI 서버에 세션 메시지 또는 TaskRun 실행 요청을 보냅니다.
3. AI 서버가 대화와 작업 컨텍스트를 구성합니다.
4. 모델이 답변만 할지, 작업 보드에 등록할지, 에이전트 오케스트레이션이나 도구를 사용할지 판단합니다.
5. 실행 이벤트가 저장되고 WebSocket으로 프론트에 전달됩니다.
6. 필요한 경우 모바일에는 FCM 알림도 전송됩니다.

### 로컬 브릿지 실행

1. 사용자가 웹에서 브릿지 페어링 코드를 발급합니다.
2. PC에서 브릿지 프로그램을 실행하고 코드를 입력합니다.
3. backend가 사용자와 브릿지 기기 연결을 저장합니다.
4. AI 서버가 브릿지 WebSocket 연결을 통해 로컬 도구 실행을 위임합니다.
5. 브릿지는 지정된 workspace 안에서만 파일/터미널 작업을 수행합니다.

### IoT 표시

1. AI 실행 상태가 변경됩니다.
2. AI 또는 backend가 표시 이벤트를 backend IoT API로 전달합니다.
3. backend가 MQTT topic으로 디스플레이 이벤트를 발행합니다.
4. 연결된 IoT 기기가 현재 작업 상태를 표시합니다.

## 내부 용어

| 용어 | 쉬운 설명 |
| --- | --- |
| TaskRun | 사용자 요청 하나를 처리하는 실행 묶음 |
| StepRun | TaskRun 안의 실행 단계 |
| AgentSession | AI 실행 중 오간 메시지 기록 |
| Agent Orchestration | 요청을 여러 단계와 역할로 나눠 실행 순서를 조율하는 구조 |
| Tool Runtime | AI가 터미널, 파일, 외부 API 같은 도구를 실행하는 계층 |
| Projection | DB 원본 데이터를 화면 조회에 맞게 빠르게 볼 수 있도록 Redis 등에 비춰둔 형태 |
| Fan-out | 하나의 이벤트를 여러 WebSocket 연결로 나눠 보내는 동작 |
