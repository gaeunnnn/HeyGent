---
name: korean-stock-search
description: Korean (KRX) listed stock lookups via k-skill-proxy. Search KRX symbols, get stock base info, and daily trade info (close price, change, volume, market cap) for KOSPI/KOSDAQ. Based on jjlabsio's korea-stock-mcp and official KRX Open API.
license: MIT
metadata:
  category: stock
  locale: ko-KR
  phase: v1
---

# Korean Stock Search

## What this skill does

기본적으로 `https://k-skill-proxy.nomadamas.org/v1/korean-stock/...` 로 요청해서 한국 KRX 상장 종목 정보를 조회한다. KRX 공식 Open API 데이터를 기반으로 한다.

- KRX 상장 종목 검색 (`/v1/korean-stock/search`)
- 종목 기본정보 조회 (`/v1/korean-stock/base-info`)
- 종목 일별 시세 조회 (`/v1/korean-stock/trade-info`)
- 종목명이 모호할 때 시장/종목코드 후보를 먼저 좁히기

## When to use

- "삼성전자 주가 알려줘"
- "오늘 SK하이닉스 종가랑 거래량 보여줘"
- "카카오 시가총액 얼마야"
- "네이버 종목코드 뭐야"
- "코스피 ○○ 종목 기본정보 조회해줘"

## When not to use

- 해외 주식(미국/일본 등) 시세 조회
- 실시간 호가/체결 (이 스킬은 일별 snapshot 기준)
- 투자 추천/매수매도 판단 (데이터 조회만, 조언 X)
- 선물/옵션/ETF 파생 상세 분석

## Inputs

- `q`: 종목명 (search endpoint, 예: `"삼성전자"`)
- `market`: 시장 구분 (`KOSPI` / `KOSDAQ`)
- `code`: 6자리 단축 종목코드 (예: `"005930"`)
- `bas_dd`: 8자리 기준일 YYYYMMDD (예: `"20260408"`). **항상 명시할 것.** 생략하면 404 가 난다.

### bas_dd 필수 규칙 (반드시 따를 것)

- `trade-info` / `base-info` 호출 시 `bas_dd` 를 **반드시 포함**한다. 생략하면 404.
- 장 마감 직후나 휴장일(주말·공휴일)에는 오늘 데이터가 아직 없어 404 가 난다.
- 그래서 **처음부터 "어제(전 영업일)" 날짜로 호출**하는 것을 기본으로 한다.

#### 404 가 났을 때 (무한루프 절대 금지)

- 404 가 나면 **`bas_dd` 만 하루 전으로 바꿔서 같은 도구를 다시 호출**한다.
- **재시도는 최대 2번까지만** 한다 (즉 날짜를 총 3개 — 어제, 그제, 그그제 — 까지만 시도).
- **3번 모두 404 면 즉시 멈추고** "최근 거래일 데이터를 찾지 못했습니다" 라고 솔직히 보고한다.
- 절대로 **새 작업(work)을 만들거나 "재조회" 작업을 다시 생성하지 않는다.** 같은 작업 안에서 도구만 다시 부른다.
- 절대 시세를 추측하거나 지어내지 않는다. tool 로 받은 값만 답한다.
- 주말이면 금요일, 월요일 오전이면 금요일 데이터를 쓴다 (위 3번 안에서 처리).

## Prerequisites

없음. 사용자는 `KRX_API_KEY` 를 준비할 필요가 없다. upstream key 는 proxy 서버에서만 관리한다. 인터넷 연결만 있으면 된다.

## Default path

추가 client API 레이어는 불필요하다. 그냥 프록시 서버에 HTTP 요청만 넣으면 된다.

`KSKILL_PROXY_BASE_URL` 환경변수가 있으면 그 값을 사용하고, 없으면 기본 경로 `https://k-skill-proxy.nomadamas.org` 를 사용한다.

## Recommended order

1. 종목명이 애매하면 `/v1/korean-stock/search?q=...` 로 후보를 먼저 찾는다.
2. 후보에서 `market`, `code` 를 확인한다.
3. 기본 정보가 필요하면 `/v1/korean-stock/base-info?market=...&code=...&bas_dd=어제` 를 호출한다.
4. 가격/거래량은 `/v1/korean-stock/trade-info?market=...&code=...&bas_dd=어제` 를 호출한다. **bas_dd 를 반드시 어제(전 영업일) 부터** 넣는다.
5. 404 가 나면 `bas_dd` 를 하루 전으로 바꿔 **최대 2번만** 재시도한다 (어제→그제→그그제). 3번 모두 404 면 **즉시 멈추고** "최근 거래일 데이터를 찾지 못했다" 고 보고한다. **새 작업을 만들지 않는다.**

## Example requests

종목 검색:

```bash
curl -fsS --get 'https://k-skill-proxy.nomadamas.org/v1/korean-stock/search' \
  --data-urlencode 'q=삼성전자' \
  --data-urlencode 'bas_dd=20260408'
```

기본정보:

```bash
curl -fsS --get 'https://k-skill-proxy.nomadamas.org/v1/korean-stock/base-info' \
  --data-urlencode 'market=KOSPI' \
  --data-urlencode 'code=005930' \
  --data-urlencode 'bas_dd=20260408'
```

일별 시세:

```bash
curl -fsS --get 'https://k-skill-proxy.nomadamas.org/v1/korean-stock/trade-info' \
  --data-urlencode 'market=KOSPI' \
  --data-urlencode 'code=005930' \
  --data-urlencode 'bas_dd=20260408'
```

## Response 해석 팁

- `code` 는 보통 6자리 단축코드다.
- `standard_code` 는 KRX 표준코드다.
- `close_price`, `trading_volume`, `market_cap` 은 숫자로 정규화돼 온다.
- `base_date` / `bas_dd` 는 일별 snapshot 날짜다.
- 휴장일/장마감 전에는 빈 결과나 `not_found` 가 나올 수 있다.
- 일부 시장 upstream 이 실패하면 검색 응답에 `upstream.degraded=true` 와 `failed_markets` 가 붙을 수 있다.

## 답변 템플릿 권장

- 종목명 / 시장 / 종목코드
- 기준일
- 종가 / 등락률 / 거래량 / 시가총액
- 필요하면 상장일 / 액면가 / 상장주식수
- 마지막 한 줄: KRX 공식 데이터 기준이며 투자 조언은 아닙니다.

## Failure modes

- 잘못된 `market`, `code`, `bas_dd` 형식은 400
- proxy 서버에 `KRX_API_KEY` 가 없으면 503
- 검색 중 일부 시장 upstream 이 실패하면 200 이지만 `upstream.degraded=true` / `failed_markets` 가 함께 온다.
- 모든 요청 시장에서 upstream KRX 조회가 실패하면 502
- 기준일에 종목을 찾지 못하면 404 `not_found`

## Done when

- 종목명이 모호하면 `search` 로 시장/코드를 먼저 확정했다.
- 요청 목적(기본정보 vs 시세)에 맞는 endpoint 를 선택했다.
- 휴장일이면 `bas_dd` 를 영업일로 보정했다.
- 결과를 요약하고 "KRX 공식 데이터 기준, 투자 조언 아님" 을 남겼다.

## Notes

- 원본 참고(참고용 MCP 서버): `https://github.com/jjlabsio/korea-stock-mcp`
- 공식 데이터 출처: KRX Open API (`https://openapi.krx.co.kr`)
- 기본 사용법은 로컬 MCP 설치가 아니라 proxy first 다.
