# 날짜

2026-05-18

# 작성자

전희수

# 관련 브랜치 또는 PR

AI-fix/agent-병목-개선

# 작업 목적

SRT 로그인 식별자가 회원번호만 가능한 것처럼 보이지 않도록 K-agent secret 안내를 명확히 한다.

# 변경 요약

- `srt-booking` skill 문서에 `KSKILL_SRT_ID`가 SRT 회원번호, 이메일, 휴대전화번호 중 하나를 받을 수 있다고 명시했다.
- K-agent 기본 `SECRETS.md` 템플릿에도 같은 안내를 추가했다.
- 휴대전화번호는 `010-1234-5678`처럼 하이픈 포함 형식을 권장한다고 명시했다.

# 주요 파일

- `ai/app/skills/k-skills/srt-booking/SKILL.md`
- `ai/app/domain/agents/templates.py`
- `ai/tests/domain/test_srt_booking_skill_document.py`
- `ai/tests/domain/test_agent_templates.py`

# 테스트 또는 확인 내용

- `python -m pytest tests/domain/test_srt_booking_skill_document.py tests/domain/test_agent_templates.py -q`
- 결과: 20 passed

# 결정, 이슈, 리스크

- 내부 secret key 이름은 기존 호환성을 위해 `KSKILL_SRT_ID`로 유지한다.
- 의미는 SRT 로그인 식별자로 확장해 안내한다.

# 다음 단계

- 실제 K-agent 설정 화면에서 새 `SECRETS.md` 안내가 노출되는지 확인한다.
