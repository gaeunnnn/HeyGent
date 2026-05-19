from __future__ import annotations

import httpx
import pytest

from app.clients.backend_memory import BackendMemoryClient, BackendMemoryClientError
from app.core.config import Settings


def memory_payload(memory_id: int = 10) -> dict:
    return {
        "id": memory_id,
        "storeType": "AGENT_MEMORY",
        "memoryType": "FACT",
        "scopeType": "GLOBAL",
        "content": "사용자는 회의록을 짧게 요약하는 것을 선호한다.",
        "summary": "짧은 회의록 요약 선호",
        "metadata": {"workspaceKey": "workspace-a"},
        "importance": 0.8,
        "confidence": 0.9,
    }


@pytest.mark.asyncio
async def test_recall_sends_internal_header_and_user_id_params():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.headers["Authorization"] == "Bearer service-token"
        assert str(request.url) == (
            "http://backend/internal/ai/memories/recall"
            "?userId=1&limit=5&query=%ED%9A%8C%EC%9D%98%EB%A1%9D+%EC%9A%94%EC%95%BD"
            "&workspaceKey=workspace-a&scopeType=WORKSPACE&tags=project&metadataCategories=task_state"
            "&metadataCategories=procedure"
        )
        return httpx.Response(200, json={"status": 200, "data": [memory_payload()]})

    settings = Settings(
        backend_base_url="http://backend",
        internal_service_token="service-token",
        backend_memory_timeout_seconds=2.5,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BackendMemoryClient(settings=settings, http_client=http_client)

        memories = await client.recall(
            user_id="1",
            query="회의록 요약",
            workspace_key="workspace-a",
            scope_type="WORKSPACE",
            tags=["project"],
            metadata_categories=["task_state", "procedure"],
        )

    assert len(memories) == 1
    assert memories[0].id == 10
    assert memories[0].memory_type == "FACT"
    assert memories[0].content == "사용자는 회의록을 짧게 요약하는 것을 선호한다."


@pytest.mark.asyncio
async def test_create_candidates_posts_user_id_and_candidates():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://backend/internal/ai/memories/candidates"
        assert request.headers["Authorization"] == "Bearer service-token"
        assert request.read() == (
            b'{"userId":1,"candidates":[{"memoryType":"PREFERENCE","scopeType":"GLOBAL",'
            b'"content":"short answers","importance":0.8,"confidence":0.9}]}'
        )
        return httpx.Response(200, json={"status": 200, "data": [memory_payload(11)]})

    settings = Settings(backend_base_url="http://backend", internal_service_token="service-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BackendMemoryClient(settings=settings, http_client=http_client)

        memories = await client.create_candidates(
            user_id="1",
            candidates=[
                {
                    "memoryType": "PREFERENCE",
                    "scopeType": "GLOBAL",
                    "content": "short answers",
                    "importance": 0.8,
                    "confidence": 0.9,
                }
            ],
        )

    assert memories[0].id == 11


@pytest.mark.asyncio
async def test_mark_used_posts_user_id_and_score():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://backend/internal/ai/memories/10/used"
        assert request.headers["Authorization"] == "Bearer service-token"
        assert request.read() == b'{"userId":1,"usefulnessScore":0.75}'
        return httpx.Response(200, json={"status": 200, "data": memory_payload(10)})

    settings = Settings(backend_base_url="http://backend", internal_service_token="service-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BackendMemoryClient(settings=settings, http_client=http_client)

        memory = await client.mark_used(user_id="1", memory_id=10, usefulness_score=0.75)

    assert memory.id == 10


@pytest.mark.asyncio
async def test_mark_used_posts_source_task_run_id_for_idempotency():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "http://backend/internal/ai/memories/10/used"
        assert request.read() == b'{"userId":1,"usefulnessScore":0.75,"sourceTaskRunId":"task_1"}'
        return httpx.Response(200, json={"status": 200, "data": memory_payload(10)})

    settings = Settings(backend_base_url="http://backend", internal_service_token="service-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BackendMemoryClient(settings=settings, http_client=http_client)

        memory = await client.mark_used(
            user_id="1",
            memory_id=10,
            usefulness_score=0.75,
            source_task_run_id="task_1",
        )

    assert memory.id == 10


@pytest.mark.asyncio
async def test_recall_raises_on_backend_error_status():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401,
            json={
                "status": 401,
                "code": "INVALID_INTERNAL_TOKEN",
                "message": "invalid token",
            },
        )

    settings = Settings(backend_base_url="http://backend", internal_service_token="bad-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BackendMemoryClient(settings=settings, http_client=http_client)

        with pytest.raises(BackendMemoryClientError, match="401") as exc_info:
            await client.recall(user_id="1", query="회의록")

    assert exc_info.value.status_code == 401
    assert exc_info.value.error_code == "INVALID_INTERNAL_TOKEN"
    assert exc_info.value.response_message == "invalid token"


@pytest.mark.asyncio
async def test_recall_wraps_network_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("backend unavailable", request=request)

    settings = Settings(backend_base_url="http://backend", internal_service_token="service-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = BackendMemoryClient(settings=settings, http_client=http_client)

        with pytest.raises(BackendMemoryClientError, match="네트워크 오류"):
            await client.recall(user_id="1", query="회의록")


@pytest.mark.asyncio
async def test_recall_raises_on_invalid_user_id():
    settings = Settings(backend_base_url="http://backend", internal_service_token="service-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as http_client:
        client = BackendMemoryClient(settings=settings, http_client=http_client)

        with pytest.raises(BackendMemoryClientError, match="user_id"):
            await client.recall(user_id="not-a-number", query="회의록")
