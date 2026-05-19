from __future__ import annotations

import httpx
import pytest

from app.domain.orchestration.agent.memory.provider_retry import (
    memory_provider_error_details,
    respond_provider_with_retry,
)
from app.domain.providers.model.base import AgentMessage, AgentModelResponse


class FlakyProvider:
    def __init__(self, *, fail_count: int) -> None:
        self.fail_count = fail_count
        self.calls = 0

    async def respond_async(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_count:
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            response = httpx.Response(429, request=request, text="rate limited")
            raise httpx.HTTPStatusError("rate limited", request=request, response=response)
        return AgentModelResponse(
            provider_name="test",
            model=kwargs["model"],
            message=AgentMessage(role="assistant", content='{"ok":true}'),
            output_text='{"ok":true}',
        )


@pytest.mark.asyncio
async def test_respond_provider_with_retry_retries_retryable_http_status(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr("app.domain.orchestration.agent.memory.provider_retry.asyncio.sleep", fake_sleep)
    provider = FlakyProvider(fail_count=1)

    response = await respond_provider_with_retry(
        provider,
        retry_delays=(0.01, 0.02),
        messages=[],
        tools=None,
        model="gpt-test",
        tool_choice=None,
    )

    assert provider.calls == 2
    assert sleeps == [0.01]
    assert response.output_text == '{"ok":true}'


@pytest.mark.asyncio
async def test_respond_provider_with_retry_attaches_debug_metadata_on_final_failure(monkeypatch):
    async def fake_sleep(delay: float) -> None:
        return None

    monkeypatch.setattr("app.domain.orchestration.agent.memory.provider_retry.asyncio.sleep", fake_sleep)
    provider = FlakyProvider(fail_count=3)

    with pytest.raises(httpx.HTTPStatusError) as error:
        await respond_provider_with_retry(
            provider,
            retry_delays=(0.01, 0.02),
            messages=[],
            tools=None,
            model="gpt-memory-debug",
            tool_choice=None,
        )

    details = memory_provider_error_details(error.value)
    assert provider.calls == 3
    assert details["selected_model"] == "gpt-memory-debug"
    assert details["provider_name"] == "FlakyProvider"
    assert details["retry_attempts"] == 3
    assert details["max_attempts"] == 3
    assert details["provider_error_message"] == "rate limited"


def test_memory_provider_error_details_extracts_http_status():
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429, request=request, text="rate limited")
    exc = httpx.HTTPStatusError("rate limited", request=request, response=response)

    assert memory_provider_error_details(exc) == {
        "error_type": "HTTPStatusError",
        "provider_status_code": 429,
        "retryable": True,
        "provider_error_message": "rate limited",
    }
