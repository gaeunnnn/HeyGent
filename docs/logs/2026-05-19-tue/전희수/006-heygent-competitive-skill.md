# 작업 로그

## 날짜

2026-05-19

## 작성자

전희수

## 관련 브랜치 / PR

- 브랜치: AI-feat/Heygent
- PR: 없음

## 작업 목적

- HeyGent 서비스 질문 대응 스킬이 경쟁 서비스 비교, 공격성 질문, 기술 근거 질문에도 빠르고 긍정적으로 답할 수 있도록 보강합니다.

## 변경 요약

- HeyGent 스킬에 답변 플레이북, 제품 포지셔닝, 경쟁 비교, 기술 근거, 보안/제약, 상태/확장 방향 레퍼런스를 추가했습니다.
- OpenClaw, ChatGPT, Codex, Claude Code, Cursor 비교 질문에서 상대 서비스를 깎아내리지 않고 HeyGent의 작업 실행 흐름으로 답하도록 정리했습니다.
- 클라우드 기반으로 어디서든 이어지는 개인 비서, 쉬운 사용성, EC2 KMS credential 암호화 저장, Windows 앱 컨테이너 기반 로컬 앱 격리 관점을 핵심 장점으로 추가했습니다.
- "너가 OpenClaw보다 나은 점", "너는 뭐가 좋아", "너희 서비스", "우리 서비스", "이 서비스" 같은 2인칭/지시어 질문도 HeyGent 제품 질문으로 해석하도록 팀장 지침과 skill 설명을 보강했습니다.
- OpenClaw 비교 답변은 TaskRun/StepRun보다 클라우드 기반 기억 비서, 쉬운 사용성, EC2 KMS credential 암호화 저장, Windows 앱 컨테이너 격리 3축을 먼저 말하도록 우선순위를 조정했습니다.
- Skill catalog description과 팀장 기본 지침에도 OpenClaw 3축 우선순위를 직접 넣어, reference를 읽기 전에도 답변이 실행 추적 중심으로 새지 않게 했습니다.
- 기존 세션 instruction bundle에는 파일 변경이 자동 반영되지 않으므로 DB의 팀장 `AGENTS.md` 문서에도 OpenClaw 3축 우선순위를 반영했습니다.
- AI 컨테이너를 다시 빌드하고 skill catalog description이 새 내용으로 동기화됐는지 확인했습니다.
- 기존 강점/한계/흐름 문서도 경쟁 비교와 부정 질문 대응 기준에 맞춰 보강했습니다.
- 스킬 레퍼런스 구성이 유지되는지 확인하는 테스트를 추가했습니다.

## 주요 파일

- `ai/app/skills/product/heygent/SKILL.md`
- `ai/app/domain/agents/templates.py`
- `ai/app/skills/product/heygent/references/answer-playbook.md`
- `ai/app/skills/product/heygent/references/competitive-comparison.md`
- `ai/app/skills/product/heygent/references/proof-points.md`
- `ai/app/skills/product/heygent/references/security-and-constraints.md`
- `ai/app/skills/product/heygent/references/status-and-roadmap.md`
- `ai/tests/domain/test_agent_templates.py`

## 테스트 / 확인

- `pytest tests\domain\test_agent_templates.py -k heygent_skill_contains_competitive_question_playbook`
- `pytest tests\domain\test_agent_templates.py -k heygent`
- `pytest tests\test_model_loop_contract.py -k heygent_catalog_description_surfaces_openclaw_answer_priorities`
- `docker compose -f compose.yml up -d --build ai`
- `docker exec heygent-postgres psql ... ai_skill_catalog where name='heygent'`
- `docker exec heygent-postgres psql ... ai_agent_instruction_documents ... has_priority`
- `pytest tests\domain\test_agent_templates.py -k "second_person_product_questions or heygent"`
- `pytest tests\domain\test_agent_templates.py -k heygent`
- `python -m compileall -q app`
- `rg -n "시연|발표" ai\app\skills\product\heygent ai\app\domain\agents\templates.py`
- 참고: `pytest tests\domain\test_agent_templates.py` 전체 실행은 기존 템플릿 기대값 2건에서 실패했습니다.

## 결정 / 이슈

- 경쟁 서비스보다 무조건 우월하다고 단정하지 않고, 사용 장면과 제품 구조 기준으로 비교합니다.
- 팀에서 확정 구현 중인 EC2 KMS와 Windows 앱 컨테이너 보안 설계는 확정 장점으로 설명합니다.
- 단, 모든 보안 위험 제거, 모델 성능 우위처럼 검증되지 않은 내용은 단정하지 않습니다.
- 스킬 reference 파일은 항상 자동 주입되는 자료가 아니며, 모델이 skill 파일 읽기 도구를 호출해야 자세한 reference를 읽습니다. 그래서 핵심 비교 포인트는 skill description과 팀장 기본 지침에도 중복 배치했습니다.

## 다음 단계

- 실제 서비스 질문 로그가 쌓이면 자주 나오는 질문을 `answer-playbook.md`에 추가합니다.
