from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.tools.runtime.catalog import register_runtime_tool_definition


logger = logging.getLogger("app.tools.web")


HTTP_GET_SCHEMA = {
    "name": "http_get",
    "description": (
        "Fetch an HTTP(S) URL with optional query parameters and return JSON or text. "
        "Use this for project skills that specify a public API/proxy endpoint, such as k-skill proxy routes."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "HTTP or HTTPS URL to fetch."},
            "params": {
                "type": "object",
                "description": "Optional query string parameters.",
                "additionalProperties": {"type": ["string", "number", "boolean"]},
            },
        },
        "required": ["url"],
    },
}


register_runtime_tool_definition(
    name="http_get",
    toolset="web",
    module="app.tools.web.web_tools",
    summary="Fetch JSON or text from an HTTP(S) URL.",
    schema=HTTP_GET_SCHEMA,
)


def http_get_handler(args: dict[str, Any]) -> dict[str, Any]:
    url = str(args.get("url") or "").strip()
    if not url.startswith(("https://", "http://")):
        return {"ok": False, "error": {"code": "invalid_url", "message": "url must start with http:// or https://"}}

    params = args.get("params")
    if isinstance(params, dict) and params:
        query = urlencode({str(key): str(value) for key, value in params.items() if value is not None})
        separator = "&" if "?" in url else "?"
        url = f"{url}{separator}{query}"

    # http_get 은 urllib 을 쓰므로 httpx 처럼 자동 로그가 안 남는다. 도구가 실제 외부 호출을
    # 했는지 디버깅하려고 호출 URL 을 명시적으로 남긴다.
    logger.info("http_get → %s", url)
    request = Request(url, headers={"User-Agent": "heygent-ai/1.0"})
    with urlopen(request, timeout=15) as response:
        raw = response.read(200_000)
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        content_type = response.headers.get("content-type", "")
        status = int(response.status)
    logger.info("http_get ← %s status=%s", url, status)

    result: dict[str, Any] = {
        "ok": True,
        "url": url,
        "status": status,
        "content_type": content_type,
    }
    if "json" in content_type.lower():
        try:
            result["json"] = json.loads(text)
        except json.JSONDecodeError:
            result["text"] = text[:20_000]
    else:
        result["text"] = text[:20_000]
    return result


def _decode_tool_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return {"ok": True, "content": raw}
        if isinstance(payload, dict):
            return payload
        return {"ok": True, "data": payload}
    return {"ok": True, "result": raw}


