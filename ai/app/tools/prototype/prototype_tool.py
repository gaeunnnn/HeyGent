from __future__ import annotations

import json
from typing import Any

from app.tools.runtime.catalog import register_runtime_tool_definition


_PROTOTYPE_CREATE_ARTIFACT_DEFINITION = register_runtime_tool_definition(
    name="prototype.create_artifact",
    toolset="prototype",
    module="app.tools.prototype.prototype_tool",
    summary="Create a session-scoped React prototype artifact version.",
    schema={
        "description": (
            "Create or update the active session prototype artifact with React component files. "
            "Use this for DESIGN.md driven prototype work instead of local file tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Prototype title shown in the preview panel.",
                },
                "framework": {
                    "type": "string",
                    "enum": ["react", "html"],
                    "description": "Generated prototype framework. Prefer react.",
                },
                "styling": {
                    "type": "string",
                    "enum": ["css", "tailwind", "mixed"],
                    "description": "Styling strategy used by the generated files.",
                },
                "designPresetId": {
                    "type": "string",
                    "description": (
                        "Required DESIGN.md preset id used as visual context. Pass the exact preset_id "
                        "returned by design.read_preset."
                    ),
                },
                "entryFile": {
                    "type": "string",
                    "description": "Main file for preview. React artifacts usually use /src/App.tsx.",
                },
                "summary": {
                    "type": "string",
                    "description": "Short Korean summary of what this version contains.",
                },
                "files": {
                    "type": "object",
                    "description": (
                        "Map of absolute project file paths to source code or { code } objects. "
                        "Use React/CSS files that render in Sandpack. Built-in dependencies include "
                        "lucide-react, motion/framer-motion, recharts, Radix UI primitives, "
                        "react-resizable-panels, react-router, axios, d3, three/@react-three, "
                        "gsap, lottie-react, animejs, react-icons, react-is, mapbox-gl, bootstrap, clsx, "
                        "date-fns, sonner, vaul, and zustand."
                    ),
                    "additionalProperties": {
                        "anyOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {"code": {"type": "string"}},
                                "required": ["code"],
                            },
                        ]
                    },
                },
                "metadata": {
                    "type": "object",
                    "description": "Optional non-sensitive metadata for this prototype version.",
                },
            },
            "required": ["title", "files"],
        },
    },
)

_PROTOTYPE_GET_ACTIVE_ARTIFACT_DEFINITION = register_runtime_tool_definition(
    name="prototype.get_active_artifact",
    toolset="prototype",
    module="app.tools.prototype.prototype_tool",
    summary="Read the active session React prototype artifact files.",
    schema={
        "description": (
            "Read the active session prototype artifact and its source files. "
            "Use this before modifying an existing DESIGN.md prototype."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
)


def prototype_create_artifact_tool_definition() -> dict[str, str]:
    return {
        "name": _PROTOTYPE_CREATE_ARTIFACT_DEFINITION.name,
        "toolset": _PROTOTYPE_CREATE_ARTIFACT_DEFINITION.toolset,
        "module": _PROTOTYPE_CREATE_ARTIFACT_DEFINITION.module,
        "summary": _PROTOTYPE_CREATE_ARTIFACT_DEFINITION.summary,
    }


def prototype_get_active_artifact_tool_definition() -> dict[str, str]:
    return {
        "name": _PROTOTYPE_GET_ACTIVE_ARTIFACT_DEFINITION.name,
        "toolset": _PROTOTYPE_GET_ACTIVE_ARTIFACT_DEFINITION.toolset,
        "module": _PROTOTYPE_GET_ACTIVE_ARTIFACT_DEFINITION.module,
        "summary": _PROTOTYPE_GET_ACTIVE_ARTIFACT_DEFINITION.summary,
    }


def normalize_prototype_files(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict):
        return {}

    files: dict[str, dict[str, str]] = {}
    for raw_path, raw_file in value.items():
        path = _normalize_file_path(raw_path)
        if not path:
            continue
        code = _extract_code(raw_file)
        if code is None:
            continue
        files[path] = {"code": code}
    return files


def prototype_tool_error(code: str, message: str, *, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "tool_name": "prototype.create_artifact",
        }
    }
    if details:
        payload["error"]["details"] = details
    return {
        "ok": False,
        **payload,
        "content": json.dumps(payload, ensure_ascii=False),
    }


def _normalize_file_path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    if not text:
        return ""
    if not text.startswith("/"):
        text = f"/{text}"
    parts = [part for part in text.split("/") if part not in {"", "."}]
    if any(part == ".." for part in parts):
        return ""
    return "/" + "/".join(parts)


def _extract_code(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("code"), str):
        return str(value["code"])
    return None
