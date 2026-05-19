from __future__ import annotations

import json
from typing import Any

from app.clients.backend_gmail import BackendGmailClient, BackendGmailClientError
from app.tools.runtime.catalog import register_runtime_tool_definition


GMAIL_PATH_PREFIX = "/gmail/v1/"
SUPPORTED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


GMAIL_EXECUTE_SCHEMA = {
    "name": "gmail.execute",
    "description": (
        "Execute one or more commands against the user's connected Gmail account through the backend Gmail proxy. "
        "Use after reading the gmail skill instructions and reference files. Do not include userId; the runtime binds it. "
        "Endpoints must start with /gmail/v1/."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "commands": {
                "type": "array",
                "description": "Ordered Gmail proxy commands to execute.",
                "items": {
                    "type": "object",
                    "properties": {
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                            "description": "HTTP method for the Gmail /gmail/v1/ endpoint.",
                        },
                        "endpoint": {
                            "type": "string",
                            "description": (
                                "Gmail endpoint path starting with /gmail/v1/. Query strings may be included "
                                "(e.g. /gmail/v1/users/me/messages?q=category:updates)."
                            ),
                        },
                        "params": {
                            "type": "object",
                            "description": (
                                "Request body for POST/PUT/PATCH commands. Ignored for GET/DELETE."
                            ),
                        },
                    },
                    "required": ["method", "endpoint"],
                },
            },
        },
        "required": ["commands"],
    },
}


_GMAIL_EXECUTE_DEFINITION = register_runtime_tool_definition(
    name="gmail.execute",
    toolset="gmail",
    module="app.tools.gmail.gmail_tool",
    summary="Execute Gmail proxy commands for the authenticated owner (read updates label, fetch messages, send mail, etc.).",
    schema=GMAIL_EXECUTE_SCHEMA,
)


def gmail_execute_tool_definition() -> dict[str, str]:
    return {
        "name": _GMAIL_EXECUTE_DEFINITION.name,
        "toolset": _GMAIL_EXECUTE_DEFINITION.toolset,
        "module": _GMAIL_EXECUTE_DEFINITION.module,
        "summary": _GMAIL_EXECUTE_DEFINITION.summary,
    }


def execute_gmail_handler(args: dict[str, Any]) -> dict[str, Any]:
    user_id = _coerce_user_id(args.get("_trusted_user_id"))
    if user_id is None:
        return _tool_error("missing_user", "Gmail 실행에 필요한 사용자 식별자가 없습니다.")

    commands = _normalize_commands(args.get("commands"))
    if not commands:
        return _tool_error("missing_commands", "실행할 Gmail 명령이 없습니다.")

    try:
        results = BackendGmailClient().execute(user_id=user_id, commands=commands)
    except BackendGmailClientError as error:
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
        if method not in SUPPORTED_METHODS or not endpoint.startswith(GMAIL_PATH_PREFIX):
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
            "tool_name": "gmail.execute",
        }
    }
    return {
        "ok": False,
        **payload,
        "content": json.dumps(payload, ensure_ascii=False),
    }
