---
name: "gmail"
description: "사용자의 연결된 Gmail 계정에서 메일을 검색·조회·정리하는 범용 Gmail 스킬입니다. 발신자 화이트리스트(이메일/도메인/보낸이 이름 3 형태)와 자유로운 사용자 프롬프트(뉴스레터 정리, 특정 메일 찾기, 기간 조회 등) 모두 지원합니다. Composio Gmail 연결과 backend 프록시를 전제로 하며, 메일 발송·삭제·이동은 기본 작업 흐름에서 제외합니다."
metadata:
  category: integrations
  integration: gmail
  runtime:
    requires_toolsets: ["gmail"]
---

# Gmail Skill

## When to use

사용자가 자신의 Gmail 계정 메일을 다루는 요청을 했을 때 사용한다.

- "뉴스레터 정리해줘"
- "이번 주 ○○ 에서 온 메일 보여줘"
- "어제 받은 메일 요약해줘"
- "○○ 보낸 사람의 최근 메일 정리해줘"
- "업데이트 탭만 / 받은편지함 전체 / 프로모션 탭"

다음 작업은 이 스킬의 범위가 아니다.

- 메일 발송, 삭제, 이동 (사용자가 명시적으로 요청해도 본 스킬은 거부)
- 라벨 생성/수정/삭제
- 첨부 파일 업로드/다운로드
- OAuth 자체 설정·해제

## Runtime

필요한 runtime toolset: `gmail`. 핵심 도구는 `gmail.execute` 하나다. backend Gmail 프록시(Composio 기반) 를 통해 Gmail REST API(`/gmail/v1/...`) 를 호출한다. 모델 응답에 `userId` 를 절대로 넣지 않는다. 런타임이 인증된 사용자 식별자를 자동으로 바인딩한다.

상세 정보는 다음 참조 문서를 단계적으로 읽는다.

- `references/gmail-api-basics.md`: gmail.execute 명령 형태, 자주 쓰는 엔드포인트, 응답 해석.
- `references/search-patterns.md`: **발신자 3 형태(이메일/도메인/이름) 조합 + 카테고리·기간 검색 패턴**.
- `references/newspaper-template.md`: 여러 메일을 묶어 신문 형태 마크다운으로 정리할 때 형식.

## Workflow

### 1. 발신자 화이트리스트 확인 (필요한 경우)

호출 에이전트가 SENDERS.md 같은 발신자 문서를 가지고 있으면 그 문서를 먼저 읽는다. 문서가 없거나 사용자가 발신자를 명시했으면 그 값을 그대로 쓴다.

SENDERS.md 의 표준 섹션:

```
## 이메일 주소
- news@stratechery.com

## 도메인
- @stibee.com
- @maily.so

## 보낸이 이름
- UPPITY
- STARTUP WEEKLY
- 데이터 센터 및 IT업계 동향
```

### 2. Gmail 검색 쿼리 구성

`references/search-patterns.md` 의 규칙을 따른다.

- 발신자가 화이트리스트에 있으면 3 형태를 **모두** OR 결합한다.
- 사용자가 명시한 기간 조건을 더한다. 기본은 `newer_than:7d`.
- 사용자가 "업데이트 탭만" / "프로모션 탭만" 같이 명시하지 않은 한 `category:` 필터는 **추가하지 않는다**.
- 라벨이 사용자 정의 라벨일 때만 `label:라벨이름` 사용.

### 3. 메시지 상세 조회

검색 결과의 각 `messageId` 를 `GET /gmail/v1/users/me/messages/{id}?format=full` 로 받는다. **한 번에 5 통 이하** 가 안전. 더 많을 땐 2 ~ 3 회 나눠 보낸다.

본문 풀로딩은 메시지당 100KB ~ 500KB 라 한 번에 7 통 이상 동시 요청하면 backend Gmail 프록시 timeout 또는 Broken pipe 발생 가능.

### 4. 본문 정리 (압축 금지)

- 헤더(From, Subject, Date) 와 본문(HTML → 텍스트) 을 충분히 살린다.
- 1 ~ 3 문장으로 압축하지 말 것. 대신:
  - 한 줄 헤드라인 + 핵심 불릿 5 ~ 10 개로 본문 사실·수치·인용·인명·기업명을 그대로 옮긴다.
  - 본문에 등장한 외부 링크는 모두 보존 (최대 5 개).
- 광고성 문구, 구독 해지 안내, CTA 버튼, 푸터, 이미지 alt 만 제거.

### 5. 출력 형식 결정

사용자 요청에 따라:

- "신문/일보/정리" → `references/newspaper-template.md` 형식.
- "목록/리스트" → 간단한 표 또는 불릿.
- "○○ 찾아줘" → 매칭 메시지 1 ~ 3 통의 본문 상세.

기본은 신문 형식.

### 6. 전송 (선택)

사용자가 mattermost 채널을 명시했으면 `mattermost-send` 도구로 결과 마크다운을 전송한다. 그렇지 않으면 채팅으로만 회신.

### 7. 마무리

- 처리한 메시지 개수, 발신자별 건수, 매칭 없는 발신자 목록을 짧게 보고.
- 검색 쿼리도 한 줄 함께 보여주면 사용자가 다음 요청을 명확히 할 수 있다.

## Command Rules

- 모든 endpoint 는 `/gmail/v1/` 으로 시작.
- `GET` 의 쿼리스트링은 `endpoint` 안에 URL 인코딩해서 둔다.
- `POST/PUT/PATCH` 의 바디는 `params` 에 둔다 (이 스킬은 기본 GET 만 사용).
- 응답 각 항목의 `success` 필드를 반드시 확인.
- 한 번에 12 개 이하의 명령만 보낸다.
- **`POST /gmail/v1/users/me/messages/send`, `modify`, `trash`, `DELETE` 등 변경 작업은 절대 호출하지 않는다.** 사용자가 명시적으로 요청해도 본 스킬에서는 안 한다.
- 발신자 화이트리스트가 비었고 사용자도 발신자를 명시하지 않았으면 검색을 시작하지 않고 사용자에게 발신자 입력을 요청.

## First Scope

이 스킬의 첫 범위는 **읽기 위주** 다.

- 지원: `messages.list`, `messages.get`, `threads.get`, `labels.list`, `users.getProfile`.
- 제외: 발송, 삭제·이동, 라벨 수정, 필터 생성, IMAP/POP/Vacation 설정, 인증서 관리.
