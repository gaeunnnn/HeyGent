---
title: 워크플로우 레시피
---

# 워크플로우 레시피

이 문서는 사용자의 요청 유형별로 실행해야 하는 `gmail.execute` 명령 체인 예시를 모은다. SKILL.md 의 "Workflow" 항목이 흐름이라면, 이 문서는 흐름의 구체 명령 단위 사용 예시다.

## 레시피 1: "오늘/이번 주 뉴스레터 정리해줘"

### 단계 1: 발신자 화이트리스트 읽기

`skills.read` 로 `references/newsletter-senders.md` 를 읽고 `- ` 로 시작하는 줄을 추출한다.

### 단계 2: 검색

```json
{
  "commands": [
    {
      "method": "GET",
      "endpoint": "/gmail/v1/users/me/messages?q=category%3Aupdates+from%3A(substack.com+OR+stibee.com+OR+maily.so)+newer_than%3A7d&maxResults=20"
    }
  ]
}
```

응답 구조:

```json
{
  "messages": [
    { "id": "abc123", "threadId": "thr456" },
    ...
  ],
  "resultSizeEstimate": 5
}
```

### 단계 3: 메시지 상세 일괄 조회

검색에서 얻은 message id 들로 한 번에 다중 명령을 보낸다.

```json
{
  "commands": [
    { "method": "GET", "endpoint": "/gmail/v1/users/me/messages/abc123?format=full" },
    { "method": "GET", "endpoint": "/gmail/v1/users/me/messages/def456?format=full" }
  ]
}
```

### 단계 4: 본문 추출 + 요약

각 메시지에서:

- `payload.headers` 에서 `From`, `Subject`, `Date` 헤더 추출.
- `payload.parts[*]` 에서 `mimeType == "text/plain"` 우선, 없으면 `text/html` 디코딩(base64url) 후 HTML 태그 제거.
- 본문을 1 ~ 3 문장 한국어 요약. 광고/구독 해지 안내 제거.

### 단계 5: 신문 마크다운 조립

`references/newspaper-template.md` 의 골격 따라 마크다운 조립.

### 단계 6: mattermost 전송

`mattermost.send` 도구 사용:

```json
{
  "target": "backend",
  "message": "{신문 마크다운 전체}"
}
```

대상 채널이 모호하면 사용자에게 확인.

### 단계 7: 보고

```
처리한 메시지 5건 / 누락된 발신자 0명 / mm 채널 backend 로 전송 완료
```

## 레시피 2: "특정 발신자만 정리해줘"

사용자가 명시한 발신자(`from:notion.com` 같은) 만 OR 안에 둔다. 화이트리스트 파일은 무시.

## 레시피 3: "뉴스레터 발신자 추가하고 싶어"

`newsletter-senders.md` 가 사용자가 직접 편집하는 칸이라는 점을 안내. 스킬은 자동 편집하지 않는다(편집 기능은 별도 도구로 처리).

## 레시피 4: "뉴스레터 발신자 목록 보여줘"

`skills.read` 로 `references/newsletter-senders.md` 의 "📝 발신자 목록" 섹션을 읽어 사용자에게 마크다운 그대로 회신.

## 레시피 5: "지난 정리 다시 보여줘"

이 스킬은 신문을 저장하지 않는다. 세션 메시지 이력에 남아 있으면 그것을 인용하고, 없으면 "다시 정리해 드릴까요?" 라고 묻는다.

## 흔한 실패와 대응

| 증상 | 원인 | 대응 |
|------|------|------|
| 검색 결과 0개 | 카테고리 탭 끔, 기간 너무 짧음, 발신자 잘못 표기 | 기간을 늘리거나 `category:updates` 제거하고 `from:` 만으로 재시도 |
| backend 401/403 | OAuth 만료 | 사용자에게 "Gmail 재연결 필요" 안내. 자동 재시도 금지 |
| 본문 디코딩 실패 | 비정상 멀티파트 / 첨부 | 헤더만 사용해 요약. 본문 누락 표시 |
| mattermost 전송 실패 | 채널 alias 오타 | 사용자에게 채널명 확인 |
