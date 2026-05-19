from __future__ import annotations

from app.domain.orchestration.capabilities import apply_task_capabilities, resolve_task_capabilities


class DummySkillRegistry:
    def __init__(self) -> None:
        self._skills = {
            "korea-weather": {
                "name": "korea-weather",
                "body": "`http_get` runtime tool 로 날씨 프록시를 조회한다.",
            },
            "mattermost-send": {
                "name": "mattermost-send",
                "metadata": {"runtime": {"required_toolsets": ["messaging"]}},
                "body": "`mattermost.send` runtime tool 로 메시지를 보낸다.",
            },
            "terminal-skill": {
                "name": "terminal-skill",
                "metadata": {"runtime": {"requires_toolsets": ["terminal"]}},
                "body": "터미널로 로컬 상태를 확인한다.",
            },
            "notion": {
                "name": "notion",
                "body": "`notion.execute` runtime tool 로 Notion 프록시 명령을 실행한다.",
            },
            "awesome-design": {
                "name": "awesome-design",
                "description": "`design.list_presets`, `design.read_preset`, `prototype.create_artifact` runtime tool 로 DESIGN.md 기반 React 프로토타입을 만든다.",
                "body": "# Awesome DESIGN.md",
            },
        }


def test_capability_resolver_adds_toolsets_required_by_enabled_skills():
    capabilities = resolve_task_capabilities(
        {
            "enabled_toolsets": ["skills"],
            "enabledSkillNames": ["korea-weather"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_skill_names == ("korea-weather",)
    assert capabilities.enabled_toolsets == ("skills", "web", "tool-result")
    assert "http_get" in capabilities.enabled_tool_names
    assert "tool_result.read" in capabilities.enabled_tool_names


def test_capability_resolver_uses_skill_metadata_runtime_toolsets():
    capabilities = resolve_task_capabilities(
        {
            "enabled_toolsets": ["skills"],
            "enabledSkillNames": ["mattermost-send"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_toolsets == ("skills", "messaging", "tool-result")
    assert "mattermost.send" in capabilities.enabled_tool_names


def test_capability_resolver_uses_reference_requires_toolsets_metadata():
    capabilities = resolve_task_capabilities(
        {
            "enabled_toolsets": ["skills"],
            "enabledSkillNames": ["terminal-skill"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_toolsets == ("skills", "terminal", "tool-result")
    assert "terminal.run" in capabilities.enabled_tool_names


def test_capability_resolver_adds_notion_toolset_from_skill_body():
    capabilities = resolve_task_capabilities(
        {
            "enabled_toolsets": ["skills"],
            "enabledSkillNames": ["notion"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_toolsets == ("skills", "notion", "tool-result")
    assert "notion.execute" in capabilities.enabled_tool_names


def test_capability_resolver_adds_design_toolset_from_skill_description():
    capabilities = resolve_task_capabilities(
        {
            "enabled_toolsets": ["skills"],
            "enabledSkillNames": ["awesome-design"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_toolsets == ("skills", "design", "prototype", "tool-result")
    assert "design.read_preset" in capabilities.enabled_tool_names
    assert "prototype.create_artifact" in capabilities.enabled_tool_names


def test_capability_resolver_opens_skill_toolsets_without_requested_toolsets():
    capabilities = resolve_task_capabilities(
        {
            "enabledSkillNames": ["mattermost-send"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_toolsets == ("skills", "messaging", "tool-result")
    assert "mattermost.send" in capabilities.enabled_tool_names


def test_capability_resolver_uses_default_toolsets_without_explicit_request():
    capabilities = resolve_task_capabilities(
        {},
        skill_registry=DummySkillRegistry(),
        default_toolsets=("skills", "web"),
    )

    assert capabilities.enabled_toolsets == ("skills", "web", "tool-result")
    assert "http_get" in capabilities.enabled_tool_names
    assert "tool_result.read" in capabilities.enabled_tool_names


def test_capability_resolver_keeps_tuple_default_toolsets_with_enabled_skills():
    capabilities = resolve_task_capabilities(
        {
            "enabledSkillNames": ["mattermost-send"],
        },
        skill_registry=DummySkillRegistry(),
        default_toolsets=("skills", "session", "planning", "work"),
    )

    assert capabilities.enabled_toolsets == ("skills", "session", "planning", "work", "messaging", "tool-result")
    assert "session_agent_task" in capabilities.enabled_tool_names
    assert "mattermost.send" in capabilities.enabled_tool_names


def test_capability_resolver_respects_explicit_toolsets_without_skills():
    capabilities = resolve_task_capabilities(
        {
            "enabled_toolsets": ["session", "planning"],
            "enabledSkillNames": ["mattermost-send"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_toolsets == ("session", "planning")
    assert "mattermost.send" not in capabilities.enabled_tool_names
    assert capabilities.skill_required_toolsets == ()


def test_capability_resolver_adds_tool_result_reader_for_explicit_data_toolsets():
    capabilities = resolve_task_capabilities(
        {
            "enabled_toolsets": ["web"],
        },
        skill_registry=DummySkillRegistry(),
    )

    assert capabilities.enabled_toolsets == ("web", "tool-result")
    assert "http_get" in capabilities.enabled_tool_names
    assert "tool_result.read" in capabilities.enabled_tool_names


def test_apply_task_capabilities_updates_payload_with_diagnostics():
    task_input = {
        "enabled_toolsets": ["skills"],
        "enabledSkillNames": ["korea-weather"],
    }

    apply_task_capabilities(task_input, skill_registry=DummySkillRegistry())

    assert task_input["enabled_toolsets"] == ["skills", "web", "tool-result"]
    assert task_input["toolsets"] == ["skills", "web", "tool-result"]
    assert task_input["capability_resolution"]["skillRequiredToolsets"] == ["web"]
