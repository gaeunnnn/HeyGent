from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.tools.runtime.catalog import RuntimeToolDefinition, list_registered_runtime_tool_definitions


@dataclass(frozen=True, slots=True)
class RuntimeToolEntry:
    definition: RuntimeToolDefinition
    handler: Callable


def discover_runtime_tool_definitions() -> list[RuntimeToolDefinition]:
    _discover_runtime_tool_modules()
    return list_registered_runtime_tool_definitions()


def build_runtime_tool_entries(handler_by_name: dict[str, Callable]) -> dict[str, RuntimeToolEntry]:
    entries: dict[str, RuntimeToolEntry] = {}
    for definition in discover_runtime_tool_definitions():
        if not definition.enabled:
            continue
        handler = handler_by_name.get(definition.name)
        if handler is None:
            continue
        entries[definition.name] = RuntimeToolEntry(definition=definition, handler=handler)
    return entries


def list_runtime_tool_definitions(handler_by_name: dict[str, Callable]) -> list[dict[str, Any]]:
    entries = build_runtime_tool_entries(handler_by_name)
    check_results: dict[Callable, bool] = {}
    return [
        {
            "name": entry.definition.name,
            "toolset": entry.definition.toolset,
            "summary": entry.definition.summary,
            "module": entry.definition.module,
            "schema": entry.definition.schema,
            "result_format": entry.definition.result_format,
            "requires_env": list(entry.definition.requires_env),
            "unavailable_reason": entry.definition.unavailable_reason,
        }
        for _, entry in sorted(entries.items())
        if _definition_is_available(entry.definition, check_results=check_results)
    ]


def list_runtime_tool_schemas(handler_by_name: dict[str, Callable]) -> list[dict[str, Any]]:
    entries = build_runtime_tool_entries(handler_by_name)
    check_results: dict[Callable, bool] = {}
    return [
        {"type": "function", "function": entry.definition.schema}
        for _, entry in sorted(entries.items())
        if _definition_is_available(entry.definition, check_results=check_results)
    ]


def list_runtime_tool_availability(handler_by_name: dict[str, Callable]) -> list[dict[str, Any]]:
    entries = build_runtime_tool_entries(handler_by_name)
    check_results: dict[Callable, bool] = {}
    availability: list[dict[str, Any]] = []
    for _, entry in sorted(entries.items()):
        available = _definition_is_available(entry.definition, check_results=check_results)
        availability.append(
            {
                "name": entry.definition.name,
                "toolset": entry.definition.toolset,
                "summary": entry.definition.summary,
                "module": entry.definition.module,
                "available": available,
                "enabled": entry.definition.enabled,
                "requires_env": list(entry.definition.requires_env),
                "unavailable_reason": None if available else entry.definition.unavailable_reason,
            }
        )
    return availability


def _definition_is_available(
    definition: RuntimeToolDefinition,
    *,
    check_results: dict[Callable, bool] | None = None,
) -> bool:
    if not definition.enabled:
        return False
    if definition.check_fn is None:
        return True
    if check_results is not None and definition.check_fn in check_results:
        return check_results[definition.check_fn]
    try:
        available = bool(definition.check_fn())
    except Exception:
        # check_fn은 도구 노출 여부만 판단한다. 검사 자체가 실패하면 모델에게
        # "쓸 수 있는 도구"처럼 보여 반복 실패를 만들지 않도록 숨긴다.
        available = False
    if check_results is not None:
        check_results[definition.check_fn] = available
    return available


def _discover_runtime_tool_modules() -> None:
    from app.tools.design import design_tool  # noqa: F401
    from app.tools.delegation import delegate_tool  # noqa: F401
    from app.tools.file import file_tools  # noqa: F401
    from app.tools.messaging import mattermost_tool  # noqa: F401
    from app.tools.notion import notion_tool  # noqa: F401
    from app.tools.planning import todo_tool  # noqa: F401
    from app.tools.prototype import prototype_tool  # noqa: F401
    from app.tools.session import session_search_tool  # noqa: F401
    from app.tools.skills import skill_execute_tool  # noqa: F401
    from app.tools.skills import skill_script_tool  # noqa: F401
    from app.tools.skills import skills_tool  # noqa: F401
    from app.tools.terminal import terminal_tool  # noqa: F401
    from app.tools.runtime import tool_result_tool  # noqa: F401
    from app.tools.web import web_tools  # noqa: F401
    from app.tools.work import session_agent_tool  # noqa: F401
