from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import Settings, get_settings


class BackendNotionClientError(RuntimeError):
    """backend Notion internal API 호출이나 응답 해석 실패를 나타낸다."""


class BackendNotionClient:
    """AI runtime에서 backend Notion internal API를 호출하는 동기 client다."""

    def __init__(self, *, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    def execute(self, *, user_id: int, commands: list[dict[str, Any]]) -> list[dict[str, Any]]:
        internal_token = str(self._settings.internal_service_token or "").strip()
        if not internal_token:
            raise BackendNotionClientError("AI 내부 인증 토큰이 설정되지 않았습니다.")

        request = Request(
            self._url("/internal/ai/notion/execute"),
            data=json.dumps({"userId": user_id, "commands": commands}, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {internal_token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._settings.backend_tool_timeout_seconds) as response:
                body = response.read(500_000).decode("utf-8", errors="replace")
        except HTTPError as error:
            raise BackendNotionClientError(_backend_error_message(error)) from error
        except URLError as error:
            raise BackendNotionClientError(f"backend 연결 실패: {error.reason}") from error
        except TimeoutError as error:
            raise BackendNotionClientError("backend Notion 실행 요청이 시간 초과되었습니다.") from error

        try:
            wrapper = json.loads(body)
        except json.JSONDecodeError as error:
            raise BackendNotionClientError("backend 응답이 JSON 형식이 아닙니다.") from error

        if not isinstance(wrapper, dict) or "data" not in wrapper:
            raise BackendNotionClientError("backend 응답 wrapper에 data가 없습니다.")
        data = wrapper["data"]
        if not isinstance(data, list):
            raise BackendNotionClientError("backend 응답 data가 목록이 아닙니다.")
        return [item for item in data if isinstance(item, dict)]

    def _url(self, path: str) -> str:
        return f"{self._settings.backend_base_url.rstrip('/')}{path}"


def _backend_error_message(error: HTTPError) -> str:
    try:
        body = error.read(50_000).decode("utf-8", errors="replace")
        payload = json.loads(body)
        if isinstance(payload, dict):
            message = payload.get("message") or payload.get("error")
            if message:
                return str(message)
    except Exception:
        pass
    return f"backend Notion 요청 실패: HTTP {error.code}"
