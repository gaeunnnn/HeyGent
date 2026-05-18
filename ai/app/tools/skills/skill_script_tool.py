from __future__ import annotations

from app.tools.runtime.catalog import register_runtime_tool_definition


_SKILL_RUN_SCRIPT_TOOL_DEFINITION = register_runtime_tool_definition(
    name="skill.run_script",
    toolset="skill-runtime",
    module="app.tools.skills.skill_script_tool",
    summary="Run a bundled Python script inside an enabled skill with optional agent secret injection.",
    schema={
        "description": (
            "Run a Python script bundled under an enabled skill's scripts/ directory. "
            "Agent secrets are injected only into the child process environment and are not returned."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "description": "Registered skill name.",
                },
                "script_path": {
                    "type": "string",
                    "description": "Path relative to the skill directory, for example scripts/srt_booking.py.",
                },
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Arguments passed to the script after the script path.",
                },
                "required_secret_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Secret environment variable names that must exist before the script runs.",
                },
                "timeout_seconds": {
                    "type": "number",
                    "description": "Optional timeout in seconds. Defaults to 30.",
                },
            },
            "required": ["skill_name", "script_path"],
        },
    },
)


def skill_script_tool_definition() -> dict[str, str]:
    return {
        "name": _SKILL_RUN_SCRIPT_TOOL_DEFINITION.name,
        "toolset": _SKILL_RUN_SCRIPT_TOOL_DEFINITION.toolset,
        "module": _SKILL_RUN_SCRIPT_TOOL_DEFINITION.module,
        "summary": _SKILL_RUN_SCRIPT_TOOL_DEFINITION.summary,
    }
