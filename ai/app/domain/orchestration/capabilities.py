from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.tools.runtime.toolsets import RUNTIME_TOOLSETS, resolve_runtime_tool_names

TOOL_RESULT_READER_SOURCE_TOOLSETS = {
    "all",
    "*",
    "coding",
    "delegation",
    "design",
    "file",
    "gmail",
    "local-core",
    "messaging",
    "notion",
    "prototype",
    "safe",
    "skill-runtime",
    "terminal",
    "web",
    "work",
}


@dataclass(frozen=True, slots=True)
class TaskCapabilityResolution:
    enabled_toolsets: tuple[str, ...] | None
    enabled_skill_names: tuple[str, ...]
    enabled_tool_names: tuple[str, ...] | None
    skill_required_toolsets: tuple[str, ...]


def resolve_task_capabilities(
    task_input: dict[str, Any],
    *,
    skill_registry: Any | None = None,
    default_toolsets: tuple[str, ...] | list[str] | None = None,
) -> TaskCapabilityResolution:
    requested_toolsets = _normalized_toolsets(task_input.get("enabled_toolsets"))
    normalized_default_toolsets = _normalized_toolsets(default_toolsets)
    enabled_skill_names = _enabled_skill_names(task_input)
    skill_required_toolsets = _skill_required_toolsets(enabled_skill_names, skill_registry=skill_registry)
    if requested_toolsets is None and normalized_default_toolsets is None and not enabled_skill_names:
        return TaskCapabilityResolution(
            enabled_toolsets=None,
            enabled_skill_names=tuple(enabled_skill_names),
            enabled_tool_names=None,
            skill_required_toolsets=(),
        )

    resolved_toolsets = list(requested_toolsets or normalized_default_toolsets or ())
    skills_allowed = requested_toolsets is None or "skills" in requested_toolsets or "skill-runtime" in requested_toolsets
    if not skills_allowed:
        if _should_add_tool_result_reader(resolved_toolsets):
            _append_unique(resolved_toolsets, "tool-result")
        enabled_tool_names = tuple(sorted(resolve_runtime_tool_names(resolved_toolsets) or ()))
        return TaskCapabilityResolution(
            enabled_toolsets=tuple(resolved_toolsets),
            enabled_skill_names=tuple(enabled_skill_names),
            enabled_tool_names=enabled_tool_names,
            skill_required_toolsets=(),
        )
    if enabled_skill_names:
        _append_unique(resolved_toolsets, "skills")
    for toolset in skill_required_toolsets:
        _append_unique(resolved_toolsets, toolset)
    if _should_add_tool_result_reader(resolved_toolsets):
        _append_unique(resolved_toolsets, "tool-result")

    enabled_tool_names = tuple(sorted(resolve_runtime_tool_names(resolved_toolsets) or ()))
    return TaskCapabilityResolution(
        enabled_toolsets=tuple(resolved_toolsets),
        enabled_skill_names=tuple(enabled_skill_names),
        enabled_tool_names=enabled_tool_names,
        skill_required_toolsets=tuple(skill_required_toolsets),
    )


def apply_task_capabilities(
    task_input: dict[str, Any],
    *,
    skill_registry: Any | None = None,
    default_toolsets: tuple[str, ...] | list[str] | None = None,
) -> TaskCapabilityResolution:
    capabilities = resolve_task_capabilities(
        task_input,
        skill_registry=skill_registry,
        default_toolsets=default_toolsets,
    )
    if capabilities.enabled_skill_names:
        task_input["enabledSkillNames"] = list(capabilities.enabled_skill_names)
    if capabilities.enabled_toolsets is not None:
        task_input["enabled_toolsets"] = list(capabilities.enabled_toolsets)
        task_input["toolsets"] = list(capabilities.enabled_toolsets)
    task_input["capability_resolution"] = {
        "enabledSkillNames": list(capabilities.enabled_skill_names),
        "enabledToolsets": list(capabilities.enabled_toolsets or []),
        "skillRequiredToolsets": list(capabilities.skill_required_toolsets),
    }
    return capabilities


def _normalized_toolsets(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)):
        return None
    normalized: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            _append_unique(normalized, text)
    return tuple(normalized)


def _enabled_skill_names(task_input: dict[str, Any]) -> list[str]:
    source = task_input.get("enabledSkillNames")
    if not isinstance(source, list):
        profile = task_input.get("targetAgentProfile")
        config = profile.get("configSnapshot") if isinstance(profile, dict) else {}
        source = config.get("skills") if isinstance(config, dict) else []
    names: list[str] = []
    for item in source or []:
        text = str(item or "").strip()
        if text:
            _append_unique(names, text)
    return names


def _skill_required_toolsets(skill_names: list[str], *, skill_registry: Any | None) -> list[str]:
    skills = getattr(skill_registry, "_skills", {}) if skill_registry is not None else {}
    required: list[str] = []
    for skill_name in skill_names:
        skill = skills.get(skill_name)
        if not isinstance(skill, dict):
            continue
        for toolset in _metadata_toolsets(skill):
            _append_unique(required, toolset)
        for toolset in _body_toolsets(str(skill.get("description") or "")):
            _append_unique(required, toolset)
        for toolset in _body_toolsets(str(skill.get("body") or "")):
            _append_unique(required, toolset)
    return required


def _metadata_toolsets(skill: dict[str, Any]) -> list[str]:
    runtime = (skill.get("metadata") or {}).get("runtime") if isinstance(skill.get("metadata"), dict) else {}
    if not isinstance(runtime, dict):
        return []
    values = runtime.get("required_toolsets") or runtime.get("requires_toolsets") or runtime.get("toolsets") or []
    if not isinstance(values, list):
        return []
    return [text for item in values if (text := str(item or "").strip()) in RUNTIME_TOOLSETS]


def _body_toolsets(body: str) -> list[str]:
    tool_to_toolsets = _tool_to_toolsets()
    required: list[str] = []
    for match in re.finditer(r"`([^`]+)`", body):
        token = match.group(1).strip()
        if token in RUNTIME_TOOLSETS:
            _append_unique(required, token)
            continue
        for toolset in tool_to_toolsets.get(token, ()):
            _append_unique(required, toolset)
    for match in re.finditer(r"toolsets\s*=\s*\[([^\]]+)\]", body):
        for token in re.findall(r"['\"]([^'\"]+)['\"]", match.group(1)):
            if token in RUNTIME_TOOLSETS:
                _append_unique(required, token)
    return required


def _tool_to_toolsets() -> dict[str, tuple[str, ...]]:
    mapping: dict[str, list[str]] = {}
    for toolset_name, definition in RUNTIME_TOOLSETS.items():
        for tool_name in definition.tools:
            mapping.setdefault(tool_name, []).append(toolset_name)
    return {tool_name: tuple(toolsets) for tool_name, toolsets in mapping.items()}


def _should_add_tool_result_reader(toolsets: list[str]) -> bool:
    return any(toolset in TOOL_RESULT_READER_SOURCE_TOOLSETS for toolset in toolsets)


def _append_unique(values: list[str], item: str) -> None:
    if item not in values:
        values.append(item)

