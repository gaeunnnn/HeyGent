# k-skills

1차와 2차 1차분으로 선별한 `NomaDamas/k-skill` 기반 skill 문서 모음이다.

## 포함 기준

- 로그인, 결제, 예약, 계정 접근 없이 조회 또는 계산할 수 있다.
- 기존 runtime tool(`terminal.run`, `web_*`, `file`)과 prompt에 주입되는 skill 설명만으로 사용할 수 있다.
- 외부 상태를 바꾸지 않는 읽기 전용 또는 deterministic utility다.
- 기능 smoke test가 가능하거나, 문서 로딩 후 최소 사용 경로가 명확하다.

## 1차 포함 목록

- `korea-weather`
- `fine-dust-location`
- `han-river-water-level`
- `seoul-subway-arrival`
- `real-estate-search`
- `zipcode-search`
- `geeknews-search`
- `korean-character-count`

## 2차 1차분 포함 목록

- `joseon-sillok-search`
- `library-book-search`
- `k-schoollunch-menu`
- `cheap-gas-nearby`
- `lotto-results`

## 3차 1차분 포함 목록

- `household-waste-info`
- `public-restroom-nearby`
- `subway-lost-property`

## 운영 메모

- 별도 `skill.execute`는 사용하지 않는다.
- `korea-weather`, `seoul-subway-arrival`은 공개 hosted proxy `https://k-skill-proxy.nomadamas.org`를 기본값으로 사용한다.
- helper script는 skill 문서가 직접 참조하고 1차 검증에 필요한 경우에만 skill 폴더 아래 `scripts/`에 둔다.
