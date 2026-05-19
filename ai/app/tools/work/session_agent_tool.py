from __future__ import annotations

from app.tools.runtime.catalog import register_runtime_tool_definition


SESSION_AGENT_TASK_SCHEMA = {
    "name": "session_agent_task",
    "description": (
        "Create a child work item assigned to one configured session agent and run it. "
        "For team-lead-owned work, use this when a configured session agent can naturally own "
        "an independent deliverable, focused specialty work, or a clearly separated part "
        "of the request. Do not invent an assignee when no configured session agent fits."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Short child work title shown on the work board.",
            },
            "instruction": {
                "type": "string",
                "description": "Concrete instruction the assigned session agent must execute.",
            },
            "assigneeAgentId": {
                "type": "string",
                "description": "Optional session agent profile id. If omitted, the first session agent is selected.",
            },
            "assigneeHint": {
                "type": "string",
                "description": "Optional agent name, role, or capability hint used when assigneeAgentId is omitted.",
            },
            "description": {
                "type": "string",
                "description": "Optional detailed child work description.",
            },
            "expectedDeliverable": {
                "type": "string",
                "description": "Expected output from the child work.",
            },
            "acceptanceCriteria": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Completion criteria for the child work.",
            },
            "constraints": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Scope, format, deadline, or other constraints.",
            },
            "requiredSkillNames": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional skill names the assigned session agent must actually have.",
            },
            "labelNames": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Existing label names to attach. Parent labels are inherited automatically.",
            },
            "blockParentUntilDone": {
                "type": "boolean",
                "description": "Whether the child work blocks the parent until the child reaches a terminal status. Defaults to false.",
            },
        },
        "required": ["title", "instruction"],
    },
}

_SESSION_AGENT_TASK_DEFINITION = register_runtime_tool_definition(
    name="session_agent_task",
    toolset="work",
    module="app.tools.work.session_agent_tool",
    summary="Create and run a child work item assigned to a configured session agent.",
    schema=SESSION_AGENT_TASK_SCHEMA,
    result_format="json",
)


def session_agent_tool_definition() -> dict[str, object]:
    return {
        "name": _SESSION_AGENT_TASK_DEFINITION.name,
        "toolset": _SESSION_AGENT_TASK_DEFINITION.toolset,
        "module": _SESSION_AGENT_TASK_DEFINITION.module,
        "summary": _SESSION_AGENT_TASK_DEFINITION.summary,
        "schema": _SESSION_AGENT_TASK_DEFINITION.schema,
        "result_format": _SESSION_AGENT_TASK_DEFINITION.result_format,
    }
