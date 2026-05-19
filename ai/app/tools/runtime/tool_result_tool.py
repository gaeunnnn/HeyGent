from __future__ import annotations

from typing import Any

from app.domain.orchestration.agent.tool_result_store import read_raw_tool_result_chunk
from app.tools.runtime.catalog import register_runtime_tool_definition


TOOL_RESULT_READ_SCHEMA = {
    "name": "tool_result.read",
    "description": (
        "Read a bounded chunk from a raw tool result referenced by raw_ref. "
        "Use only when a previous tool observation says the result was truncated and the preview is insufficient."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "raw_ref": {"type": "string", "description": "tool-result:// reference from a truncated tool observation."},
            "offset": {"type": "integer", "description": "Character offset to start reading from.", "default": 0},
            "limit": {"type": "integer", "description": "Maximum characters to return, capped by the runtime.", "default": 8000},
        },
        "required": ["raw_ref"],
    },
}


register_runtime_tool_definition(
    name="tool_result.read",
    toolset="tool-result",
    module="app.tools.runtime.tool_result_tool",
    summary="Read a bounded chunk from a stored raw tool result.",
    schema=TOOL_RESULT_READ_SCHEMA,
)


def tool_result_read_handler(args: dict[str, Any]) -> dict[str, Any]:
    return read_raw_tool_result_chunk(
        str(args.get("raw_ref") or ""),
        offset=_int_arg(args.get("offset"), default=0),
        limit=_int_arg(args.get("limit"), default=8000),
    )


def _int_arg(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
