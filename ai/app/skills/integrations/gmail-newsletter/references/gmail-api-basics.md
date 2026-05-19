---
title: Gmail API 기본 사용법
---

# Gmail API 기본 사용법

`gmail.execute` 도구는 backend Gmail 프록시(Composio 기반) 를 호출한다. Gmail REST API 의 모든 호출은 `/gmail/v1/` 로 시작한다. `userId` 같은 사용자 식별자는 모델 인자가 아니라 런타임이 바인딩한다 — 명령에 직접 넣지 않는다.

## 명령 형태

```json
{
  "commands": [
    {
      "method": "GET",
      "endpoint": "/gmail/v1/users/me/messages?q=category%3Aupdates&maxResults=20"
    }
  ]
}
```

규칙:

- 모든 endpoint 는 `/gmail/v1/` 으로 시작.
- `GET` 쿼리스트링은 `endpoint` 안에 인코딩해서 둔다. 한글이나 `:`, `@`, `&` 같은 문자는 URL 인코딩한다.
- `POST/PUT/PATCH` 의 바디는 `params` 객체로 둔다.
- 응답의 각 항목 `success` 필드를 매번 확인한다. 일부 실패가 다른 명령 결과를 무효화하지 않는다.

## 응답 형태

backend 가 돌려주는 형식:

```json
{
  "results": [
    {
      "success": true,
      "method": "GET",
      "endpoint": "/gmail/v1/users/me/messages?q=...",
      "data": {
        "messages": [{ "id": "...", "threadId": "..." }],
        "resultSizeEstimate": 3
      }
    }
  ],
  "success_count": 1,
  "failed_count": 0
}
```

실패는 `data` 대신 `errorCode`, `errorMessage` 에 들어온다.

## 자주 쓰는 엔드포인트 (읽기 전용)

### 메시지 검색

```
GET /gmail/v1/users/me/messages?q={검색식}&maxResults=20
```

`q` 는 Gmail 검색 문법 그대로. 자주 쓰는 토큰:

- `category:updates` — 받은편지함의 '업데이트' 카테고리.
- `category:promotions` / `category:social` — 다른 카테고리.
- `from:(주소1 OR 주소2)` — 발신자 OR 결합.
- `newer_than:7d` / `older_than:30d` — 기간 필터.
- `is:unread` — 읽지 않은 메시지만.
- `subject:"키워드"` — 제목 필터.
- `label:Newsletters` — 사용자가 만든 라벨 이름. 라벨에 공백이 있으면 `label:"My Letters"`.

### 메시지 상세

```
GET /gmail/v1/users/me/messages/{id}?format=full
```

- `format=full` 본문 포함.
- `format=metadata&metadataHeaders=From&metadataHeaders=Subject&metadataHeaders=Date` 헤더만.
- `format=minimal` 라벨/스레드 id 만.

### 스레드 상세

```
GET /gmail/v1/users/me/threads/{id}?format=full
```

같은 대화에 묶인 모든 메시지를 한 번에 가져온다.

### 라벨 목록

```
GET /gmail/v1/users/me/labels
```

사용자 정의 라벨 id 를 얻는다. `category:` 검색에는 라벨 id 가 필요 없지만, `label:` 검색이나 라벨 기반 modify 호출에는 라벨 id 가 필수다.

### 프로필

```
GET /gmail/v1/users/me/profile
```

연결된 Gmail 주소·메시지 총개수 확인용.

## 절대 호출하지 않는 엔드포인트 (이 스킬 범위 밖)

- `POST /gmail/v1/users/me/messages/send` — 메일 발송.
- `POST /gmail/v1/users/me/messages/{id}/modify` — 라벨 추가/제거.
- `POST /gmail/v1/users/me/messages/{id}/trash` — 휴지통 이동.
- `DELETE /gmail/v1/users/me/messages/{id}` — 영구 삭제.
- `POST /gmail/v1/users/me/filters` — 필터 생성.
- `POST /gmail/v1/users/me/labels` — 라벨 생성.
- `GET /gmail/v1/users/me/settings/...` — vacation/imap/pop 설정 읽기 자체는 안전하나 본 스킬과 무관.

사용자가 이런 작업을 명시적으로 요청한 경우에만, 사용자가 동의한 정확한 한 가지 작업만 수행하고 그 외 모든 mutation 은 거부한다.

## 본문 추출 팁

Gmail 메시지의 본문은 `payload.parts` 또는 `payload.body.data` 안에 base64url 로 인코딩돼 있다.

- 단일 파트: `payload.body.data` 디코딩.
- 멀티파트: `payload.parts[*]` 중 `mimeType == "text/plain"` 우선, 없으면 `text/html` 디코딩 후 태그 제거.
- base64url 디코딩 후 UTF-8 텍스트로 환원한다.
- 광고용 푸터(구독 해지 안내, 추적 픽셀, 광고 배너) 는 요약 단계에서 제거한다.

## 한 번에 보내는 명령 수

- 검색: 1 회.
- 메시지 상세: 8 ~ 12 통(검색 결과 상한). 명령 배열이 너무 길면 응답 페이로드가 커진다.
- 라벨/프로필 조회: 1 회씩.

배치를 나눌 때는 페이지네이션(`pageToken`) 을 사용한다:

```
GET /gmail/v1/users/me/messages?q=...&maxResults=20&pageToken=NEXT
```
