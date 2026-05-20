from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Iterable


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RuntimeToolsetDefinition:
    description: str
    tools: tuple[str, ...] = ()
    includes: tuple[str, ...] = ()


RUNTIME_TOOLSETS: dict[str, RuntimeToolsetDefinition] = {
    "skills": RuntimeToolsetDefinition(
        description="Skill catalog inspection tools.",
        tools=("skills.list", "skills.read", "skills.read_file", "skill.execute"),
    ),
    "skill-runtime": RuntimeToolsetDefinition(
        description="Restricted skill execution tools.",
        tools=("skill.execute", "skill.run_script"),
    ),
    "session": RuntimeToolsetDefinition(
        description="Session record and recall tools.",
        tools=("session.record", "session.search"),
    ),
    "planning": RuntimeToolsetDefinition(
        description="Todo and planning tools.",
        tools=("todo",),
    ),
    "terminal": RuntimeToolsetDefinition(
        description="Local terminal execution tools.",
        tools=("terminal.run",),
    ),
    "web": RuntimeToolsetDefinition(
        description="Direct HTTP fetch tools.",
        tools=("http_get",),
    ),
    "tool-result": RuntimeToolsetDefinition(
        description="Bounded access to stored raw tool results.",
        tools=("tool_result.read",),
    ),
    "messaging": RuntimeToolsetDefinition(
        description="Outbound messaging tools.",
        tools=("mattermost.send",),
    ),
    "notion": RuntimeToolsetDefinition(
        description="Notion workspace proxy execution tools.",
        tools=("notion.execute",),
    ),
    "gmail": RuntimeToolsetDefinition(
        description="Gmail account proxy execution tools (read updates label, fetch messages, build newsletter digests).",
        tools=("gmail.execute",),
    ),
    "health": RuntimeToolsetDefinition(
        description="Authenticated health data proxy execution tools.",
        tools=("health.execute",),
    ),
    "design": RuntimeToolsetDefinition(
        description="DESIGN.md preset inspection tools for prototype generation.",
        tools=("design.list_presets", "design.read_preset"),
    ),
    "prototype": RuntimeToolsetDefinition(
        description="Session-scoped React prototype artifact tools.",
        tools=("prototype.create_artifact", "prototype.get_active_artifact"),
    ),
    "file": RuntimeToolsetDefinition(
        description="Local file read, write, patch, and search tools.",
        tools=("read_file", "write_file", "patch", "search_files"),
    ),
    "coding": RuntimeToolsetDefinition(
        description="Local coding tools that can inspect and edit files.",
        includes=("file", "terminal"),
    ),
    "safe": RuntimeToolsetDefinition(
        description="Safe runtime tools without terminal execution.",
        includes=("skills", "session", "planning", "web"),
    ),
    "delegation": RuntimeToolsetDefinition(
        description="Worker delegation tools.",
        tools=("delegate_task",),
    ),
    "work": RuntimeToolsetDefinition(
        description="Work board assignment tools.",
        tools=("session_agent_task",),
    ),
    "local-core": RuntimeToolsetDefinition(
        description="Current minimal local runtime tool bundle.",
        includes=("skills", "session", "planning", "terminal", "file", "web", "work"),
    ),
}


def get_runtime_toolset(name: str) -> RuntimeToolsetDefinition | None:
    return RUNTIME_TOOLSETS.get(name)


def list_runtime_toolsets() -> list[str]:
    return sorted(RUNTIME_TOOLSETS)


def resolve_runtime_tool_names(enabled_toolsets: Iterable[str] | None) -> set[str] | None:
    if enabled_toolsets is None:
        return None

    resolved: set[str] = set()
    for name in enabled_toolsets:
        normalized_name = str(name or "").strip()
        if not normalized_name:
            continue
        if normalized_name in {"all", "*"}:
            for toolset_name in list_runtime_toolsets():
                resolved.update(_resolve_runtime_toolset(toolset_name, seen=set()))
            continue
        resolved.update(_resolve_runtime_toolset(normalized_name, seen=set()))
    return resolved


def get_runtime_toolset_info(name: str) -> dict[str, object] | None:
    toolset = get_runtime_toolset(name)
    if toolset is None:
        return None
    resolved = sorted(_resolve_runtime_toolset(name, seen=set()))
    return {
        "name": name,
        "description": toolset.description,
        "direct_tools": list(toolset.tools),
        "includes": list(toolset.includes),
        "resolved_tools": resolved,
        "tool_count": len(resolved),
    }


def _resolve_runtime_toolset(name: str, *, seen: set[str]) -> set[str]:
    if name in seen:
        return set()
    definition = RUNTIME_TOOLSETS.get(name)
    if definition is None:
        # DB/settings 에 남은 과거 toolset(browser 등)이나 잘못 저장된 toolset 이
        # 한 번 들어왔다고 실행 전체를 죽이면, 모델은 실제 사용 가능한 도구도
        # 받지 못한다. 알 수 없는 toolset 은 빈 목록으로 처리하고,
        # 공개 설정 저장 단계에서만 allowlist 로 막는다.
        logger.warning("Ignoring unknown runtime toolset: %s", name)
        return set()

    seen.add(name)
    resolved = set(definition.tools)
    for included in definition.includes:
        resolved.update(_resolve_runtime_toolset(included, seen=seen))
    return resolved
