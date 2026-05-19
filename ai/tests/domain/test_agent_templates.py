from pathlib import Path
from types import SimpleNamespace

from app.api.http.agents import (
    _bundle_response,
    _custom_agent_config_snapshot,
    _profile_response,
    _template_response,
    _sanitize_profile_skill_config,
)
from app.domain.orchestration.prompts.skill_prompt import SkillLoader
from app.domain.agents.templates import (
    BUILTIN_AGENT_TEMPLATES,
    DEFAULT_SESSION_TEMPLATE_KEYS,
    K_SERVICE_SKILL_IDS,
    LEGACY_AGENT_SKILL_IDS,
    MAIN_AGENT_TEMPLATE,
)
from app.contracts.agents import CreateSessionAgentRequest
from tests.fakes import InMemoryAgentRepository


def test_main_agent_template_does_not_include_heartbeat_document():
    document_keys = {document_key for document_key, _, _ in MAIN_AGENT_TEMPLATE.documents}

    assert "HEARTBEAT.md" not in document_keys


def test_main_agent_template_includes_mattermost_send_skill():
    assert "mattermost-send" in MAIN_AGENT_TEMPLATE.skills


def test_main_agent_template_includes_notion_skill():
    assert "notion" in MAIN_AGENT_TEMPLATE.skills


def test_main_agent_template_includes_awesome_design_skill():
    assert "awesome-design" in MAIN_AGENT_TEMPLATE.skills


def test_main_agent_template_includes_heygent_skill():
    assert "heygent" in MAIN_AGENT_TEMPLATE.skills


def test_builtin_subagent_templates_default_to_worker_model():
    assert MAIN_AGENT_TEMPLATE.model == "gpt-5.4"

    for template in BUILTIN_AGENT_TEMPLATES:
        assert template.model == "gpt-5.2"


def test_prototype_capable_subagents_include_awesome_design_skill():
    template_by_key = {template.template_key: template for template in BUILTIN_AGENT_TEMPLATES}

    assert "awesome-design" in template_by_key["coder"].skills
    assert "awesome-design" in template_by_key["ux_designer"].skills


def test_main_agent_template_uses_team_lead_display_copy():
    assert MAIN_AGENT_TEMPLATE.display_name == "팀장"
    assert MAIN_AGENT_TEMPLATE.name == "팀장"
    assert MAIN_AGENT_TEMPLATE.title == "팀장"
    assert MAIN_AGENT_TEMPLATE.role == "ceo"
    joined_documents = "\n".join(document for _, _, document in MAIN_AGENT_TEMPLATE.documents)
    assert "팀장 지침" in joined_documents
    assert "CEO 지침" not in joined_documents


def test_main_agent_handles_heygent_service_questions_directly():
    joined_documents = "\n".join(document for _, _, document in MAIN_AGENT_TEMPLATE.documents)

    assert "HeyGent 서비스 질문 응답" in joined_documents
    assert "HeyGent 서비스 자체" in joined_documents
    assert "팀장이 직접 답합니다" in joined_documents
    assert "시연" not in joined_documents
    assert "발표" not in joined_documents
    assert "개발 에이전트" not in joined_documents
    assert "보안 위험 검토" not in joined_documents


def test_main_agent_routes_second_person_product_questions_to_heygent_skill():
    joined_documents = "\n".join(document for _, _, document in MAIN_AGENT_TEMPLATE.documents)
    skill_root = Path(__file__).resolve().parents[2] / "app" / "skills" / "product" / "heygent"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    competitive = (skill_root / "references" / "competitive-comparison.md").read_text(encoding="utf-8")

    assert "너가 OpenClaw보다 나은 점" in joined_documents
    assert "너는 뭐가 좋아" in joined_documents
    assert "너희 서비스" in joined_documents
    assert "우리 서비스" in joined_documents
    assert "이 서비스" in joined_documents
    assert "heygent` skill" in joined_documents
    assert "너가 OpenClaw보다 나은 점" in skill
    assert "너/너희/우리 서비스" in competitive


