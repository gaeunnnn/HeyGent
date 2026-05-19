---
title: 업데이트 라벨 + 발신자 검색 패턴
---

# 업데이트 라벨 + 발신자 검색 패턴

Gmail 받은편지함은 카테고리 탭으로 자동 분류된다:

- Primary
- Social → `category:social`
- Promotions → `category:promotions`
- **Updates → `category:updates`** ← 뉴스레터 대다수가 여기로 자동 분류됨
- Forums → `category:forums`

이 스킬은 기본적으로 `category:updates` 만 본다. 사용자가 다른 라벨(예: 직접 만든 `Newsletters` 라벨) 을 명시했다면 `label:Newsletters` 로 대체한다.

## 발신자 화이트리스트 결합

`references/newsletter-senders.md` 의 발신자 목록을 OR 로 묶는다.

- 이메일 형태(`news@example.com`) → `from:news@example.com`
- 도메인 형태(`@example.com`) → `from:example.com`
- 이름 포함(`Steve <s@apple.com>`) → 주소 부분만 추출 → `from:s@apple.com`

여러 발신자는 괄호로 묶고 `OR` 로 결합:

```
from:(news@stratechery.com OR substack.com OR notion.com)
```

도메인 앞의 `@` 는 Gmail 검색에서 생략한다.

## 기본 검색식 (한 줄로 결합)

기본은 **발신자만** OR 결합. 라벨 조건은 추가하지 않는다(뉴스레터가 Updates 가 아닌 다른 탭으로 분류되는 경우가 많기 때문).

```
from:(news@stratechery.com OR substack.com OR notion.com) newer_than:7d
```

URL 인코딩 후 `gmail.execute` 명령:

```json
{
  "commands": [
    {
      "method": "GET",
      "endpoint": "/gmail/v1/users/me/messages?q=from%3A(news%40stratechery.com+OR+substack.com+OR+notion.com)+newer_than%3A7d&maxResults=30"
    }
  ]
}
```

사용자가 **"업데이트 탭만"** 같이 명시했을 때만 `category:updates` 를 같이 결합:

```
category:updates from:(...) newer_than:7d
```

## 인코딩 규칙

- 공백 → `+`
- `:` → `%3A`
- `@` → `%40`
- `(` → `%28`, `)` → `%29`
- `&` → `%26`
- 한글은 UTF-8 후 `%XX` 인코딩.

## 기간 조정

- 기본: `newer_than:7d` (지난 7 일).
- 사용자가 "오늘" / "이번 주" / "어제" / "한 달" 같이 말하면 매핑:
  - 오늘 → `newer_than:1d`
  - 어제 → `newer_than:2d` 후 `older_than:1d` 결합
  - 이번 주 → `newer_than:7d`
  - 이번 달 → `newer_than:30d`
  - 사용자 명시 일수 → 그대로 사용.

## 결과 정렬

Gmail 의 `messages.list` 는 기본적으로 최신순. 별도 정렬 옵션 없음. 직접 정렬해야 한다면 각 메시지의 `internalDate` (epoch ms) 를 기준으로 한다.

## 흔한 함정

- **카테고리 탭이 꺼져 있는 사용자**: `category:updates` 가 빈 결과를 돌려줄 수 있다. 이 경우 `from:` 만으로 검색하고 사용자에게 안내한다.
- **너무 많은 발신자**: OR 결합이 길어지면 Gmail 이 거부할 수 있다. 30 개 이하로 유지.
- **발신자 화이트리스트 비어 있음**: 검색 자체를 실행하지 않는다. `references/newsletter-senders.md` 에 추가하라고 안내.
- **라벨 이름 검색**: `label:` 은 표시 이름을 받지만 공백/한글이 있으면 따옴표로 감싼다. `label:"내 뉴스레터"`.
