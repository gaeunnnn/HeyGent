import asyncio
from types import SimpleNamespace

import httpx
import pytest

from app.api.memory_context import (
    LlmMemoryRecallPlanner,
    attach_persistent_memory_context,
    plan_memory_recall,
    select_memory_recall_query,
)
from app.clients.backend_memory import BackendMemoryClientError, BackendMemoryItem


class FakeMemoryClient:
    def __init__(self, memories=None, *, fail: bool = False) -> None:
        self.memories = list(memories or [])
        self.fail = fail
        self.calls = []

    async def recall(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise BackendMemoryClientError("recall failed")
        return list(self.memories)


class EmptyThenMemoryClient(FakeMemoryClient):
    async def recall(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) == 1:
            return []
        return list(self.memories)


class FilteredMemoryClient:
    def __init__(self, memories_by_filter: dict[tuple[str | None, str | None], list[BackendMemoryItem]]) -> None:
        self.memories_by_filter = memories_by_filter
        self.calls = []

    async def recall(self, **kwargs):
        self.calls.append(kwargs)
        key = (kwargs.get("store_type"), kwargs.get("memory_type"))
        return list(self.memories_by_filter.get(key, self.memories_by_filter.get((kwargs.get("store_type"), None), [])))


class QueryAwareFilteredMemoryClient(FilteredMemoryClient):
    async def recall(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("query") is not None:
            return []
        key = (kwargs.get("store_type"), kwargs.get("memory_type"))
        return list(self.memories_by_filter.get(key, self.memories_by_filter.get((kwargs.get("store_type"), None), [])))


class FakeRecallPlannerProvider:
    def __init__(
        self,
        payload=None,
        *,
        fail: bool = False,
        fail_error: Exception | None = None,
        delay_seconds: float = 0.0,
    ) -> None:
        self.payload = payload or {}
        self.fail = fail
        self.fail_error = fail_error
        self.delay_seconds = delay_seconds
        self.calls = []
        self.last_memory_provider_meta = {}

    async def plan_memory_recall_json(self, **kwargs):
        self.calls.append(kwargs)
        self.last_memory_provider_meta = {
            "provider_name": "fake_memory_provider",
            "selected_model": kwargs.get("model") or "fake-default",
            "max_attempts": 3,
        }
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.fail:
            raise self.fail_error or RuntimeError("planner failed")
        return self.payload


def _memory(
    content: str,
    *,
    memory_id: int = 1,
    memory_type: str = "PREFERENCE",
    store_type: str = "PROFILE",
    summary: str = "선호 요약",
) -> BackendMemoryItem:
    return BackendMemoryItem(
        id=memory_id,
        memory_type=memory_type,
        store_type=store_type,
        scope_type="GLOBAL",
        content=content,
        summary=summary,
        importance=0.8,
        confidence=0.9,
        metadata={"workspaceKey": "team-a", "token": "hidden"},
    )


def test_select_memory_recall_query_uses_prompt_like_fields():
    assert select_memory_recall_query({"prompt": "  현재 요청  "}) == "현재 요청"
    assert select_memory_recall_query({"count": 1, "message": ""}) is None
    assert select_memory_recall_query({"subject": "회의 정리"}) == "회의 정리"


def test_recall_planner_prompt_separates_instructions_from_task_state():
    from app.api.memory_context import MEMORY_RECALL_PLANNER_SYSTEM_PROMPT

    assert "AGENT_MEMORY/INSTRUCTION/GLOBAL/instruction,procedure" in MEMORY_RECALL_PLANNER_SYSTEM_PROMPT
    assert "Do not classify saved answer-format instructions" in MEMORY_RECALL_PLANNER_SYSTEM_PROMPT
    assert "current user situations embedded in task requests" in MEMORY_RECALL_PLANNER_SYSTEM_PROMPT
    assert "interview preparation" in MEMORY_RECALL_PLANNER_SYSTEM_PROMPT
    assert "지난번처럼 docs/logs 작업하고 커밋해줘" in MEMORY_RECALL_PLANNER_SYSTEM_PROMPT
    assert "preferred name, nickname, addressing" in MEMORY_RECALL_PLANNER_SYSTEM_PROMPT


def test_plan_memory_recall_skips_low_value_greeting():
    plan = plan_memory_recall("안녕")

    assert plan.should_recall is False
    assert plan.reason == "low_value_query"


def test_plan_memory_recall_selects_user_preference_filters():
    plan = plan_memory_recall("앞으로 답변은 짧게 해줘", workspace_key="team-a")

    assert plan.should_recall is True
    assert plan.reason == "user_preference_needed"
    assert plan.filters() == {
        "store_type": "USER_PROFILE",
        "memory_type": "PREFERENCE",
        "scope_type": "GLOBAL",
        "metadata_categories": ["preference"],
    }


def test_plan_memory_recall_selects_workspace_task_state_filters():
    plan = plan_memory_recall("4번 장기기억 작업 이어서 해줘", workspace_key="team-a")

    assert plan.should_recall is True
    assert plan.reason == "workspace_memory_needed"
    assert plan.filters() == {
        "store_type": "AGENT_MEMORY",
        "memory_type": "FACT",
        "scope_type": "WORKSPACE",
        "workspace_key": "team-a",
        "metadata_categories": ["task_state", "fact"],
    }


def test_rule_fallback_does_not_treat_generic_plan_as_workspace_state():
    plan = plan_memory_recall("서울 여행 계획 짜줘")

    assert plan.should_recall is True
    assert plan.reason == "general_semantic_recall"
    assert plan.filters() == {}


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_uses_model_structured_filters():
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "MR 작성 선호",
            "reason": "사용자 MR 작성 형식 선호가 필요함",
            "limit": 3,
            "filters": {
                "storeType": "USER_PROFILE",
                "memoryType": "PREFERENCE",
                "scopeType": "GLOBAL",
                "metadataCategories": ["preference", "unknown"],
            },
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)

    plan = await planner.plan_recall("MR 작업내용 정리해줘", workspace_key="team-a", limit=5)

    assert plan.should_recall is True
    assert plan.query == "MR 작성 선호"
    assert plan.reason == "사용자 MR 작성 형식 선호가 필요함"
    assert plan.limit == 3
    assert plan.planner_source == "llm"
    assert plan.planner_latency_ms is not None
    assert plan.filters() == {
        "store_type": "USER_PROFILE",
        "memory_type": "PREFERENCE",
        "scope_type": "GLOBAL",
        "metadata_categories": ["preference"],
    }
    assert provider.calls[0]["rule_plan"].should_recall is True


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_handles_personalized_recommendation():
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "사용자 점심 메뉴 선호",
            "reason": "점심 추천은 사용자 음식 선호가 필요함",
            "filters": {
                "storeType": "USER_PROFILE",
                "memoryType": "PREFERENCE",
                "scopeType": "GLOBAL",
                "metadataCategories": ["preference"],
            },
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)

    plan = await planner.plan_recall("오늘 점심 뭐 먹을까?", workspace_key="team-a")

    assert plan.should_recall is True
    assert plan.query == "사용자 점심 메뉴 선호"
    assert plan.reason == "점심 추천은 사용자 음식 선호가 필요함"
    assert plan.planner_source == "llm"
    assert plan.filters() == {
        "store_type": "USER_PROFILE",
        "memory_type": "PREFERENCE",
        "scope_type": "GLOBAL",
        "metadata_categories": ["preference"],
    }


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_handles_saved_addressing_preference():
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "사용자 호칭 선호",
            "reason": "사용자가 선호하는 호칭 기억이 필요함",
            "filters": {
                "storeType": "USER_PROFILE",
                "memoryType": "PREFERENCE",
                "scopeType": "GLOBAL",
                "metadataCategories": ["preference"],
            },
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)

    plan = await planner.plan_recall("나 뭐라고 부르기로 했지?", workspace_key="team-a")

    assert plan.should_recall is True
    assert plan.query == "사용자 호칭 선호"
    assert plan.reason == "사용자가 선호하는 호칭 기억이 필요함"
    assert plan.planner_source == "llm"
    assert plan.filters() == {
        "store_type": "USER_PROFILE",
        "memory_type": "PREFERENCE",
        "scope_type": "GLOBAL",
        "metadata_categories": ["preference"],
    }


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_handles_current_user_fact_for_planning():
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "사용자 면접 준비 현황",
            "reason": "면접 준비 계획은 사용자의 현재 준비 상태 fact가 필요함",
            "filters": {
                "storeType": "AGENT_MEMORY",
                "memoryType": "FACT",
                "scopeType": "GLOBAL",
                "metadataCategories": ["fact", "event"],
            },
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)

    plan = await planner.plan_recall("면접 준비 계획서 다시 만들어줘", workspace_key="team-a")

    assert plan.should_recall is True
    assert plan.query == "사용자 면접 준비 현황"
    assert plan.reason == "면접 준비 계획은 사용자의 현재 준비 상태 fact가 필요함"
    assert plan.planner_source == "llm"
    assert plan.filters() == {
        "store_type": "AGENT_MEMORY",
        "memory_type": "FACT",
        "scope_type": "GLOBAL",
        "metadata_categories": ["fact", "event"],
    }


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_handles_repeated_docs_logs_workflow():
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "docs logs 작업 절차",
            "reason": "지난번처럼 처리하려면 저장된 반복 작업 절차가 필요함",
            "filters": {
                "storeType": "AGENT_MEMORY",
                "memoryType": "PROCEDURE",
                "scopeType": "WORKSPACE",
                "metadataCategories": ["procedure", "instruction"],
            },
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)

    plan = await planner.plan_recall("지난번처럼 docs/logs 작업하고 커밋해줘", workspace_key="team-a")

    assert plan.should_recall is True
    assert plan.query == "docs logs 작업 절차"
    assert plan.reason == "지난번처럼 처리하려면 저장된 반복 작업 절차가 필요함"
    assert plan.planner_source == "llm"
    assert plan.filters() == {
        "store_type": "AGENT_MEMORY",
        "scope_type": "WORKSPACE",
        "workspace_key": "team-a",
        "metadata_categories": ["procedure", "instruction"],
    }


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_accepts_additional_recall_plans():
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "사용자 선호",
            "reason": "사용자 선호가 답변에 영향을 줄 수 있음",
            "filters": {
                "storeType": "USER_PROFILE",
                "memoryType": "PREFERENCE",
                "scopeType": "GLOBAL",
                "metadataCategories": ["preference"],
            },
            "additionalRecallPlans": [
                {
                    "query": "재사용 가능한 응답 절차",
                    "reason": "저장된 절차가 답변 구조를 바꿀 수 있음",
                    "filters": {
                        "storeType": "AGENT_MEMORY",
                        "memoryType": "INSTRUCTION",
                        "scopeType": "GLOBAL",
                        "metadataCategories": ["instruction", "procedure"],
                    },
                }
            ],
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)

    plan = await planner.plan_recall("부산 여행 계획 짜줘")

    assert plan.filters() == {
        "store_type": "USER_PROFILE",
        "memory_type": "PREFERENCE",
        "scope_type": "GLOBAL",
        "metadata_categories": ["preference"],
    }
    assert len(plan.additional_plans) == 1
    assert plan.additional_plans[0].filters() == {
        "store_type": "AGENT_MEMORY",
        "scope_type": "GLOBAL",
        "metadata_categories": ["instruction", "procedure"],
    }


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_normalizes_profile_fact_mix_to_agent_fact():
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "저녁 메뉴 추천",
            "reason": "추천에 사용자 선호가 필요함",
            "filters": {
                "storeType": "USER_PROFILE",
                "memoryType": "PREFERENCE",
                "scopeType": "GLOBAL",
                "metadataCategories": ["preference"],
            },
            "additionalRecallPlans": [
                {
                    "query": "건강 제한",
                    "reason": "건강 제한이 추천을 바꿀 수 있음",
                    "filters": {
                        "storeType": "USER_PROFILE",
                        "memoryType": "PROFILE",
                        "scopeType": "GLOBAL",
                        "metadataCategories": ["profile", "fact"],
                    },
                }
            ],
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)

    plan = await planner.plan_recall("나 대창구이 먹고싶다. 오늘 저녁에 먹을까?")

    assert len(plan.additional_plans) == 1
    assert plan.additional_plans[0].filters() == {
        "store_type": "AGENT_MEMORY",
        "memory_type": "FACT",
        "scope_type": "GLOBAL",
        "metadata_categories": ["fact"],
    }


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_falls_back_to_rules_on_error():
    planner = LlmMemoryRecallPlanner(provider=FakeRecallPlannerProvider(fail=True))

    plan = await planner.plan_recall("4번 장기기억 작업 이어서 해줘", workspace_key="team-a")

    assert plan.reason == "workspace_memory_needed"
    assert plan.planner_source == "rule_fallback"
    assert plan.fallback_reason == "llm_planner_error:RuntimeError"
    assert plan.planner_latency_ms is not None
    assert plan.filters()["metadata_categories"] == ["task_state", "fact"]


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_records_http_error_fallback_details():
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429, request=request, text="rate limited")
    error = httpx.HTTPStatusError("rate limited", request=request, response=response)
    setattr(error, "memory_selected_model", "gpt-memory-debug")
    setattr(error, "memory_provider_name", "fake_memory_provider")
    setattr(error, "memory_retry_attempts", 3)
    setattr(error, "memory_max_attempts", 3)
    planner = LlmMemoryRecallPlanner(
        provider=FakeRecallPlannerProvider(
            fail=True,
            fail_error=error,
        )
    )

    plan = await planner.plan_recall("나 국수 좋아해", workspace_key="team-a")

    assert plan.reason == "general_semantic_recall"
    assert plan.planner_source == "rule_fallback"
    assert plan.fallback_reason == "llm_planner_http_error:429"
    assert plan.fallback_error_type == "HTTPStatusError"
    assert plan.fallback_status_code == 429
    assert plan.fallback_selected_model == "gpt-memory-debug"
    assert plan.fallback_provider_name == "fake_memory_provider"
    assert plan.fallback_retry_attempts == 3
    assert plan.fallback_max_attempts == 3
    assert plan.fallback_provider_error_message == "rate limited"
    assert plan.planner_latency_ms is not None