def test_main_agent_openclaw_comparison_prioritizes_three_business_advantages():
    joined_documents = "\n".join(document for _, _, document in MAIN_AGENT_TEMPLATE.documents)

    assert "OpenClaw 비교 질문은 아래 3가지를 먼저 답합니다" in joined_documents
    assert joined_documents.index("어디서든 이어지는 나를 기억하는 클라우드 비서") < joined_documents.index("TaskRun")
    assert joined_documents.index("설치와 운영 부담을 줄인 쉬운 사용성") < joined_documents.index("TaskRun")
    assert joined_documents.index("EC2 KMS credential 암호화 저장") < joined_documents.index("TaskRun")
    assert joined_documents.index("Windows 앱 컨테이너") < joined_documents.index("TaskRun")
    assert "TaskRun/StepRun은 위 3가지를 말한 뒤 보조 근거로만 덧붙입니다" in joined_documents


def test_builtin_agent_template_skills_exist_in_builtin_catalog():
    catalog_skill_names = {skill["name"] for skill in SkillLoader().load_builtin()}
    template_skills = {
        skill
        for template in (MAIN_AGENT_TEMPLATE, *BUILTIN_AGENT_TEMPLATES)
        for skill in template.skills
    }

    assert template_skills
    assert template_skills.isdisjoint(LEGACY_AGENT_SKILL_IDS)
    assert template_skills.issubset(catalog_skill_names)


def test_builtin_subagent_templates_do_not_default_to_notion_or_mattermost():
    restricted_defaults = {"notion", "mattermost-send"}

    for template in BUILTIN_AGENT_TEMPLATES:
        assert restricted_defaults.isdisjoint(template.skills)


def test_k_service_template_includes_korean_life_skills():
    template_by_key = {template.template_key: template for template in BUILTIN_AGENT_TEMPLATES}
    template = template_by_key["k_services"]

    assert "k_services" in DEFAULT_SESSION_TEMPLATE_KEYS
    assert template.display_name == "K-에이전트"
    assert template.profile_image == "/assets/agents/agent06/idle_front.png"
    assert set(K_SERVICE_SKILL_IDS).issubset(set(template.skills))
    assert "subway-lost-property" in template.skills


def test_k_service_template_includes_srt_booking_and_secrets_document():
    template_by_key = {template.template_key: template for template in BUILTIN_AGENT_TEMPLATES}
    template = template_by_key["k_services"]
    documents = {document_key: content for document_key, _, content in template.documents}

    assert "srt-booking" in template.skills
    assert "SECRETS.md" in documents
    assert "저장 시 자동으로 암호화 저장됩니다" in documents["SECRETS.md"]
    assert "서버가 원문 값을 암호화하여 저장합니다" in documents["SECRETS.md"]
    assert "저장 후에는 입력한 값이 다시 노출되지 않습니다" in documents["SECRETS.md"]
    assert "필수값이 모두 저장되면 섹션 제목 옆에 `(암호화 저장 완료)`가 표시됩니다" in documents["SECRETS.md"]
    assert "하나라도 비어 있으면 완료 표시가 사라집니다" in documents["SECRETS.md"]
    assert "원문 대신 `<stored>`" not in documents["SECRETS.md"]
    assert "SRT 회원번호, 이메일, 휴대전화번호 중 하나" in documents["SECRETS.md"]
    assert "하이픈 포함 형식" in documents["SECRETS.md"]
    assert "KSKILL_SRT_ID=" in documents["SECRETS.md"]
    assert "KSKILL_SRT_PASSWORD=" in documents["SECRETS.md"]
    assert "SECRETS.md" in documents["AGENTS.md"]


def test_health_template_includes_health_condition_skill():
    template_by_key = {template.template_key: template for template in BUILTIN_AGENT_TEMPLATES}
    template = template_by_key["health_agent"]

    assert "health_agent" in DEFAULT_SESSION_TEMPLATE_KEYS
    assert template.display_name == "헬스 에이전트"
    assert template.skills == ("health-condition-check",)
    assert "건강정보" in template.description
    assert "생활 활동 데이터" in template.description
    assert "몸 상태가 괜찮은지" in template.description
    assert "하루 페이스" in template.description
    assert "건강 데이터 추세" in template.description
    assert "발표·업무" not in template.description
    assert "의료 진단" in template.description
    joined_documents = "\n".join(document for _, _, document in template.documents)
    assert "의도분류" not in joined_documents
    assert "health.execute" in joined_documents
    assert "step_count" in joined_documents
    assert "duration_minutes" in joined_documents
    assert "건강정보 참고 코칭" in joined_documents
    assert "AASM/SRS" in joined_documents
    assert "`건강 데이터 요약`, `근거`, `주의할 점`, `추천 행동`, `참고`" in joined_documents
    assert "수면: 사용자 데이터 → 짧은 해석" in joined_documents
    assert "의학적 진단이나 치료 조언을 대체하지 않는다" in joined_documents


