---
name: srt-booking
description: Search, reserve, inspect, and cancel SRT tickets in Korea with the SRTrain library. Use when the user asks for SRT seat availability, booking, canceling, or sold-out retry plans.
license: MIT
metadata:
  category: travel
  locale: ko-KR
  phase: v1
  runtime:
    required_toolsets:
      - skill-runtime
---

# SRT Booking

## What this skill does

`SRTrain` 위에서 SRT 좌석을 조회하고, 조건이 맞으면 예약과 취소까지 진행한다.

## When to use

- "수서에서 부산 가는 SRT 찾아줘"
- "내일 오전 SRT 빈자리 있으면 잡아줘"
- "예약 내역 확인해줘"
- "이 SRT 예약 취소해줘"

## When not to use

- 결제까지 자동으로 끝내야 하는 경우
- 비밀번호를 채팅창에 직접 보내려는 경우
- SRT가 아니라 KTX/Korail 예매인 경우

## Prerequisites

- Python 3.10+
- `python3 -m pip install SRTrain`
- `skill.run_script` runtime tool

## Required credentials

SRT 조회/예약/취소에는 SRT 계정 정보가 필요하다. `KSKILL_SRT_ID`에는 SRT 회원번호, 이메일, 휴대전화번호 중 하나를 넣을 수 있다.

- 이메일: `name@example.com`
- 휴대전화번호: `010-1234-5678`처럼 하이픈 포함 권장
- 그 외 값: 회원번호로 처리

K-agent 설정의 `SECRETS.md`에서 아래 섹션을 채운 뒤 저장한다.

```dotenv
## srt-booking

KSKILL_SRT_ID=
KSKILL_SRT_PASSWORD=
```

저장하면 서버가 값을 암호화하여 보관한다. 저장 후에는 입력한 값이 다시 노출되지 않는다.

필수값이 모두 저장되면 섹션 제목이 아래처럼 표시된다.

```md
## srt-booking (암호화 저장 완료)
```

아이디나 비밀번호 중 하나라도 비어 있으면 사용자에게 K-agent 설정의 `SECRETS.md`를 채워 저장하라고 안내한다. 채팅창에 비밀번호를 직접 입력하라고 요구하지 않는다.

## Inputs

- 출발역
- 도착역
- 날짜: `YYYYMMDD`
- 희망 시작 시각: `HHMMSS`
- 인원 수와 승객 유형
- 좌석 선호: 일반실 / 특실

## Runtime tool

실제 조회/예약/취소는 이 스킬에 포함된 `scripts/srt_booking.py`를 `skill.run_script`로 실행한다.

항상 아래 secret key를 요구한다.

```json
{
  "skill_name": "srt-booking",
  "script_path": "scripts/srt_booking.py",
  "required_secret_keys": ["KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD"]
}
```

`skill.run_script`가 `missing_skill_secrets`를 반환하면 사용자에게 K-agent 설정의 `SECRETS.md`에서 `srt-booking` 섹션을 저장하라고 안내한다. 채팅창에서 비밀번호를 받지 않는다.

`missing_dependency`가 반환되면 `SRTrain` 설치가 필요하다고 안내한다. 서버/컨테이너 실행 환경에서는 `python -m pip install SRTrain` 또는 이미지 의존성 추가가 필요하다.

## Workflow

### 1. Ensure credentials are available

K-agent 설정의 `SECRETS.md`에서 `KSKILL_SRT_ID`, `KSKILL_SRT_PASSWORD`가 저장되어 있는지 확인한다. 없으면 위 required credentials 안내에 따라 확보한다.

시크릿이 없다는 이유로 웹사이트를 직접 긁거나 다른 비공식 경로를 찾지 않는다.

### 2. Search first

먼저 조회해서 후보를 요약한다. 예시 tool call:

```json
{
  "skill_name": "srt-booking",
  "script_path": "scripts/srt_booking.py",
  "argv": [
    "search",
    "--departure", "수서",
    "--arrival", "부산",
    "--date", "20260328",
    "--time", "080000",
    "--time-limit", "120000",
    "--limit", "5"
  ],
  "required_secret_keys": ["KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD"]
}
```

### 3. Summarize options before side effects

예약 전에는 항상 아래를 짧게 정리한다.

- 출발/도착 시각
- 일반실/특실 가능 여부
- 예상 운임

### 4. Reserve only after the train is fixed

예약은 부작용이 있으므로 정확한 열차를 고른 뒤에만 진행한다.

`--train-index`는 직전 `search` 응답의 `trains` 배열 기준이다. `search`는 설명을 위해 매진 열차도 포함하므로, 예약 가능한 후보 중 가장 빠른 열차를 고를 때도 원래 search 목록에서의 index를 그대로 사용한다. 예약 결과의 열차 번호와 출발 시각이 선택한 후보와 다르면 즉시 불일치로 보고한다.

```json
{
  "skill_name": "srt-booking",
  "script_path": "scripts/srt_booking.py",
  "argv": [
    "reserve",
    "--departure", "수서",
    "--arrival", "부산",
    "--date", "20260328",
    "--time", "080000",
    "--time-limit", "120000",
    "--train-index", "0",
    "--adult-count", "1",
    "--seat", "general-first"
  ],
  "required_secret_keys": ["KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD"]
}
```

### 5. Inspect or cancel

취소 전에는 대상 예약을 다시 식별한다.

```json
{
  "skill_name": "srt-booking",
  "script_path": "scripts/srt_booking.py",
  "argv": ["reservations", "--limit", "20"],
  "required_secret_keys": ["KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD"]
}
```

```json
{
  "skill_name": "srt-booking",
  "script_path": "scripts/srt_booking.py",
  "argv": ["cancel", "--reservation-index", "0"],
  "required_secret_keys": ["KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD"]
}
```

## Done when

- 조회 요청이면 후보 열차가 정리되어 있다
- 예약 요청이면 예약 결과, 운임, 구입기한이 확인되어 있다
- 취소 요청이면 어떤 예약을 취소했는지 명확하다

## Failure modes

- 로그인 오류: 계정 정보나 SRT site policy 변경 가능성 확인
- 매진: 다른 시간대나 좌석 타입으로 재조회
- 네트워크 오류: 짧게 재시도하되 aggressive polling은 피하기

## Notes

- `SRTrain`은 SRT 전용 라이브러리라서 스킬 의도가 더 선명하다
- 결제 완료까지는 자동화하지 않는다
- 자동 재시도 루프는 계정 보호 차원에서 짧고 보수적으로 유지한다
