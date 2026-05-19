from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.http.credential_cache_internal import router
from app.core.config import Settings


class DummyProviderRegistry:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invalidate_backend_credential_cache(self, **kwargs) -> int:
        self.calls.append(kwargs)
        return 2


def test_credential_cache_invalidate_requires_internal_token():
    app = FastAPI()
    app.state.settings = Settings(internal_service_token="service-token")
    app.state.provider_registry = DummyProviderRegistry()
    app.include_router(router, prefix="/ai/api/v1")

    response = TestClient(app).post(
        "/ai/api/v1/internal/ai/credential-cache/invalidate",
        json={"userId": 1, "providerName": "openai_api_key"},
    )

    assert response.status_code == 401


def test_credential_cache_invalidate_delegates_to_provider_registry():
    registry = DummyProviderRegistry()
    app = FastAPI()
    app.state.settings = Settings(internal_service_token="service-token")
    app.state.provider_registry = registry
    app.include_router(router, prefix="/ai/api/v1")

    response = TestClient(app).post(
        "/ai/api/v1/internal/ai/credential-cache/invalidate",
        headers={"Authorization": "Bearer service-token"},
        json={"userId": 1, "providerName": "openai_api_key", "model": "gpt-5.4"},
    )

    assert response.status_code == 200
    assert response.json() == {"invalidated": 2}
    assert registry.calls == [
        {"user_id": 1, "provider_name": "openai_api_key", "model": "gpt-5.4"},
    ]
