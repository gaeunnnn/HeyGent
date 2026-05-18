# 작업 로그

## 날짜

2026-05-18

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-fix/agent-병목-개선
- PR: 없음

## 작업 목적

- SRT skill의 계정 정보 안내를 K-agent `SECRETS.md` 기반 흐름에 맞춘다.

## 변경 요약

- SRT skill 문서에서 로컬 env 파일과 외부 secret vault fallback 안내를 제거했다.
- K-agent 설정의 `SECRETS.md` > `## srt-booking`에 `KSKILL_SRT_ID`, `KSKILL_SRT_PASSWORD`를 입력하도록 안내를 교체했다.
- 저장 후 암호화 보관과 `(암호화 저장 완료)` 표시 기준을 skill 문서에 명시했다.
- 비밀번호를 채팅창에 직접 요구하지 않도록 안내를 추가했다.

## 주요 파일

- `ai/app/skills/k-skills/srt-booking/SKILL.md`
- `ai/tests/domain/test_srt_booking_skill_document.py`

## 테스트 / 확인

- `python -m pytest tests/domain/test_srt_booking_skill_document.py tests/domain/test_agent_templates.py tests/domain/test_agent_secret_documents.py tests/storage/test_agent_repository_secrets.py -q`

## 결정 / 이슈

- 이번 변경은 skill 문서의 credential 안내만 교체한다.
- 조회/예약/취소 workflow와 SRTrain 예시는 원문 흐름을 유지했다.

## 다음 단계

- 실제 SRT 실행 runtime tool을 붙일 때 저장된 secret을 모델 프롬프트가 아니라 런타임에만 주입한다.
