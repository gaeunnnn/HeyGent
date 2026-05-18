# 날짜

2026-05-18

# 작성자

전희수

# 관련 브랜치 또는 PR

AI-fix/agent-병목-개선

# 작업 목적

SRT 스킬이 문서 안내에만 머물지 않고, 스킬에 종속된 Python script를 통해 실제 조회/예약/취소 실행 경로를 가질 수 있게 한다.

# 변경 요약

- `skill-runtime` toolset에 `skill.run_script`를 추가했다.
- `skill.run_script`는 등록된 skill의 `scripts/*.py`만 실행하고, 현재 agent profile의 `SECRETS.md` 저장값을 child process 환경변수로만 주입한다.
- `srt-booking` skill에 `scripts/srt_booking.py`를 추가하고, 조회/예약/예약내역/취소 subcommand를 제공했다.
- AI 이미지 의존성에 `SRTrain>=2.6.7,<3`을 추가했다.
- SRT 스킬 문서를 `skill.run_script` 사용 흐름으로 갱신했다.

# 주요 파일

- `ai/app/tools/runtime/local_tool_runtime.py`
- `ai/app/tools/runtime/toolsets.py`
- `ai/app/tools/runtime/registry.py`
- `ai/app/tools/skills/skill_script_tool.py`
- `ai/app/skills/k-skills/srt-booking/SKILL.md`
- `ai/app/skills/k-skills/srt-booking/scripts/srt_booking.py`
- `ai/pyproject.toml`
- `ai/requirements.txt`

# 테스트 또는 확인 내용

- `python -m pytest tests/tools/test_skill_script_runtime.py tests/domain/test_srt_booking_skill_document.py tests/domain/test_capability_resolver.py tests/api/test_tasks_runtime.py tests/storage/test_agent_repository_secrets.py tests/domain/test_agent_secret_documents.py -q`
- 결과: 69 passed
- `docker compose up -d --build ai`로 AI 컨테이너 재빌드 및 재기동
- AI health 응답 `ok` 확인
- 컨테이너 내부 `SRT` import 확인
- 컨테이너 내부 SRT skill 문서와 `scripts/srt_booking.py` 존재 확인

# 결정, 이슈, 리스크

- secret 원문은 모델이나 문서에 넘기지 않고, `skill.run_script` 실행 process의 환경변수로만 전달한다.
- SRT 예약은 부작용이 있으므로 스킬 문서에서 조회 후 사용자 확인, 예약 대상 확정 순서를 유지한다.
- 실제 예약 성공 여부는 SRT 계정, SRT 정책, 네트워크 상태에 의존한다.

# 다음 단계

- K-agent로 실제 SRT 조회 요청을 실행해 `missing_skill_secrets`, 로그인 실패, 조회 성공 케이스별 사용자 안내가 자연스러운지 확인한다.
