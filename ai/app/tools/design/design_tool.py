from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.tools.runtime.catalog import register_runtime_tool_definition


_DESIGN_SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "design" / "awesome-design"
_DESIGN_MD_DIR = _DESIGN_SKILL_DIR / "design-md"


_DESIGN_LIST_PRESETS_DEFINITION = register_runtime_tool_definition(
    name="design.list_presets",
    toolset="design",
    module="app.tools.design.design_tool",
    summary="List built-in DESIGN.md presets available to prototype generation.",
    schema={
        "description": "List built-in DESIGN.md presets available to prototype generation.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
)


_DESIGN_READ_PRESET_DEFINITION = register_runtime_tool_definition(
    name="design.read_preset",
    toolset="design",
    module="app.tools.design.design_tool",
    summary="Read a built-in DESIGN.md preset by preset id.",
    schema={
        "description": "Read a built-in DESIGN.md preset by preset id.",
        "parameters": {
            "type": "object",
            "properties": {
                "preset_id": {
                    "type": "string",
                    "description": "DESIGN.md preset id. Example: ai-agent-console",
                },
            },
            "required": ["preset_id"],
        },
    },
)


def design_list_presets_tool_definition() -> dict[str, str]:
    return {
        "name": _DESIGN_LIST_PRESETS_DEFINITION.name,
        "toolset": _DESIGN_LIST_PRESETS_DEFINITION.toolset,
        "module": _DESIGN_LIST_PRESETS_DEFINITION.module,
        "summary": _DESIGN_LIST_PRESETS_DEFINITION.summary,
    }


def design_read_preset_tool_definition() -> dict[str, str]:
    return {
        "name": _DESIGN_READ_PRESET_DEFINITION.name,
        "toolset": _DESIGN_READ_PRESET_DEFINITION.toolset,
        "module": _DESIGN_READ_PRESET_DEFINITION.module,
        "summary": _DESIGN_READ_PRESET_DEFINITION.summary,
    }


def list_design_presets_handler(args: dict[str, Any]) -> dict[str, Any]:
    _ = args
    presets = [_preset_summary(path) for path in _iter_preset_files()]
    payload = {
        "ok": True,
        "count": len(presets),
        "presets": presets,
    }
    return {
        **payload,
        "content": json.dumps(payload, ensure_ascii=False),
    }


def read_design_preset_handler(args: dict[str, Any]) -> dict[str, Any]:
    preset_id = _normalize_preset_id(args.get("preset_id"))
    if not preset_id:
        return _tool_error("invalid_preset_id", "DESIGN.md preset id is required.")
    preset_file = (_DESIGN_MD_DIR / preset_id / "DESIGN.md").resolve(strict=False)
    if not _is_relative_to(preset_file, _DESIGN_MD_DIR.resolve(strict=False)) or not preset_file.is_file():
        return _tool_error("preset_not_found", f"unknown DESIGN.md preset: {preset_id}")

    content = preset_file.read_text(encoding="utf-8")
    content_chunks = _chunk_text(content, chunk_size=16_000)
    payload = {
        "ok": True,
        "preset_id": preset_id,
        "document_name": "DESIGN.md",
        "path": preset_file.relative_to(_DESIGN_SKILL_DIR).as_posix(),
        "content": content_chunks[0] if content_chunks else "",
        "content_chunks": content_chunks,
        "content_length": len(content),
        "chunk_count": len(content_chunks),
    }
    return {
        **payload,
        "content_json": json.dumps(
            {
                "preset_id": preset_id,
                "document_name": "DESIGN.md",
                "path": payload["path"],
            },
            ensure_ascii=False,
        ),
    }


def _iter_preset_files() -> list[Path]:
    if not _DESIGN_MD_DIR.exists():
        return []
    return sorted(_DESIGN_MD_DIR.glob("*/DESIGN.md"))


def _preset_summary(path: Path) -> dict[str, str]:
    preset_id = path.parent.name
    content = path.read_text(encoding="utf-8")
    title = _first_heading(content)
    description = _frontmatter_value(content, "description")
    return {
        "preset_id": preset_id,
        "title": title or preset_id.replace("-", " ").title(),
        "description": description,
        "document_name": "DESIGN.md",
        "path": path.relative_to(_DESIGN_SKILL_DIR).as_posix(),
    }


def _first_heading(content: str) -> str:
    for line in content.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def _frontmatter_value(content: str, key: str) -> str:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return ""

    prefix = f"{key}:"
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            return ""
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip().strip('"').strip("'")
    return ""


def _normalize_preset_id(value: Any) -> str:
    text = str(value or "").strip().lower()
    allowed = []
    for char in text:
        if char.isalnum() or char in {"-", "_", "."}:
            allowed.append(char)
    return "".join(allowed)


def _chunk_text(value: str, *, chunk_size: int) -> list[str]:
    if not value:
        return []
    return [value[index : index + chunk_size] for index in range(0, len(value), chunk_size)]


def _tool_error(code: str, message: str) -> dict[str, Any]:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "tool_name": "design.read_preset",
        }
    }
    return {
        "ok": False,
        **payload,
        "content": json.dumps(payload, ensure_ascii=False),
    }


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