def test_health_skill_references_include_research_sources_and_safe_policy():
    skill_root = Path(__file__).resolve().parents[2] / "app" / "skills" / "health" / "condition-check"
    evidence = (skill_root / "references" / "evidence-map.md").read_text(encoding="utf-8")
    policy = (skill_root / "references" / "response-policy.md").read_text(encoding="utf-8")

    assert "AASM/SRS 성인 수면 시간 합의문" in evidence
    assert "WHO 신체활동 및 좌식행동 가이드라인" in evidence
    assert "2025 AHA/ACC 성인 고혈압 가이드라인" in evidence
    assert "스마트워치 BIA 체성분 추정 연구" in evidence
    assert "PMID: 38759474" in evidence
    assert "https://pubmed.ncbi.nlm.nih.gov/40811516/" in evidence
    assert "이 응답은 의학적인 조언입니다" in policy
    assert "의학적 진단이나 치료 조언을 대체하지 않습니다" in policy
    assert "`건강 데이터 요약`, `근거`, `주의할 점`, `추천 행동`, `참고`" in policy
    assert "사용자 데이터 → 짧은 해석" in policy
    assert "정확히 3줄만 작성" in policy
    assert "근거 기반 컨디션 판단" not in policy

    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    assert "피로감" in skill
    assert "운동 가능 여부" in skill
    assert "몸 상태가 괜찮은지" in skill
    assert "건강 데이터 요약:" in skill
    assert "주의할 점:" in skill
    assert "사용자 데이터 → 짧은 해석" in skill


def test_heygent_is_skill_for_team_lead_not_builtin_subagent_template():
    template_by_key = {template.template_key: template for template in BUILTIN_AGENT_TEMPLATES}

    assert "heygent" not in DEFAULT_SESSION_TEMPLATE_KEYS
    assert "heygent" not in template_by_key


def test_heygent_skill_contains_fast_positive_service_knowledge_index():
    skill_root = Path(__file__).resolve().parents[2] / "app" / "skills" / "product" / "heygent"
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    overview = (skill_root / "references" / "overview.md").read_text(encoding="utf-8")
    features = (skill_root / "references" / "features.md").read_text(encoding="utf-8")
    limitations = (skill_root / "references" / "limitations.md").read_text(encoding="utf-8")
    product_flow = (skill_root / "references" / "product-flow.md").read_text(encoding="utf-8")
    all_heygent_skill_text = "\n".join(
        [
            skill,
            overview,
            features,
            limitations,
            product_flow,
            (skill_root / "references" / "architecture.md").read_text(encoding="utf-8"),
            (skill_root / "references" / "ai-runtime.md").read_text(encoding="utf-8"),
            (skill_root / "references" / "strengths.md").read_text(encoding="utf-8"),
            (skill_root / "references" / "glossary.md").read_text(encoding="utf-8"),
        ]
    )

    assert 'name: "heygent"' in skill
    assert "빠르고 긍정적으로 답할 때 사용합니다" in skill
    assert "기본 답변은 3~5문장" in skill
    assert "references/overview.md" in skill
    assert "references/product-flow.md" in skill
    assert "AI 오케스트레이션 서비스" in overview
    assert "TaskRun" in features
    assert "멀티 디바이스" in features
    assert "부정적인 결과가 예상되면 짧게만 설명합니다" in limitations
    assert "그렇지만" in limitations
    assert "시연" not in all_heygent_skill_text
    assert "발표" not in all_heygent_skill_text


