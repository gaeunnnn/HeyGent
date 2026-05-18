# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-fix/agent-병목-개선
- PR: 미생성

## 작업 목적

- SRT 예약에서 조회 결과 index와 예약 index 기준이 달라 다른 열차가 예약되는 문제를 막는다.
- 자식 작업 완료 wake가 이미 실행 중인 부모 작업 뒤에서 재실행되어 Mattermost 같은 외부 부작용을 중복 수행하는 문제를 줄인다.

## 변경 요약

- SRT `reserve`가 직전 `search`와 같은 전체 후보 순서 기준으로 `--train-index`를 해석하도록 분리했다.
- `blockers_resolved`, `children_completed` wake가 대상 work의 active run과 겹치면 retry하지 않고 coalesced skip 처리한다.
- wake 생성 이후 대상 work가 이미 다른 run으로 진행된 경우 stale wake로 보고 skip 처리한다.
- SRT skill 문서에 `--train-index` 기준과 예약 결과 불일치 확인 규칙을 명시했다.

## 주요 파일

- `ai/app/skills/k-skills/srt-booking/scripts/srt_booking.py`
- `ai/app/skills/k-skills/srt-booking/SKILL.md`
- `ai/app/api/http/sessions.py`
- `ai/tests/domain/test_srt_booking_script.py`
- `ai/tests/api/test_work_run_blockers.py`

## 테스트 / 확인

- `python -m pytest .\tests\domain\test_srt_booking_script.py`
- `python -m pytest .\tests\api\test_work_run_blockers.py`
- `python -m pytest .\tests\domain\test_srt_booking_script.py .\tests\domain\test_srt_booking_skill_document.py`
- `python -m pytest .\tests\api\test_work_run_blockers.py .\tests\domain\test_work_service.py`

## 결정 / 이슈

- Paperclip reference의 "이미 running이면 wakeup은 duplicate run을 만들지 않고 coalesced 처리" 계약을 blockers/children wake에 적용했다.
- 실제 실테스트에서는 부모 작업 종료 뒤 stale wake가 한 번 더 실행되는 것이 확인되어, active run 중복뿐 아니라 wake 이후 work 진행 여부도 같이 본다.
- SRT 예약은 아직 `--train-index` 기반이므로 장기적으로는 열차번호/출발시각 또는 candidate id 기반으로 바꾸는 것이 더 안전하다.

## 다음 단계

- 관련 테스트 묶음을 한 번 더 돌리고, 필요하면 실제 프론트 요청 재현 전에 현재 미결제 예약 상태를 별도로 정리한다.
