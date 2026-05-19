---
title: 검색 쿼리 패턴 (발신자 3 형태 + 카테고리 + 기간)
---

# 검색 쿼리 패턴

Gmail 검색은 `from:`, `subject:`, `category:`, `label:`, `newer_than:`, `older_than:`, `before:`, `after:` 등의 연산자를 지원한다. 본 스킬은 **발신자 화이트리스트 + 사용자 명시 조건** 두 가지로 쿼리를 만든다.

## 발신자 3 형태

호출 에이전트의 SENDERS.md 는 세 가지 섹션을 가진다. AI 는 셋 다 읽어 OR 결합해야 한다.

### 형태 1: 이메일 주소

`## 이메일 주소` 섹션의 각 줄을 그대로 `from:주소` 로.

```
- news@stratechery.com
- digest@theinformation.com
```

→ `from:news@stratechery.com OR from:digest@theinformation.com`

### 형태 2: 도메인

`## 도메인` 섹션. 앞의 `@` 는 빼고 `from:도메인` 으로.

```
- @stibee.com
- @maily.so
- @substack.com
```

→ `from:stibee.com OR from:maily.so OR from:substack.com`

### 형태 3: 보낸이 이름

`## 보낸이 이름` 섹션. Gmail 은 발신자 표시 이름(From 헤더의 이름 부분) 도 `from:` 으로 검색 가능.

- 공백 없으면 그대로: `from:UPPITY`
- 공백 있으면 따옴표: `from:"STARTUP WEEKLY"` (URL 인코딩 시 `%22` 사용)
- 한국어도 그대로: `from:"데이터 센터 및 IT업계 동향"`

```
- UPPITY
- STARTUP WEEKLY
- 데이터 센터 및 IT업계 동향
```

→ `from:UPPITY OR from:"STARTUP WEEKLY" OR from:"데이터 센터 및 IT업계 동향"`

### 세 형태 OR 결합 — 최종 쿼리 예

```
from:(news@stratechery.com OR stibee.com OR maily.so OR UPPITY OR "STARTUP WEEKLY" OR "데이터 센터 및 IT업계 동향") newer_than:7d
```

괄호는 한 번에 묶어도 되고, 각 항목을 `from:` 으로 따로 둬도 된다. 어느 쪽이든 결과는 같다.

## 기간 조건

사용자 표현 → 검색 연산자 매핑.

| 사용자 표현 | 검색식 |
|---|---|
| 오늘 | `newer_than:1d` |
| 어제 | `newer_than:2d older_than:1d` |
| 이번 주 / 최근 7일 | `newer_than:7d` |
| 이번 달 / 한 달 | `newer_than:30d` |
| 5월 / 4월 | `after:2026/05/01 before:2026/06/01` |
| N일 명시 | `newer_than:Nd` |

명시 안 했으면 기본 `newer_than:7d`.

## 카테고리 / 라벨

**기본은 카테고리 조건 추가 안 함.** 뉴스레터가 Updates / Promotions / Forums / Primary 어디로 갈지 사용자 설정·발신자에 따라 다르기 때문.

사용자가 명시적으로 말한 경우만 추가:

| 사용자 표현 | 검색식 |
|---|---|
| 업데이트 탭만 | `category:updates` |
| 프로모션 탭만 | `category:promotions` |
| 소셜 탭만 | `category:social` |
| 받은편지함 | `in:inbox` |
| 안 읽은 메일만 | `is:unread` |
| 별표 표시 | `is:starred` |
| 첨부 있음 | `has:attachment` |

사용자 정의 라벨(`Newsletters` 같은) 은 `label:이름` (공백·한글이면 `label:"My Letters"`).

## URL 인코딩 표

| 문자 | 인코딩 |
|---|---|
| 공백 | `+` (또는 `%20`) |
| `:` | `%3A` |
| `@` | `%40` |
| `(` `)` | `%28` `%29` |
| `"` | `%22` |
| `,` | `%2C` |
| 한국어 | UTF-8 → `%XX` |

## 명령 예시

### 예시 1: 화이트리스트 전체 + 최근 7일

쿼리:
```
from:(stibee.com OR maily.so OR UPPITY OR "STARTUP WEEKLY") newer_than:7d
```

명령:
```json
{
  "commands": [
    {
      "method": "GET",
      "endpoint": "/gmail/v1/users/me/messages?q=from%3A(stibee.com+OR+maily.so+OR+UPPITY+OR+%22STARTUP+WEEKLY%22)+newer_than%3A7d&maxResults=20"
    }
  ]
}
```

### 예시 2: 특정 발신자 1 명 + 한 달

```
from:news@stratechery.com newer_than:30d
```

```json
{
  "commands": [
    {
      "method": "GET",
      "endpoint": "/gmail/v1/users/me/messages?q=from%3Anews%40stratechery.com+newer_than%3A30d&maxResults=30"
    }
  ]
}
```

### 예시 3: 업데이트 탭만 + 화이트리스트

```
category:updates from:(stibee.com OR maily.so) newer_than:7d
```

```json
{
  "commands": [
    {
      "method": "GET",
      "endpoint": "/gmail/v1/users/me/messages?q=category%3Aupdates+from%3A(stibee.com+OR+maily.so)+newer_than%3A7d&maxResults=20"
    }
  ]
}
```

## 함정과 대응

| 증상 | 원인 | 대응 |
|---|---|---|
| 결과 0 건인데 메일은 있음 | `category:updates` 박힘. 메일이 Promotions/Primary 로 감 | `category:` 제거하고 발신자만으로 재검색 |
| 표시 이름이 정확히 안 잡힘 | 발신자가 "어피티 UPPITY <...@uppity.co.kr>" 처럼 결합형 | 도메인 (`uppity.co.kr`) 도 같이 OR |
| 한국어 이름 인코딩 오류 | 따옴표 안에 한글 + 공백 | UTF-8 인코딩 후 `%XX` 로 전체 |
| 30 개 초과 OR 결합 거부 | Gmail 쿼리 한계 | 화이트리스트를 30 개 이하로 추리거나 2 회로 나눠 호출 |