@pytest.mark.asyncio
async def test_llm_memory_recall_planner_times_out_to_rule_fallback():
    planner = LlmMemoryRecallPlanner(
        provider=FakeRecallPlannerProvider(delay_seconds=0.05),
        timeout_seconds=0.01,
    )

    plan = await planner.plan_recall("4번 장기기억 작업 이어서 해줘", workspace_key="team-a")

    assert plan.reason == "workspace_memory_needed"
    assert plan.planner_source == "rule_fallback"
    assert plan.fallback_reason == "llm_planner_timeout"
    assert plan.fallback_selected_model == "fake-default"
    assert plan.fallback_provider_name == "fake_memory_provider"
    assert plan.fallback_max_attempts == 3
    assert plan.planner_latency_ms is not None


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_replaces_client_supplied_context():
    memory_client = FakeMemoryClient([_memory("사용자는 회의 요약을 짧게 받는 것을 선호한다.")])
    task_input = {
        "prompt": "오늘 회의 정리해줘",
        "persistent_memory_context": "client supplied context",
        "memory_context": "legacy client supplied context",
        "memory_context_meta": {"recall": {"status": "client_supplied"}},
    }

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=memory_client),
        task_input=task_input,
        user_id="7",
        query="오늘 회의 정리해줘",
        workspace_key="team-a",
    )

    assert memory_client.calls == [
        {
            "user_id": "7",
            "query": "오늘 회의 정리해줘",
            "limit": 5,
            "workspace_key": None,
            "store_type": None,
            "memory_type": None,
            "scope_type": None,
            "metadata_categories": None,
        }
    ]
    assert "client supplied context" not in task_input["persistent_memory_context"]
    assert "legacy client supplied context" not in str(task_input)
    assert "사용자는 회의 요약을 짧게 받는 것을 선호한다." in task_input["persistent_memory_context"]
    assert "hidden" not in task_input["persistent_memory_context"]
    recall_meta = task_input["memory_context_meta"]["recall"]
    assert recall_meta["status"] == "injected"
    assert recall_meta["source"] == "backend"
    assert recall_meta["query_present"] is True
    assert recall_meta["workspace_key_present"] is False
    assert recall_meta["count"] == 1
    assert recall_meta["memory_ids"] == [1]
    assert recall_meta["memory_types"] == ["PREFERENCE"]
    assert recall_meta["store_types"] == ["PROFILE"]
    assert recall_meta["scope_types"] == ["GLOBAL"]
    assert recall_meta["failed"] is False
    assert recall_meta["planner"]["should_recall"] is True
    assert recall_meta["planner"]["reason"] == "general_semantic_recall"
    assert recall_meta["planner"]["source"] == "rule"
    assert recall_meta["planner"]["filters"] == {}


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_uses_llm_planner_when_available():
    memory_client = FakeMemoryClient([_memory("사용자는 MR 설명을 짧게 받는 것을 선호한다.")])
    provider = FakeRecallPlannerProvider(
        {
            "shouldRecall": True,
            "query": "MR 작성 선호",
            "reason": "사용자 MR 작성 선호 필요",
            "filters": {
                "storeType": "USER_PROFILE",
                "memoryType": "PREFERENCE",
                "scopeType": "GLOBAL",
                "metadataCategories": ["preference"],
            },
        }
    )
    planner = LlmMemoryRecallPlanner(provider=provider)
    task_input = {
        "prompt": "MR 작업내용 정리해줘",
        "model": "gpt-current",
        "provider_name": "openai_api_key",
        "session_id": "session_1",
    }

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=memory_client, memory_recall_planner=planner),
        task_input=task_input,
        user_id="7",
        query="MR 작업내용 정리해줘",
        workspace_key="team-a",
    )

    assert memory_client.calls == [
        {
            "user_id": "7",
            "query": "MR 작성 선호",
            "limit": 5,
            "workspace_key": None,
            "store_type": "USER_PROFILE",
            "memory_type": "PREFERENCE",
            "scope_type": "GLOBAL",
            "metadata_categories": ["preference"],
        }
    ]
    assert provider.calls[0]["model"] == "gpt-current"
    assert provider.calls[0]["runtime_context"] == {
        "user_id": "7",
        "provider_name": "openai_api_key",
        "session_id": "session_1",
        "model": "gpt-current",
    }
    planner_meta = task_input["memory_context_meta"]["recall"]["planner"]
    assert planner_meta["should_recall"] is True
    assert planner_meta["reason"] == "사용자 MR 작성 선호 필요"
    assert planner_meta["source"] == "llm"
    assert planner_meta["latency_ms"] is not None
    assert planner_meta["filters"] == {
        "store_type": "USER_PROFILE",
        "memory_type": "PREFERENCE",
        "scope_type": "GLOBAL",
        "metadata_categories": ["preference"],
    }


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_executes_additional_llm_plans():
    memory_client = FilteredMemoryClient(
        {
            ("USER_PROFILE", "PREFERENCE"): [
                _memory(
                    "사용자는 반말로 대화해주길 선호한다.",
                    memory_id=10,
                    store_type="USER_PROFILE",
                    summary="반말 선호",
                )
            ],
            ("AGENT_MEMORY", None): [
                _memory(
                    "여행 계획 요청 시 날짜와 예산을 먼저 확인한 뒤 교통편, 숙소, 식당 순서로 계획한다.",
                    memory_id=11,
                    memory_type="INSTRUCTION",
                    store_type="AGENT_MEMORY",
                    summary="여행 계획 절차",
                ),
                _memory(
                    "사용자가 여행 계획을 부탁하면 먼저 날짜와 예산을 확인한 뒤, 교통편, 숙소, 식당 순서로 계획을 짠다.",
                    memory_id=12,
                    memory_type="PROCEDURE",
                    store_type="AGENT_MEMORY",
                    summary="여행 계획 절차 프로시저",
                )
            ],
        }
    )
    planner = LlmMemoryRecallPlanner(
        provider=FakeRecallPlannerProvider(
            {
                "shouldRecall": True,
                "query": "사용자 선호",
                "reason": "사용자 선호가 답변에 영향을 줄 수 있음",
                "filters": {
                    "storeType": "USER_PROFILE",
                    "memoryType": "PREFERENCE",
                    "scopeType": "GLOBAL",
                    "metadataCategories": ["preference"],
                },
                "additionalRecallPlans": [
                    {
                        "query": "재사용 가능한 응답 절차",
                        "reason": "저장된 절차가 답변 구조를 바꿀 수 있음",
                        "filters": {
                            "storeType": "AGENT_MEMORY",
                            "memoryType": "INSTRUCTION",
                            "scopeType": "GLOBAL",
                            "metadataCategories": ["instruction", "procedure"],
                        },
                    }
                ],
            }
        )
    )
    task_input = {"prompt": "부산 여행 계획 짜줘"}

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=memory_client, memory_recall_planner=planner),
        task_input=task_input,
        user_id="7",
        query="부산 여행 계획 짜줘",
    )

    assert memory_client.calls == [
        {
            "user_id": "7",
            "query": "사용자 선호",
            "limit": 5,
            "workspace_key": None,
            "store_type": "USER_PROFILE",
            "memory_type": "PREFERENCE",
            "scope_type": "GLOBAL",
            "metadata_categories": ["preference"],
        },
        {
            "user_id": "7",
            "query": "재사용 가능한 응답 절차",
            "limit": 5,
            "workspace_key": None,
            "store_type": "AGENT_MEMORY",
            "memory_type": None,
            "scope_type": "GLOBAL",
            "metadata_categories": ["instruction", "procedure"],
        },
    ]
    recall_meta = task_input["memory_context_meta"]["recall"]
    assert recall_meta["status"] == "injected"
    assert recall_meta["count"] == 3
    assert recall_meta["memory_ids"] == [10, 11, 12]
    assert recall_meta["planner"]["additional_plans"] == [
        {
            "reason": "저장된 절차가 답변 구조를 바꿀 수 있음",
            "source": "llm",
            "filters": {
                "store_type": "AGENT_MEMORY",
                "scope_type": "GLOBAL",
                "metadata_categories": ["instruction", "procedure"],
            },
            "query_present": True,
        }
    ]
    assert "여행 계획 요청 시 날짜와 예산" in task_input["persistent_memory_context"]
    assert "사용자가 여행 계획을 부탁하면 먼저 날짜와 예산" in task_input["persistent_memory_context"]


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_retries_user_preference_recall_without_query_when_empty():
    memory_client = EmptyThenMemoryClient([_memory("사용자는 점심 추천에서 샐러드나 생선 메뉴를 우선 선호한다.")])
    planner = LlmMemoryRecallPlanner(
        provider=FakeRecallPlannerProvider(
            {
                "shouldRecall": True,
                "query": "오늘 점심 뭐 먹을까?",
                "reason": "점심 추천은 사용자 음식 선호가 필요함",
                "filters": {
                    "storeType": "USER_PROFILE",
                    "memoryType": "PREFERENCE",
                    "scopeType": "GLOBAL",
                    "metadataCategories": ["preference"],
                },
            }
        )
    )
    task_input = {"prompt": "오늘 점심 뭐 먹을까?"}

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=memory_client, memory_recall_planner=planner),
        task_input=task_input,
        user_id="7",
        query="오늘 점심 뭐 먹을까?",
    )

    assert memory_client.calls == [
        {
            "user_id": "7",
            "query": "오늘 점심 뭐 먹을까?",
            "limit": 5,
            "workspace_key": None,
            "store_type": "USER_PROFILE",
            "memory_type": "PREFERENCE",
            "scope_type": "GLOBAL",
            "metadata_categories": ["preference"],
        },
        {
            "user_id": "7",
            "query": None,
            "limit": 5,
            "workspace_key": None,
            "store_type": "USER_PROFILE",
            "memory_type": "PREFERENCE",
            "scope_type": "GLOBAL",
            "metadata_categories": ["preference"],
        },
    ]
    assert task_input["memory_context_meta"]["recall"]["status"] == "injected"
    assert task_input["memory_context_meta"]["recall"]["count"] == 1
    assert "샐러드나 생선" in task_input["persistent_memory_context"]


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_retries_agent_fact_recall_without_query_when_empty():
    memory_client = QueryAwareFilteredMemoryClient(
        {
            ("AGENT_MEMORY", "FACT"): [
                _memory(
                    "지난주 금요일에 건강검진을 받았고, 당분간 식단 추천 시 기름진 음식을 줄여야 한다.",
                    memory_id=13,
                    memory_type="FACT",
                    store_type="AGENT_MEMORY",
                    summary="건강검진 후 당분간 기름진 음식 제한",
                )
            ]
        }
    )
    planner = LlmMemoryRecallPlanner(
        provider=FakeRecallPlannerProvider(
            {
                "shouldRecall": True,
                "query": "오늘 저녁 뭐먹지? 나 기름진 전골 먹고싶다",
                "reason": "건강 제한이 추천을 바꿀 수 있음",
                "filters": {
                    "storeType": "AGENT_MEMORY",
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "metadataCategories": ["event", "fact", "reason"],
                },
            }
        )
    )
    task_input = {"prompt": "오늘 저녁 뭐먹지? 나 기름진 전골 먹고싶다"}

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=memory_client, memory_recall_planner=planner),
        task_input=task_input,
        user_id="7",
        query="오늘 저녁 뭐먹지? 나 기름진 전골 먹고싶다",
    )

    assert memory_client.calls == [
        {
            "user_id": "7",
            "query": "오늘 저녁 뭐먹지? 나 기름진 전골 먹고싶다",
            "limit": 5,
            "workspace_key": None,
            "store_type": "AGENT_MEMORY",
            "memory_type": "FACT",
            "scope_type": "GLOBAL",
            "metadata_categories": ["event", "fact", "reason"],
        },
        {
            "user_id": "7",
            "query": None,
            "limit": 5,
            "workspace_key": None,
            "store_type": "AGENT_MEMORY",
            "memory_type": "FACT",
            "scope_type": "GLOBAL",
            "metadata_categories": ["event", "fact", "reason"],
        },
    ]
    assert task_input["memory_context_meta"]["recall"]["status"] == "injected"
    assert task_input["memory_context_meta"]["recall"]["count"] == 1
    assert task_input["memory_context_meta"]["recall"]["memory_ids"] == [13]
    assert "기름진 음식을 줄여야" in task_input["persistent_memory_context"]


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_skips_low_value_recall():
    memory_client = FakeMemoryClient([_memory("불러오면 안 되는 기억")])
    task_input = {"prompt": "안녕", "persistent_memory_context": "client supplied context"}

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=memory_client),
        task_input=task_input,
        user_id="7",
        query="안녕",
        workspace_key="team-a",
    )

    assert memory_client.calls == []
    assert "persistent_memory_context" not in task_input
    assert task_input["memory_context_meta"]["recall"]["status"] == "skipped"
    assert task_input["memory_context_meta"]["recall"]["reason"] == "low_value_query"


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_is_nonfatal_on_backend_failure():
    task_input = {"prompt": "실패해도 계속 진행", "persistent_memory_context": "client supplied context"}

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=FakeMemoryClient(fail=True)),
        task_input=task_input,
        user_id="7",
        query="실패해도 계속 진행",
    )

    assert "persistent_memory_context" not in task_input
    assert task_input["memory_context_meta"]["recall"]["status"] == "failed"
    assert task_input["memory_context_meta"]["recall"]["failed"] is True
    assert task_input["memory_context_meta"]["recall"]["reason"] == "backend_memory_client_error"
    assert task_input["memory_context_meta"]["recall"]["planner"]["reason"] == "general_semantic_recall"


@pytest.mark.asyncio
async def test_attach_persistent_memory_context_records_empty_recall():
    task_input = {"prompt": "새 요청"}

    await attach_persistent_memory_context(
        app_state=SimpleNamespace(backend_memory_client=FakeMemoryClient([])),
        task_input=task_input,
        user_id="7",
        query="새 요청",
    )

    assert "persistent_memory_context" not in task_input
    assert task_input["memory_context_meta"]["recall"]["status"] == "empty"
    assert task_input["memory_context_meta"]["recall"]["count"] == 0