def test_heygent_skill_contains_competitive_question_playbook():
    skill_root = Path(__file__).resolve().parents[2] / "app" / "skills" / "product" / "heygent"
    required_reference_names = {
        "answer-playbook.md",
        "positioning.md",
        "capability-map.md",
        "competitive-comparison.md",
        "proof-points.md",
        "security-and-constraints.md",
        "status-and-roadmap.md",
    }
    reference_texts = {
        name: (skill_root / "references" / name).read_text(encoding="utf-8")
        for name in required_reference_names
    }
    skill = (skill_root / "SKILL.md").read_text(encoding="utf-8")
    all_heygent_skill_text = "\n".join([skill, *reference_texts.values()])

    for name in required_reference_names:
        assert f"references/{name}" in skill

    assert "OpenClaw보다 뭐가 나아" in reference_texts["competitive-comparison.md"]
    assert "ChatGPT" in reference_texts["competitive-comparison.md"]
    assert "Codex" in reference_texts["competitive-comparison.md"]
    assert "Claude Code" in reference_texts["competitive-comparison.md"]
    assert "Cursor" in reference_texts["competitive-comparison.md"]
    assert "경쟁 서비스를 깎아내리지 않습니다" in reference_texts["competitive-comparison.md"]
    assert "사용자의 한 문장 요청을 실제 작업 흐름으로 바꾸는 AI 작업 실행 플랫폼" in reference_texts["positioning.md"]
    assert "TaskRun" in reference_texts["proof-points.md"]
    assert "StepRun" in reference_texts["proof-points.md"]
    assert "그렇지만" in reference_texts["answer-playbook.md"]
    assert "상태와 실행 근거를 보여 주는 방향" in reference_texts["status-and-roadmap.md"]
    assert "시연" not in all_heygent_skill_text
    assert "발표" not in all_heygent_skill_text


def test_heygent_skill_contains_cloud_memory_easy_security_positioning():
    skill_root = Path(__file__).resolve().parents[2] / "app" / "skills" / "product" / "heygent"
    positioning = (skill_root / "references" / "positioning.md").read_text(encoding="utf-8")
    competitive = (skill_root / "references" / "competitive-comparison.md").read_text(encoding="utf-8")
    security = (skill_root / "references" / "security-and-constraints.md").read_text(encoding="utf-8")
    strengths = (skill_root / "references" / "strengths.md").read_text(encoding="utf-8")
    status = (skill_root / "references" / "status-and-roadmap.md").read_text(encoding="utf-8")
    all_heygent_skill_text = "\n".join([positioning, competitive, security, strengths, status])

    assert "어디서든 이어지는" in positioning
    assert "나를 기억하는 비서" in positioning
    assert "쉽게 사용할 수 있는" in strengths
    assert ".env 평문" in security
    assert "EC2 KMS" in security
    assert "KMS로 암호화 저장" in security
    assert "암호화 저장" in security
    assert "Windows 앱 컨테이너" in security
    assert "레지스트리를 직접 변경하지 못하게" in security
    assert "클라우드 기반" in competitive
    assert "설치와 운영 부담" in competitive
    assert "확정된 보안 차별점" in competitive
    assert "배포 환경" in status
    assert "시연" not in all_heygent_skill_text
    assert "발표" not in all_heygent_skill_text


def test_heygent_openclaw_answer_prioritizes_three_core_advantages():
    skill_root = Path(__file__).resolve().parents[2] / "app" / "skills" / "product" / "heygent"
    competitive = (skill_root / "references" / "competitive-comparison.md").read_text(encoding="utf-8")
    playbook = (skill_root / "references" / "answer-playbook.md").read_text(encoding="utf-8")
    openclaw_answer_start = competitive.index("## OpenClaw보다 뭐가 나아?")
    second_person_start = competitive.index("## 2인칭 비교 질문 처리")
    openclaw_answer = competitive[openclaw_answer_start:second_person_start]

    assert "OpenClaw 비교는 아래 3가지를 먼저 말합니다" in competitive
    assert openclaw_answer.index("어디서든 이어지는 나를 기억하는 클라우드 비서") < openclaw_answer.index("TaskRun")
    assert openclaw_answer.index("설치와 운영 부담을 줄인 쉬운 사용성") < openclaw_answer.index("TaskRun")
    assert openclaw_answer.index("EC2 KMS credential 암호화 저장") < openclaw_answer.index("TaskRun")
    assert openclaw_answer.index("Windows 앱 컨테이너") < openclaw_answer.index("TaskRun")
    assert "TaskRun/StepRun은 보조 근거로만 덧붙입니다" in competitive
    assert "OpenClaw 질문은 클라우드/쉬운 사용/보안을 먼저 답합니다" in playbook


def test_builtin_subagent_profile_images_point_to_frontend_assets():
    for template in BUILTIN_AGENT_TEMPLATES:
        assert not template.profile_image.startswith("/assets/agents/sub/")
        assert template.profile_image.startswith("/assets/agents/agent")
        assert template.profile_image.endswith("/idle_front.png")


