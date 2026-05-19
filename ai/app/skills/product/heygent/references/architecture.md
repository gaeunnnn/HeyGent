# Architecture

HeyGent는 monorepo 안에 frontend, backend, ai, mobile, bridge, docker를 함께 둔 구조입니다.

## Frontend

- React, Vite, TypeScript, Tailwind CSS 기반입니다.
- 채팅, 대시보드, 작업 보드, 설정, 에이전트 시각화를 제공합니다.
- WebSocket으로 AI 실행 상태를 실시간 구독합니다.

## Backend

- Spring Boot 기반 API 서버입니다.
- 인증, 사용자, 세션, 에이전트 프로필, 외부 연동 credential, 장기기억, IoT, 브릿지 도메인을 담당합니다.
- PostgreSQL, Redis, MQTT 인프라와 연결됩니다.

## AI Server

- FastAPI 기반 AI 서버입니다.
- TaskRun, StepRun, agent loop, skill runtime, tool runtime, WebSocket 이벤트 처리를 담당합니다.
- OpenAI와 Gemini 모델 provider를 사용할 수 있습니다.

## Mobile

- Android Kotlin, Jetpack Compose 기반입니다.
- 모바일 채팅, 로그인, 건강 데이터, FCM, STT 흐름을 제공합니다.

## Bridge

- 사용자 PC에서 실행되는 로컬 브릿지 프로그램입니다.
- 클라우드 AI가 제한된 로컬 워크스페이스 안에서 파일과 터미널 작업을 위임할 수 있게 합니다.

프로젝트 설명에서는 "하나의 AI 요청이 backend, AI server, frontend/mobile/IoT/bridge로 동시에 이어진다"는 점을 강조하면 좋습니다.
