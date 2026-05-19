---
name: "gmail-newsletter"
description: "사용자 Gmail 의 '업데이트(CATEGORY_UPDATES)' 라벨에 도착한 뉴스레터들을 발신자 화이트리스트로 골라내고 한국어로 요약해 신문 형태의 마크다운으로 정리합니다. 정리한 신문은 mattermost.send 스킬을 통해 사용자가 지정한 채널로 전달합니다. Composio Gmail 연결과 backend 프록시를 전제로 하며 OAuth 토큰 발급, multipart 첨부, 라벨 자체 수정 등은 기본 작업 흐름에서 제외합니다."
metadata:
  category: integrations
  integration: gmail
  runtime:
    requires_toolsets: ["gmail"]
---

# Gmail Newsletter Skill

## When to use

다음과 같은 사용자 요청이 들어오면 이 스킬을 사용한다.

- "오늘/이번 주 뉴스레터 정리해줘"
- "Gmail 업데이트 탭에 온 뉴스레터 요약해서 mm 으로 보내줘"
- "구독 중인 뉴스레터를 신문 형식으로 만들어줘"
- "최근 7일 동안의 뉴스레터 한 번 정리해서 공유해줘"

다음 작업은 이 스킬의 범위가 아니다.

- 뉴스레터가 아닌 일반 메일 처리(주문 내역, 청구서, 1:1 메일)
- Gmail OAuth 자체 설정·해제
- 라벨/필터 자동 생성·삭제

## Runtime

필요한 runtime toolset: `gmail`. 본 스킬은 메시지 정리·전달까지 책임지므로 mattermost 채널 전달이 필요한 경우 `mattermost.send` 도구를 함께 사용한다.

핵심 사용 도구는 `gmail.execute` 하나다. `gmail.execute` 는 backend Gmail 프록시를 통해 Gmail REST API(`/gmail/v1/...`) 를 호출한다. 모델 응답에 `userId` 를 절대로 넣지 않는다. 런타임이 인증된 사용자 식별자를 자동으로 바인딩한다.

상세 정보는 다음 참조 문서를 단계적으로 읽는다.

- `references/gmail-api-basics.md`: gmail.execute 명령 형태와 응답 해석 규칙.
- `references/updates-label-and-search.md`: 업데이트 라벨/카테고리 + 발신자 필터 검색 패턴.
- `references/newsletter-senders.md`: **구독 중인 뉴스레터 발신자 목록**. 사용자가 직접 편집하는 칸이다.
- `references/newspaper-template.md`: 신문 형태 마크다운 템플릿.
- `references/workflow-recipes.md`: 전체 수행 시나리오(요약·정리·전달) 의 예시 명령 체인.

## Workflow

1. **발신자 목록 확인**
   - 먼저 `references/newsletter-senders.md` 를 `skills.read` 로 읽어 구독 중인 발신자 화이트리스트를 확보한다.
   - 사용자가 추가로 발신자를 언급하면 그 요청도 함께 합산한다.
   - 화이트리스트가 비어 있다면 작업을 멈추고 사용자에게 발신자 목록을 추가해 달라고 요청한다.

2. **검색 쿼리 구성**
   - **기본은 발신자만 OR 결합.** `category:updates` 같은 라벨 조건은 추가하지 않는다 — 뉴스레터가 Promotions / Forums / Primary 등 다른 탭으로 자동 분류되는 경우가 많아 결과가 누락된다.
   - 발신자 조건: `from:(주소1 OR 주소2 OR @도메인1 OR ...)` 형태로 OR 결합.
   - 기간 조건(없으면 기본 7일): `newer_than:7d`.
   - 사용자가 명시적으로 "업데이트 탭만" 이라고 했을 때만 `category:updates` 추가.
   - 최종 쿼리 예: `from:(news@stratechery.com OR @substack.com) newer_than:7d`.
   - 명령:
     ```json
     {
       "commands": [
         {
           "method": "GET",
           "endpoint": "/gmail/v1/users/me/messages?q=from%3A(news%40stratechery.com+OR+%40substack.com)+newer_than%3A7d&maxResults=30"
         }
       ]
     }
     ```

3. **메시지 상세 조회**
   - 위 검색 결과에서 받은 각 `messageId` 에 대해 `GET /gmail/v1/users/me/messages/{id}?format=full` 호출.
   - 너무 많을 때는 한 번에 8 ~ 12 통만 처리한다.

4. **본문 정리 (압축 금지)**
   - 각 메시지의 헤더(From, Subject, Date) 와 본문(HTML 은 텍스트로 환원) 을 충분히 살린다.
   - **1 ~ 3 문장으로 줄이지 말 것.** 대신:
     - 한 줄 헤드라인 + 핵심 불릿 5 ~ 10 개 (본문 사실·수치·인용을 그대로)
     - 본문에 등장한 외부 링크는 모두 보존 (최대 5 개)
   - 광고성 문구·구독 해지 안내·CTA 버튼·이미지 alt·푸터만 제거.
   - 숫자·날짜·기업명·인명·국가명·제품명·인용문은 원문 표현 유지.
   - 본문이 매우 짧으면 그것도 그대로 표시한다. 빈자리 메우려 사실 만들지 말 것.

5. **신문 마크다운 생성**
   - `references/newspaper-template.md` 의 형식을 따른다.
   - 헤드라인 → 발신자별 섹션 → 각 메시지 카드 순서.
   - 이모지는 사용자가 명시적으로 요청하지 않으면 제목 줄에 1 개 정도만.

6. **전달**
   - 사용자가 mattermost 채널을 지정했으면 `mattermost.send` 로 신문 마크다운 전체를 1 메시지로 전송한다.
   - 채널 미지정 시 기본 alias(예: `backend`) 사용 여부를 사용자에게 짧게 확인한다.

7. **마무리**
   - 처리한 메시지 개수, 누락된 발신자(화이트리스트에 있지만 결과에 없던 경우) 를 사용자에게 요약 보고한다.
   - `task.completed` 직전에 신문 마크다운 미리보기(앞 부분 20 줄 정도) 를 함께 회신한다.

## Command Rules

- 모든 endpoint 는 `/gmail/v1/` 으로 시작한다.
- `GET` 의 쿼리스트링은 `endpoint` 안에 직접 인코딩해서 넣는다. 한글·특수문자는 URL 인코딩한다.
- `POST/PUT/PATCH` 의 바디는 `params` 에 둔다.
- 명령 결과의 `success` 필드를 반드시 확인한다. 단일 명령 실패가 다른 명령 성공을 가리지 않는다.
- 한 번에 보내는 명령은 12 개 이하로 유지한다.
- 사용자가 명시적으로 요청하지 않은 한 메시지 삭제(`DELETE`), 라벨 변경(`POST /gmail/v1/users/me/messages/{id}/modify`), 발송(`POST /gmail/v1/users/me/messages/send`) 은 절대 호출하지 않는다.
- 발신자 화이트리스트가 비었거나 모호하면 검색을 시작하지 않는다.

## First Scope

이 스킬의 첫 범위는 **읽기 위주** 다.

- 지원: `messages.list`, `messages.get`, `labels.list`, `threads.get`, `users.getProfile`.
- 제외: 메시지 발송, 메시지 삭제·이동, 라벨 생성·수정, IMAP/POP/Vacation 설정, 필터 생성, 인증서/CSE 관리.

이 제한 안에서 사용자에게 뉴스레터 정리·요약·전달까지 일관된 한국어 신문 형태로 응답한다.
