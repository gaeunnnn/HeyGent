from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import get_settings
from app.tools.runtime.catalog import register_runtime_tool_definition


MATTERMOST_SEND_SCHEMA = {
    "name": "mattermost.send",
    "description": (
        "Send a user-approved message to a configured Mattermost channel alias. "
        "Use only when the user explicitly asks to send/share/post to Mattermost or a channel."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Optional Mattermost channel alias such as backend, frontend, free, 자유채널, or e105.",
            },
            "message": {
                "type": "string",
                "description": "Final message text to send to Mattermost.",
            },
        },
        "required": ["message"],
    },
}


register_runtime_tool_definition(
    name="mattermost.send",
    toolset="messaging",
    module="app.tools.messaging.mattermost_tool",
    summary="Send a message to a configured Mattermost channel alias.",
    schema=MATTERMOST_SEND_SCHEMA,
)


def send_mattermost_message_handler(args: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    user_id = _coerce_user_id(args.get("_trusted_user_id") or args.get("user_id"))
    if user_id is None:
        return _tool_error("missing_user", "Mattermost 전송에 필요한 사용자 식별자가 없습니다.")

    message = str(args.get("message") or "").strip()
    if not message:
        return _tool_error("missing_message", "전송할 메시지가 없습니다.")

    internal_token = str(settings.internal_service_token or "").strip()
    if not internal_token:
        return _tool_error("missing_internal_token", "AI 내부 인증 토큰이 설정되지 않았습니다.")

    payload: dict[str, Any] = {
        "userId": user_id,
        "message": message,
    }
    target = str(args.get("target") or "").strip()
    if target:
        payload["target"] = target

    request = Request(
        f"{settings.backend_base_url.rstrip('/')}/internal/ai/mattermost/messages",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {internal_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=settings.backend_tool_timeout_seconds) as response:
            body = response.read(100_000).decode("utf-8", errors="replace")
    except HTTPError as error:
        return _tool_error("backend_request_failed", _backend_error_message(error))
    except URLError as error:
        return _tool_error("backend_unreachable", f"backend 연결 실패: {error.reason}")
    except TimeoutError:
        return _tool_error("backend_timeout", "backend Mattermost 전송 요청이 시간 초과되었습니다.")

    try:
        wrapper = json.loads(body)
    except json.JSONDecodeError:
        return _tool_error("invalid_backend_response", "backend 응답이 JSON 형식이 아닙니다.")
    data = wrapper.get("data") if isinstance(wrapper, dict) else None
    if not isinstance(data, dict):
        return _tool_error("invalid_backend_response", "backend 응답 data가 객체가 아닙니다.")

    return {
        "ok": True,
        "sent": bool(data.get("sent")),
        "target": data.get("target"),
        "displayName": data.get("displayName"),
    }


def _coerce_user_id(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _backend_error_message(error: HTTPError) -> str:
    try:
        body = error.read(20_000).decode("utf-8", errors="replace")
        payload = json.loads(body)
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("error")
            if message:
                return str(message)
    except Exception:
        pass
    return f"backend Mattermost 요청 실패: HTTP {error.code}"


def _tool_error(code: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": code,
            "message": message,
        },
    }
