from __future__ import annotations

import json
from typing import Any

from app.clients.backend_health import BackendHealthClient, BackendHealthClientError
from app.tools.runtime.catalog import register_runtime_tool_definition


HEALTH_PATH_PREFIX = "/api/v1/health/"
SUPPORTED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


HEALTH_EXECUTE_SCHEMA = {
    "name": "health.execute",
    "description": (
        "Execute one or more commands against the authenticated user's health data through the backend Health proxy. "
        "Use after reading the health-condition-check skill instructions and reference files. Do not include userId; "
        "the runtime binds it. Endpoints must start with /api/v1/health/."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "description": "Ordered Health proxy commands to execute.",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                            "description": "HTTP method for the /api/v1/health/ endpoint.",
                        },
                        "endpoint": {
                            "type": "string",
                            "description": (
                                "Health endpoint path starting with /api/v1/health/. Query strings may be included "
                                "(e.g. /api/v1/health/me/latest)."
                            ),
                        },
                        "params": {
                            "type": "object",
                            "description": "Request body for POST/PUT/PATCH commands. Ignored for GET/DELETE.",
                        },
                    },
                    "required": ["method", "endpoint"],
                },
            },
        },
        "required": ["commands"],
    },
}


_HEALTH_EXECUTE_DEFINITION = register_runtime_tool_definition(
    name="health.execute",
    toolset="health",
    module="app.tools.health.health_tool",
    summary="Execute Health proxy commands for the authenticated owner.",
    schema=HEALTH_EXECUTE_SCHEMA,
)


def health_execute_tool_definition() -> dict[str, str]:
    return {
        "name": _HEALTH_EXECUTE_DEFINITION.name,
        "toolset": _HEALTH_EXECUTE_DEFINITION.toolset,
        "module": _HEALTH_EXECUTE_DEFINITION.module,
        "summary": _HEALTH_EXECUTE_DEFINITION.summary,
    }


def execute_health_handler(args: dict[str, Any]) -> dict[str, Any]:
    user_id = _coerce_user_id(args.get("_trusted_user_id"))
    if user_id is None:
        return _tool_error("missing_user", "Health 실행에 필요한 사용자 식별자가 없습니다.")

    commands = _normalize_commands(args.get("commands"))
    if not commands:
        return _tool_error("missing_commands", "실행할 Health 명령이 없습니다.")

    try:
        results = BackendHealthClient().execute(user_id=user_id, commands=commands)
    except BackendHealthClientError as error:
        return _tool_error("backend_request_failed", str(error))

    success_count = sum(1 for item in results if item.get("success") is True)
    failed_count = sum(1 for item in results if item.get("success") is False)
    return {
        "ok": failed_count == 0,
        "results": results,
        "success_count": success_count,
        "failed_count": failed_count,
        "content": json.dumps(
            {
                "results": results,
                "success_count": success_count,
                "failed_count": failed_count,
            },
            ensure_ascii=False,
        ),
    }


def _normalize_commands(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []

    commands: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        method = str(item.get("method") or "").strip().upper()
        endpoint = str(item.get("endpoint") or "").strip()
        if method not in SUPPORTED_METHODS or not endpoint.startswith(HEALTH_PATH_PREFIX):
            continue

        command: dict[str, Any] = {
            "method": method,
            "endpoint": endpoint,
        }
        params = item.get("params")
        if isinstance(params, dict):
            command["params"] = params
        commands.append(command)
    return commands


def _coerce_user_id(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _tool_error(code: str, message: str) -> dict[str, Any]:
    payload = {
        "error": {
            "code": code,
            "message": message,
            "tool_name": "health.execute",
        }
    }
    return {
        "ok": False,
        **payload,
        "content": json.dumps(payload, ensure_ascii=False),
    }
