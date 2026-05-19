from __future__ import annotations

import httpx
import json
import pytest

from app.clients.backend_ai import BackendAiClient
from app.core.config import Settings


@pytest.mark.asyncio
async def test_issue_credential_sends_internal_token_and_caches_by_user_provider_model():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.headers["Authorization"] == "Bearer service-token"
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "ok",
                "data": {
                    "providerName": "openai_api_key",
                    "authType": "api_key",
                    "model": "gpt-5.4",
                    "credentialType": "api_key",
                    "credential": "sk-user",
                    "expiresAt": None,
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = BackendAiClient(
        settings=Settings(
            backend_base_url="http://backend",
            internal_service_token="service-token",
        ),
        http_client=http_client,
    )

    first = await client.issue_credential(user_id="10", provider_name="openai_api_key", model="gpt-5.4")
    second = await client.issue_credential(user_id="10", provider_name="openai_api_key", model="gpt-5.4")

    assert first.credential == "sk-user"
    assert second.credential == "sk-user"
    assert len(calls) == 1
    assert calls[0].url == "http://backend/internal/ai/credentials/issue"
    assert calls[0].read() == b'{"userId":10,"providerName":"openai_api_key","model":"gpt-5.4"}'


@pytest.mark.asyncio
async def test_invalidate_credential_cache_removes_matching_user_provider_entries():
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        provider_name = json.loads(request.read().decode())["providerName"]
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "ok",
                "data": {
                    "providerName": provider_name,
                    "authType": "api_key",
                    "model": "gpt-5.4",
                    "credentialType": "api_key",
                    "credential": f"credential-{len(calls)}",
                    "expiresAt": None,
                },
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = BackendAiClient(
        settings=Settings(
            backend_base_url="http://backend",
            internal_service_token="service-token",
        ),
        http_client=http_client,
    )

    first = await client.issue_credential(user_id="10", provider_name="openai_api_key", model="gpt-5.4")
    removed = client.invalidate_credential_cache(user_id=10, provider_name="openai_api_key")
    second = await client.issue_credential(user_id="10", provider_name="openai_api_key", model="gpt-5.4")

    assert removed == 1
    assert first.credential == "credential-1"
    assert second.credential == "credential-2"
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_record_command_usage_maps_openai_usage_and_session_context():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = request.read().decode()
        return httpx.Response(
            200,
            json={
                "status": 200,
                "message": "ok",
                "data": {"id": 1},
            },
        )

    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = BackendAiClient(
        settings=Settings(
            backend_base_url="http://backend",
            internal_service_token="service-token",
        ),
        http_client=http_client,
    )

    await client.record_command_usage(
        user_id="10",
        provider_name="openai_api_key",
        model="gpt-5.4",
        task_run_id="task-1",
        step_run_id="step-1",
        session_id="session-1",
        request_id="resp-1",
        usage={
            "input_tokens": 12,
            "output_tokens": 4,
            "total_tokens": 16,
            "input_tokens_details": {"cached_tokens": 3},
            "output_tokens_details": {"reasoning_tokens": 2},
        },
        metadata={"command": "agent_loop"},
    )

    assert captured["url"] == "http://backend/internal/ai/usages/commands"
    assert captured["headers"]["authorization"] == "Bearer service-token"
    assert json.loads(captured["json"]) == {
        "userId": 10,
        "providerName": "openai_api_key",
        "model": "gpt-5.4",
        "taskRunId": "task-1",
        "stepRunId": "step-1",
        "sessionId": "session-1",
        "requestId": "resp-1",
        "inputTokens": 12,
        "outputTokens": 4,
        "totalTokens": 16,
        "cachedInputTokens": 3,
        "reasoningTokens": 2,
        "estimatedCostUsd": 0.00008325,
        "metadata": {"command": "agent_loop"},
    }
