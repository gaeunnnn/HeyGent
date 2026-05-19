from __future__ import annotations

from typing import Any

from app.domain.orchestration.prompts.skill_utils import default_skills_root, iter_skill_files, load_skill_document


_CONDITION_KEYS = (
    "fallback_for_toolsets",
    "requires_toolsets",
    "fallback_for_tools",
    "requires_tools",
)


class SkillRegistry:
    """In-memory skill metadata store populated from app/skills assets."""

    def __init__(self) -> None:
        self._skills: dict[str, dict] = {}

    def register_many(self, skills: list[dict]) -> None:
        for skill in skills:
            name = str(skill.get("name") or "").strip()
            if not name:
                continue
            self._skills[name] = dict(skill)

    def resolve_hints(self, hints: list[str]) -> list[dict]:
        return [self._skills[hint] for hint in hints if hint in self._skills]

    def catalog_items(self, *, allowed_names: set[str] | None = None) -> list[dict]:
        names = sorted(self._skills)
        if allowed_names is not None:
            names = [name for name in names if name in allowed_names]
        return [self._skills[name] for name in names]


class SkillLoader:
    def __init__(self, *, skills_root=None) -> None:
        self.skills_root = skills_root or default_skills_root()

    def load_builtin(self) -> list[dict]:
        skills: list[dict] = []
        for path in iter_skill_files(self.skills_root):
            document = load_skill_document(path)
            skills.append(
                {
                    "name": document.name,
                    "description": document.description,
                    "path": str(document.path),
                    "body": document.body,
                    "metadata": document.metadata,
                }
            )
        return skills


class SkillPromptBuilder:
    """Convert requested skill hints into prompt context."""

    def __init__(self, registry) -> None:
        self.registry = registry

    def build(self, *, input_payload: dict, available_tools: list[dict[str, Any]] | None = None) -> str:
        hints = [str(item).strip() for item in input_payload.get("skill_hints") or [] if str(item).strip()]
        resolved = self._filter_by_tool_conditions(self.registry.resolve_hints(hints), available_tools=available_tools)
        if not resolved:
            return ""
        lines = ["적용 가능한 작업 힌트:"]
        for skill in resolved:
            lines.append(f"[{skill['name']}]")
            body = str(skill.get("body") or "").strip()
            if body:
                lines.append(body[:600].rstrip())
        return "\n".join(lines)

    def build_catalog(
        self,
        *,
        input_payload: dict | None = None,
        available_tools: list[dict[str, Any]] | None = None,
    ) -> str:
        items = self._filter_by_tool_conditions(
            self.registry.catalog_items(
                allowed_names=_allowed_skill_names(input_payload or {})
            ),
            available_tools=available_tools,
        )
        if not items:
            return ""

        lines = [
            "사용 가능한 skill 설명:",
            "- 아래 목록은 현재 실행 에이전트가 직접 사용할 수 있는 skill의 이름과 설명입니다.",
            "- 작업을 시작할 때 먼저 아래 목록에서 사용자 요청을 처리할 수 있는 skill 후보가 있는지 확인하세요.",
            "- 세션 에이전트 후보가 더 직접적으로 맞으면 이 목록에 억지로 맞추지 말고 세션 에이전트 배정을 검토하세요.",
            "- 사용자 입력을 직접 수행할 수 있는 skill이 있으면 일반 도구를 바로 호출하기보다 해당 skill을 최대한 우선 후보로 삼으세요.",
            "- 관련 skill 후보를 선택했다면 `skills.read` 또는 `skill.execute`로 본문을 먼저 확인한 뒤, 본문에 적힌 runtime tool 순서를 따르세요.",
            "- 여러 skill이 수행할 수 있으면 요청을 가장 직접적으로 처리할 skill을 중심으로 삼고 필요한 경우 다른 skill도 함께 참고하세요.",
            "- 전혀 관련 있는 skill이 없을 때만 skill 없이 진행하고, skill 본문에 제한이나 우선 절차가 있으면 그 절차를 우선하세요.",
            "- skill은 별도 실행 도구가 아니며, 실제 행동은 현재 제공된 runtime tool만 사용하세요.",
        ]
        for skill in items:
            name = str(skill.get("name") or "").strip()
            description = str(skill.get("description") or "").strip()
            if not name:
                continue
            if len(description) > 180:
                description = description[:177].rstrip() + "..."
            lines.append(f"- `{name}`: {description}" if description else f"- `{name}`")
        return "\n".join(lines)

    def _filter_by_tool_conditions(
        self,
        items: list[dict],
        *,
        available_tools: list[dict[str, Any]] | None,
    ) -> list[dict]:
        available_tool_names, available_toolsets = _available_tool_surface(available_tools)
        return [
            item
            for item in items
            if _skill_should_show(
                _skill_conditions(item),
                available_tools=available_tool_names,
                available_toolsets=available_toolsets,
            )
        ]


def _allowed_skill_names(input_payload: dict) -> set[str] | None:
    if "enabledSkillNames" not in input_payload:
        return None
    return {
        str(item).strip()
        for item in list(input_payload.get("enabledSkillNames") or [])
        if str(item).strip()
    }


def _available_tool_surface(
    available_tools: list[dict[str, Any]] | None,
) -> tuple[set[str] | None, set[str] | None]:
    if available_tools is None:
        return None, None
    tool_names: set[str] = set()
    toolsets: set[str] = set()
    for tool in available_tools:
        name = str(tool.get("name") or "").strip()
        toolset = str(tool.get("toolset") or "").strip()
        if name:
            tool_names.add(name)
        if toolset:
            toolsets.add(toolset)
    return tool_names, toolsets


def _skill_should_show(
    conditions: dict[str, list[str]],
    *,
    available_tools: set[str] | None,
    available_toolsets: set[str] | None,
) -> bool:
    if available_tools is None and available_toolsets is None:
        return True

    tool_names = available_tools or set()
    toolsets = available_toolsets or set()
    for toolset in conditions.get("fallback_for_toolsets", []):
        if toolset in toolsets:
            return False
    for tool_name in conditions.get("fallback_for_tools", []):
        if tool_name in tool_names:
            return False
    for toolset in conditions.get("requires_toolsets", []):
        if toolset not in toolsets:
            return False
    for tool_name in conditions.get("requires_tools", []):
        if tool_name not in tool_names:
            return False
    return True


def _skill_conditions(skill: dict[str, Any]) -> dict[str, list[str]]:
    metadata = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
    runtime = metadata.get("runtime") if isinstance(metadata, dict) else {}
    hermes = metadata.get("hermes") if isinstance(metadata, dict) else {}
    if not isinstance(runtime, dict):
        runtime = {}
    if not isinstance(hermes, dict):
        hermes = {}
    return {
        key: _string_list(runtime.get(key, hermes.get(key, [])))
        for key in _CONDITION_KEYS
    }


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := str(item or "").strip())]
