from __future__ import annotations

import json
from pathlib import Path

from app.tools.runtime.local_tool_runtime import LocalToolRuntime


class DummySkillRegistry:
    def __init__(self, skill_path: Path) -> None:
        self._skills = {
            "demo-skill": {
                "name": "demo-skill",
                "path": str(skill_path),
                "body": "# Demo",
            }
        }


class DummyTranscriptStore:
    pass


class DummyAgentRepository:
    def __init__(self, values: dict[str, dict[str, str]]) -> None:
        self.values = values

    def get_agent_secret_values(self, *, profile_id: str, owner_key: str, document_key: str, section_key: str | None = None):
        assert profile_id == "agent_profile_demo"
        assert owner_key == "owner-1"
        assert document_key == "SECRETS.md"
        if section_key is None:
            return self.values
        return {section_key: self.values.get(section_key, {})}


def _runtime(
    tmp_path: Path,
    monkeypatch,
    *,
    secrets: dict[str, dict[str, str]] | None = None,
) -> LocalToolRuntime:
    skill_dir = tmp_path / "skills" / "demo-skill"
    scripts_dir = skill_dir / "scripts"
    scripts_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text("---\nname: demo-skill\ndescription: demo\n---\n# Demo\n", encoding="utf-8")
    (scripts_dir / "check_runtime.py").write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "import json",
                "import os",
                "import sys",
                "print(json.dumps({",
                "    'id_present': bool(os.environ.get('KSKILL_SRT_ID')),",
                "    'password_present': bool(os.environ.get('KSKILL_SRT_PASSWORD')),",
                "    'argv': sys.argv[1:],",
                "}, ensure_ascii=False))",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(LocalToolRuntime, "_default_skills_root", staticmethod(lambda: tmp_path / "skills"))
    return LocalToolRuntime(
        skill_registry=DummySkillRegistry(skill_path),
        session_store=DummyTranscriptStore(),
        workspace_root=tmp_path,
        owner_key="owner-1",
        agent_repository=DummyAgentRepository(secrets or {}),
        runtime_context={"targetAgentProfile": {"profileId": "agent_profile_demo"}},
    )


def test_skill_run_script_injects_agent_secrets_into_process_env(tmp_path: Path, monkeypatch):
    runtime = _runtime(
        tmp_path,
        monkeypatch,
        secrets={
            "demo-skill": {
                "KSKILL_SRT_ID": "secret-id",
                "KSKILL_SRT_PASSWORD": "secret-password",
            }
        },
    )

    result = runtime.run_call(
        name="skill.run_script",
        enabled_toolsets=("skill-runtime",),
        args={
            "skill_name": "demo-skill",
            "script_path": "scripts/check_runtime.py",
            "argv": ["--mode", "search"],
            "required_secret_keys": ["KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD"],
        },
    )

    assert result["ok"] is True
    payload = json.loads(result["stdout"])
    assert payload == {
        "id_present": True,
        "password_present": True,
        "argv": ["--mode", "search"],
    }
    assert "secret-id" not in json.dumps(result, ensure_ascii=False)
    assert "secret-password" not in json.dumps(result, ensure_ascii=False)


def test_skill_run_script_reports_missing_required_secret_without_running(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch, secrets={"demo-skill": {"KSKILL_SRT_ID": "secret-id"}})

    result = runtime.run_call(
        name="skill.run_script",
        enabled_toolsets=("skill-runtime",),
        args={
            "skill_name": "demo-skill",
            "script_path": "scripts/check_runtime.py",
            "required_secret_keys": ["KSKILL_SRT_ID", "KSKILL_SRT_PASSWORD"],
        },
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "missing_skill_secrets"
    assert result["missing_secret_keys"] == ["KSKILL_SRT_PASSWORD"]


def test_skill_run_script_rejects_paths_outside_skill_scripts(tmp_path: Path, monkeypatch):
    runtime = _runtime(tmp_path, monkeypatch)

    result = runtime.run_call(
        name="skill.run_script",
        enabled_toolsets=("skill-runtime",),
        args={
            "skill_name": "demo-skill",
            "script_path": "../outside.py",
        },
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "skill_script_not_allowed"
