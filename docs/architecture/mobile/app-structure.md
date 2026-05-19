# Mobile 구조

## 개요

모바일 앱은 Android Kotlin + Jetpack Compose 기반입니다. 웹과 같은 HeyGent 세션을 모바일에서도 사용할 수 있게 하고, 건강 데이터와 음성 입력을 연결합니다.

기준 위치: `mobile/app/src/main/java/com/example/mob`

## 주요 화면

위치: `MainActivity.kt`

- `Home`: 홈 화면
- `Chat`: AI 채팅 화면
- `Profile`: 사용자 프로필 화면

## 주요 패키지

| 패키지 | 역할 |
| --- | --- |
| `feature/auth` | 로그인 화면과 인증 흐름 |
| `feature/chat` | 모바일 채팅 UI와 메시지 처리 |
| `feature/health` | 건강 데이터 조회/표시 |
| `feature/home` | 홈 화면 |
| `feature/profile` | 프로필 화면 |
| `data/remote` | backend/AI API 호출 |
| `data/health` | Samsung Health 데이터 수집 |
| `fcm` | Firebase Cloud Messaging 수신 |
| `voice` | STT, WakeWord, 녹음/전사 흐름 |

## 주요 기능

- Kakao 로그인과 개발용 로그인
- 세션 목록/메시지 조회
- 채팅 메시지 전송
- FCM으로 AI 작업 완료 알림 수신
- Samsung Health / Galaxy Watch 데이터 수집 후 backend 전송
- Whisper STT 기반 음성 입력
- WakeWord 서비스 기반 음성 시작 흐름

## 기술 요소

- Kotlin
- Jetpack Compose
- Material3
- Retrofit / OkHttp
- Firebase Messaging
- Kakao SDK
- Samsung Health SDK