def test_agent_template_and_profile_responses_include_visual_key():
    template = next(item for item in BUILTIN_AGENT_TEMPLATES if item.template_key == "k_services")
    template_payload = _template_response(
        {
            "template_id": "template-k",
            "template_key": template.template_key,
            "template_version": 1,
            "default_config_snapshot": {
                "name": template.name,
                "role": template.role,
                "profileImage": template.profile_image,
                "skills": list(template.skills),
            },
        }
    )
    profile_payload = _profile_response(
        {
            "profile_id": "agent-profile-k",
            "session_id": "session-1",
            "profile_key": "session.session-1.agent-profile-k",
            "profile_version": 1,
            "agent_type": "user_subagent",
            "template_key": "k_services",
            "config_snapshot": {
                "name": template.name,
                "role": template.role,
                "profileImage": template.profile_image,
                "skills": list(template.skills),
            },
        }
    )

    assert template_payload.visual_key == "agent06"
    assert profile_payload.visual_key == "agent06"


def test_visible_builtin_templates_are_routing_focused_agents():
    repository = InMemoryAgentRepository()

    assert [item["template_key"] for item in repository.list_templates()] == [
        "coder",
        "qa",
        "ux_designer",
        "k_services",
        "health_agent",
        "gmail_agent",
    ]


def test_instruction_bundle_response_omits_removed_run_loop_document():
    response = _bundle_response(
        {
            "bundle_id": "bundle-1",
            "profile_id": "profile-1",
            "mode": "managed",
            "entry_document_key": "AGENTS.md",
            "documents": [
                {"document_key": "AGENTS.md", "display_name": "기본 지침", "content": "base"},
                {"document_key": "HEARTBEAT.md", "display_name": "old", "content": "old"},
            ],
        }
    )

    assert [document.document_key for document in response.documents] == ["AGENTS.md"]


def test_custom_agent_snapshot_omits_removed_run_loop_document():
    snapshot = _custom_agent_config_snapshot(
        CreateSessionAgentRequest(
            name="개발 에이전트",
            instructionsFiles={
                "AGENTS.md": "base",
                "HEARTBEAT.md": "old",
            },
        )
    )

    document_keys = [document["documentKey"] for document in snapshot["documents"]]
    assert document_keys == ["AGENTS.md"]


def test_custom_agent_snapshot_falls_back_when_removed_document_is_entry():
    snapshot = _custom_agent_config_snapshot(
        CreateSessionAgentRequest(
            name="개발 에이전트",
            entryDocumentKey="HEARTBEAT.md",
            instructionsFiles={"HEARTBEAT.md": "old"},
        )
    )

    assert snapshot["entryDocumentKey"] == "AGENTS.md"
    assert [document["documentKey"] for document in snapshot["documents"]] == ["AGENTS.md"]


def test_agent_profile_skill_sanitizer_removes_catalog_missing_skills():
    item = {
        "profile_id": "agent-1",
        "session_id": "session-1",
        "config_snapshot": {
            "name": "개발 에이전트",
            "skills": ["notion", "subagent-driven-development", "missing-skill"],
            "documents": [
                {"documentKey": "AGENTS.md", "displayName": "기본 지침", "content": "base"}
            ],
        },
    }
    agent_repository = _FakeAgentRepository()
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                agent_repository=agent_repository,
                skill_repository=_FakeSkillRepository(["notion", "subagent-driven-development"]),
            )
        )
    )

    sanitized = _sanitize_profile_skill_config(
        request,
        item=item,
        user=SimpleNamespace(user_id=1),
    )

    assert sanitized["config_snapshot"]["skills"] == ["notion", "subagent-driven-development"]
    assert agent_repository.updated_config["skills"] == ["notion", "subagent-driven-development"]


class _FakeSkillRepository:
    def __init__(self, skill_ids: list[str]) -> None:
        self.skill_ids = skill_ids

    def list_user_skills(self, *, owner_key: str, owner_user_id: int | None):
        return [{"skill_id": skill_id, "name": skill_id} for skill_id in self.skill_ids]


class _FakeAgentRepository:
    def __init__(self) -> None:
        self.updated_config = {}

    def update_session_agent(
        self,
        *,
        session_id: str,
        owner_key: str,
        profile_id: str,
        config_snapshot: dict,
    ):
        self.updated_config = dict(config_snapshot)
        return {
            "profile_id": profile_id,
            "session_id": session_id,
            "config_snapshot": self.updated_config,
        }
