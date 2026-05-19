from app.tools.runtime.local_tool_runtime import LocalToolRuntime
from app.tools.runtime.toolsets import resolve_runtime_tool_names


class DummySessionStore:
    pass


def test_design_toolset_exposes_design_preset_readers():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("design",))

    names = [definition["name"] for definition in definitions]
    assert names == ["design.list_presets", "design.read_preset"]
    assert "design.list_presets" in resolve_runtime_tool_names(("design",))
    assert "design.read_preset" in resolve_runtime_tool_names(("design",))


def test_design_read_preset_returns_design_md_content():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="design.read_preset",
        args={"preset_id": "cursor"},
        enabled_toolsets=("design",),
    )

    assert result["ok"] is True
    assert result["preset_id"] == "cursor"
    assert result["document_name"] == "DESIGN.md"
    assert "Cursor" in result["content"]
    assert "Cursor" in "".join(result["content_chunks"])
    assert result["content_length"] == len("".join(result["content_chunks"]))


def test_design_list_presets_includes_frontmatter_descriptions():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="design.list_presets",
        args={},
        enabled_toolsets=("design",),
    )

    cursor = next(preset for preset in result["presets"] if preset["preset_id"] == "cursor")
    assert result["ok"] is True
    assert "description" in cursor
    assert "AI-first code editor" in cursor["description"]


def test_design_read_preset_preserves_dotted_ids():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="design.read_preset",
        args={"preset_id": "linear.app"},
        enabled_toolsets=("design",),
    )

    assert result["ok"] is True
    assert result["preset_id"] == "linear.app"
    assert "Linear" in result["content"]
