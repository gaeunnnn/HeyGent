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
