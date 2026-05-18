import json

import pytest

from app.clients import backend_notion
from app.clients.backend_notion import BackendNotionClient, BackendNotionClientError
from app.core.config import Settings


class FakeResponse:
    def __init__(self, body: dict):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit):
        return json.dumps(self.body, ensure_ascii=False).encode("utf-8")


def test_backend_notion_client_posts_internal_execute_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse({"data": [{"success": True, "endpoint": "/v1/search"}]})

    monkeypatch.setattr(backend_notion, "urlopen", fake_urlopen)
    client = BackendNotionClient(
        settings=Settings(
            backend_base_url="http://backend.local",
            internal_service_token="internal-token",
            backend_memory_timeout_seconds=3.0,
            backend_tool_timeout_seconds=9.0,
        )
    )

    result = client.execute(
        user_id=7,
        commands=[{"method": "POST", "endpoint": "/v1/search", "notionVersion": "2026-03-11"}],
    )

    assert result == [{"success": True, "endpoint": "/v1/search"}]
    assert captured["url"] == "http://backend.local/internal/ai/notion/execute"
    assert captured["timeout"] == 9.0
    assert captured["headers"]["Authorization"] == "Bearer internal-token"
    assert captured["body"]["userId"] == 7
    assert captured["body"]["commands"][0]["endpoint"] == "/v1/search"


def test_backend_notion_client_requires_internal_token():
    client = BackendNotionClient(settings=Settings(internal_service_token=""))

    with pytest.raises(BackendNotionClientError, match="내부 인증 토큰"):
        client.execute(user_id=7, commands=[{"method": "GET", "endpoint": "/v1/users/me"}])
