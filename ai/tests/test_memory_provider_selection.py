from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.api.memory_context import MemoryRecallPlan
from app.contracts.provider.provider_response import ProviderHealthResponse
from app.domain.orchestration.agent.memory.memory_extraction_provider import ProviderMemoryExtractionClient
from app.domain.orchestration.agent.memory.memory_extractor import MemoryExtractionContext
from app.domain.orchestration.agent.memory.memory_recall_planner_provider import ProviderMemoryRecallPlannerClient
from app.domain.orchestration.agent.memory.memory_usage_attribution_provider import ProviderMemoryUsageAttributionClient
from app.domain.providers.model.base import AgentMessage, AgentModelResponse
from app.domain.providers.registry import ProviderRegistry


class FakeProvider:
    auth_type = "api_key"

    def __init__(self, name: str, output: dict) -> None:
        self.name = name
        self.output = output
        self.calls: list[dict] = []
        self.settings = SimpleNamespace(openai_response_model="gpt-5.4")

    def health(self) -> ProviderHealthResponse:
        return ProviderHealthResponse(
            provider_name=self.name,
            healthy=True,
            configured=True,
            connected=True,
            auth_type=self.auth_type,
            detail="test",
            missing_env=[],
            scopes=[],
            expires_at=None,
        )

    async def respond_async(self, **kwargs) -> AgentModelResponse:
        self.calls.append(kwargs)
        output_text = json.dumps(self.output, ensure_ascii=False)
        return AgentModelResponse(
            provider_name=self.name,
            model=str(kwargs.get("model") or ""),
            message=AgentMessage(role="assistant", content=output_text),
            output_text=output_text,
        )


def _registry() -> tuple[ProviderRegistry, FakeProvider, FakeProvider]:
    openai = FakeProvider("openai_api", {"ok": True})
    gemini = FakeProvider(
        "gemini_api",
        {
            "shouldRecall": True,
            "query": "사용자 선호",
            "reason": "profile_needed",
            "usedMemoryIds": [1],
            "scores": {"1": 0.9},
        },
    )
    return ProviderRegistry([openai, gemini]), openai, gemini


@pytest.mark.asyncio
async def test_memory_recall_planner_selects_gemini_provider_from_runtime_context():
    registry, openai, gemini = _registry()
    client = ProviderMemoryRecallPlannerClient(provider_registry=registry)

    await client.plan_memory_recall_json(
        system_prompt="plan",
        query="내 선호 기억해?",
        workspace_key=None,
        rule_plan=MemoryRecallPlan(should_recall=True, query="내 선호 기억해?", reason="rule"),
        runtime_context={
            "user_id": "7",
            "provider_name": "gemini_api_key",
            "model": "gemini-2.5-flash",
        },
    )

    assert openai.calls == []
    assert gemini.calls[0]["model"] == "gemini-2.5-flash"
    assert gemini.calls[0]["runtime_context"]["provider_name"] == "gemini_api_key"
    assert client.last_memory_provider_meta["provider_name"] == "gemini_api"


@pytest.mark.asyncio
async def test_memory_extraction_selects_gemini_provider_from_context():
    registry, openai, gemini = _registry()
    client = ProviderMemoryExtractionClient(provider_registry=registry)

    await client.extract_memory_json(
        system_prompt="extract",
        user_message="내 답변은 짧게 해줘.",
        assistant_message="알겠습니다.",
        context=MemoryExtractionContext(
            user_id="7",
            session_id="session_1",
            provider_name="gemini_api_key",
            model="gemini-2.5-flash",
        ),
    )

    assert openai.calls == []
    assert gemini.calls[0]["model"] == "gemini-2.5-flash"
    assert gemini.calls[0]["runtime_context"]["provider_name"] == "gemini_api_key"
    assert client.last_memory_provider_meta["provider_name"] == "gemini_api"


@pytest.mark.asyncio
async def test_memory_usage_attribution_selects_gemini_provider_from_runtime_context():
    registry, openai, gemini = _registry()
    client = ProviderMemoryUsageAttributionClient(provider_registry=registry)

    await client.verify_memory_usage_json(
        system_prompt="verify",
        user_query="짧게 정리해줘.",
        assistant_message="요약했습니다.",
        recalled_memories=[{"id": 1, "content": "사용자는 짧은 답변을 선호한다."}],
        runtime_context={
            "user_id": "7",
            "provider_name": "gemini_api_key",
            "model": "gemini-2.5-flash",
        },
    )

    assert openai.calls == []
    assert gemini.calls[0]["model"] == "gemini-2.5-flash"
    assert gemini.calls[0]["runtime_context"]["provider_name"] == "gemini_api_key"
    assert client.last_memory_provider_meta["provider_name"] == "gemini_api"
