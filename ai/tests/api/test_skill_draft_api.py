from __future__ import annotations

import json

from app.domain.providers.model.base import AgentMessage, AgentModelResponse


class _FakeProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[dict] = []

    async def respond_async(self, **kwargs):
        self.calls.append(kwargs)
        return AgentModelResponse(
            provider_name="openai_api",
            model=kwargs.get("model") or "gpt-test",
            message=AgentMessage(role="assistant", content=self.text),
            output_text=self.text,
            finish_reason="stop",
            visible_text=self.text,
        )


class _FakeProviderRegistry:
    def __init__(self, provider: _FakeProvider) -> None:
        self.provider = provider

    def preferred_model_provider(self):
        return self.provider


def _auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer 7"}


def test_generate_skill_draft_returns_create_skill_compatible_payload(client):
    payload = {
        "name": "meeting-notes",
        "displayName": "회의록 정리",
        "description": "회의 내용을 정리합니다.",
        "body": "---\nname: meeting-notes\ndescription: 회의 내용을 정리합니다.\n---\n\n## 작업 순서\n\n1. 회의 내용을 읽는다.",
        "documents": [
            {
                "documentKey": "references/style.md",
                "title": "정리 기준",
                "content": "# Style",
            }
        ],
    }
    provider = _FakeProvider(json.dumps(payload, ensure_ascii=False))
    client.app.state.provider_registry = _FakeProviderRegistry(provider)

    response = client.post(
        "/ai/api/v1/skills/draft",
        headers=_auth_headers(),
        json={"goal": "회의록 정리 스킬을 만들고 싶어"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "meeting-notes"
    assert data["displayName"] == "회의록 정리"
    assert data["documents"][0]["documentKey"] == "references/style.md"
    assert provider.calls[0]["tools"] == []
    assert provider.calls[0]["runtime_context"] == {
        "user_id": "7",
        "provider_name": "openai_api_key",
    }

    create_response = client.post("/ai/api/v1/skills", headers=_auth_headers(), json=data)
    assert create_response.status_code == 200
    assert create_response.json()["skillId"] == "custom:7:meeting-notes"


def test_generate_skill_draft_rejects_empty_goal(client):
    response = client.post(
        "/ai/api/v1/skills/draft",
        headers=_auth_headers(),
        json={"goal": "   "},
    )

    assert response.status_code == 400


def test_import_skill_url_uses_skill_markdown_without_provider(client, monkeypatch):
    import app.api.http.agents as agent_routes

    async def fake_fetch(_url: str) -> tuple[str, str]:
        return (
            "https://example.com/SKILL.md",
            "---\nname: imported-skill\ndescription: 가져온 스킬\n---\n\n## 작업 순서\n\n1. 읽는다.",
        )

    provider = _FakeProvider("{}")
    client.app.state.provider_registry = _FakeProviderRegistry(provider)
    monkeypatch.setattr(agent_routes, "_fetch_skill_import_url", fake_fetch)

    response = client.post(
        "/ai/api/v1/skills/import-url",
        headers=_auth_headers(),
        json={"url": "https://example.com/SKILL.md"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "imported-skill"
    assert data["sourceUrl"] == "https://example.com/SKILL.md"
    assert provider.calls == []


def test_import_skill_url_rejects_localhost(client):
    response = client.post(
        "/ai/api/v1/skills/import-url",
        headers=_auth_headers(),
        json={"url": "http://localhost/SKILL.md"},
    )

    assert response.status_code == 400


def test_delete_custom_skill_removes_user_created_skill(client):
    provider = _FakeProvider(
        json.dumps(
            {
                "name": "frontend-review",
                "displayName": "프론트엔드 리뷰",
                "description": "프론트엔드 PR을 점검합니다.",
                "body": "---\nname: frontend-review\ndescription: 프론트엔드 PR을 점검합니다.\n---\n\n# Review",
                "documents": [],
            },
            ensure_ascii=False,
        )
    )
    client.app.state.provider_registry = _FakeProviderRegistry(provider)
    create_response = client.post(
        "/ai/api/v1/skills/draft",
        headers=_auth_headers(),
        json={"goal": "프론트엔드 PR 리뷰 스킬"},
    )
    created = client.post("/ai/api/v1/skills", headers=_auth_headers(), json=create_response.json())

    skill_id = created.json()["skillId"]
    delete_response = client.delete(f"/ai/api/v1/skills/{skill_id}", headers=_auth_headers())
    detail_response = client.get(f"/ai/api/v1/skills/{skill_id}", headers=_auth_headers())

    assert delete_response.status_code == 204
    assert detail_response.status_code == 404
    assert skill_id not in {item["skillId"] for item in client.get("/ai/api/v1/skills", headers=_auth_headers()).json()["items"]}


def test_delete_builtin_skill_is_not_allowed(client):
    skill_id = client.get("/ai/api/v1/skills", headers=_auth_headers()).json()["items"][0]["skillId"]

    response = client.delete(f"/ai/api/v1/skills/{skill_id}", headers=_auth_headers())

    assert response.status_code == 404
