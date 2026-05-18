# 날짜

2026-05-18

# 작성자

전희수

# 관련 브랜치 또는 PR

AI-fix/agent-병목-개선

# 작업 목적

SRT 조회 결과가 전부 매진일 때 사용자에게 열차가 없는 것처럼 보이지 않도록 한다.

# 변경 요약

- `srt_booking.py`의 `search` 명령은 매진 열차까지 포함해 후보를 반환하도록 조정했다.
- `reserve` 명령은 기존처럼 예약 가능한 열차만 대상으로 유지했다.
- 조회/예약 검색 필터 동작을 검증하는 테스트를 추가했다.

# 주요 파일

- `ai/app/skills/k-skills/srt-booking/scripts/srt_booking.py`
- `ai/tests/domain/test_srt_booking_script.py`

# 테스트 또는 확인 내용

- `python -m pytest tests/domain/test_srt_booking_script.py tests/tools/test_skill_script_runtime.py tests/domain/test_srt_booking_skill_document.py -q`
- 결과: 7 passed

# 결정, 이슈, 리스크

- 사용자가 조회를 요청하면 매진 여부까지 설명하는 것이 맞다.
- 실제 예약은 여전히 예약 가능한 좌석만 대상으로 한다.

# 다음 단계

- 실제 조건 조회에서 매진 후보가 사용자에게 자연스럽게 설명되는지 확인한다.
