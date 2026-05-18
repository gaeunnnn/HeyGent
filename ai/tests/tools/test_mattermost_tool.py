import json

from app.tools.messaging import mattermost_tool


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit):
        return json.dumps({"data": {"sent": True, "target": "우리만", "displayName": "우리만"}}, ensure_ascii=False).encode(
            "utf-8"
        )


def test_mattermost_tool_uses_backend_tool_timeout(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["timeout"] = timeout
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setenv("HEYGENT_INTERNAL_SERVICE_TOKEN", "internal-token")
    monkeypatch.setenv("HEYGENT_BACKEND_TOOL_TIMEOUT_SECONDS", "9.5")
    monkeypatch.setattr(mattermost_tool, "urlopen", fake_urlopen)

    result = mattermost_tool.send_mattermost_message_handler(
        {"_trusted_user_id": 1, "target": "우리만", "message": "테스트 메시지"}
    )

    assert result["ok"] is True
    assert captured["timeout"] == 9.5
    assert captured["body"]["target"] == "우리만"
