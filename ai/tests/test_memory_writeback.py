from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from app.api.memory_writeback import writeback_persistent_memory_candidates
from app.clients.backend_memory import BackendMemoryClientError


class FakeMemoryClient:
    def __init__(
        self,
        *,
        fail: bool = False,
        fail_recall: bool = False,
        fail_error: BackendMemoryClientError | None = None,
        memories=None,
    ) -> None:
        self.calls = []
        self.recall_calls = []
        self.fail = fail
        self.fail_recall = fail_recall
        self.fail_error = fail_error
        self.memories = list(memories or [])

    async def recall(self, **kwargs):
        self.recall_calls.append(kwargs)
        if self.fail_recall:
            raise BackendMemoryClientError("backend failed")
        return list(self.memories)

    async def create_candidates(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail_error or BackendMemoryClientError("backend failed")
        return []


class FakeExtractor:
    def __init__(self, candidates=None, *, fail: bool = False, fail_error: Exception | None = None) -> None:
        self.calls = []
        self.candidates = candidates or []
        self.fail = fail
        self.fail_error = fail_error

    async def extract_candidates(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise self.fail_error or RuntimeError("extract failed")
        return list(self.candidates)


class FakeOperationProvider:
    def __init__(self, decision) -> None:
        self.calls = []
        self.decision = decision

    async def reconcile_memory_operation_json(self, **kwargs):
        self.calls.append(kwargs)
        return dict(self.decision)


@pytest.mark.asyncio
async def test_writeback_extracts_and_posts_candidates_to_backend():
    candidate = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "ADD",
        "content": "사용자는 짧은 답변을 선호한다.",
        "metadata": {"source": "ai.writeback"},
        "importance": 0.8,
        "confidence": 0.9,
    }
    memory_client = FakeMemoryClient()
    extractor = FakeExtractor([candidate])
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="앞으로 짧게 답해줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
        workspace_key="workspace-a",
        task_run_id="task_1",
        user_message_id="msg_1",
        assistant_message_id="msg_2",
        model="gpt-current",
        request_date="2026-05-16",
        provider_name="openai_api_key",
    )

    assert len(extractor.calls) == 1
    assert extractor.calls[0]["context"].workspace_key == "workspace-a"
    assert extractor.calls[0]["context"].model == "gpt-current"
    assert extractor.calls[0]["context"].request_date == "2026-05-16"
    assert extractor.calls[0]["context"].provider_name == "openai_api_key"
    assert extractor.calls[0]["context"].task_run_id == "task_1"
    assert extractor.calls[0]["context"].session_id == "session_1"
    assert memory_client.recall_calls == [
        {
            "user_id": "1",
            "query": "사용자는 짧은 답변을 선호한다.",
            "limit": 5,
            "workspace_key": None,
            "store_type": "USER_PROFILE",
            "memory_type": "PREFERENCE",
            "scope_type": "GLOBAL",
            "tags": None,
        }
    ]
    assert memory_client.calls == [{"user_id": "1", "candidates": [candidate]}]
    assert observation["status"] == "succeeded"
    assert observation["attempted"] is True
    assert observation["candidate_count"] == 1
    assert observation["memory_types"] == ["PREFERENCE"]
    assert observation["store_types"] == ["USER_PROFILE"]
    assert observation["scope_types"] == ["GLOBAL"]
    assert observation["operation_types"] == ["ADD"]
    assert observation["failed"] is False
    assert observation["original_candidate_count"] == 1
    assert observation["final_candidate_count"] == 1
    assert observation["skipped_candidate_count"] == 0
    assert observation["skipped_target_memory_ids"] == []


@pytest.mark.asyncio
async def test_writeback_is_nonfatal_when_extractor_fails():
    memory_client = FakeMemoryClient()
    extractor = FakeExtractor(fail=True)
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="기억해줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    assert memory_client.calls == []
    assert observation["status"] == "extract_failed"
    assert observation["failed"] is True


@pytest.mark.asyncio
async def test_writeback_records_http_error_details_when_extractor_fails():
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(429, request=request, text="rate limited")
    memory_client = FakeMemoryClient()
    extractor = FakeExtractor(
        fail=True,
        fail_error=httpx.HTTPStatusError("rate limited", request=request, response=response),
    )
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="나 국수 좋아해.",
        assistant_message="국수도 좋죠.",
        session_id="session_1",
    )

    assert memory_client.calls == []
    assert observation["status"] == "extract_failed"
    assert observation["reason"] == "memory_extractor_http_error"
    assert observation["error_type"] == "HTTPStatusError"
    assert observation["provider_status_code"] == 429
    assert observation["retryable"] is True
    assert observation["provider_error_message"] == "rate limited"


@pytest.mark.asyncio
async def test_writeback_is_nonfatal_when_backend_fails():
    memory_client = FakeMemoryClient(
        fail=True,
        fail_error=BackendMemoryClientError(
            "backend failed",
            status_code=409,
            error_code="MEMORY_TARGET_INACTIVE",
            response_message="target memory is inactive",
        ),
    )
    extractor = FakeExtractor(
        [
            {
                "memoryType": "FACT",
                "storeType": "AGENT_MEMORY",
                "scopeType": "GLOBAL",
                "operationType": "ADD",
                "content": "사용자는 테스트를 사용한다.",
                "metadata": {"source": "ai.writeback"},
                "importance": 0.7,
                "confidence": 0.9,
            }
        ]
    )
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="기억해줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    assert len(memory_client.calls) == 1
    assert observation["status"] == "store_failed"
    assert observation["attempted"] is True
    assert observation["candidate_count"] == 1
    assert observation["backend_status"] == 409
    assert observation["backend_error_code"] == "MEMORY_TARGET_INACTIVE"
    assert observation["backend_error_message"] == "target memory is inactive"


@pytest.mark.asyncio
async def test_writeback_reconciles_preference_change_to_update():
    candidate = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "ADD",
        "content": "사용자는 Jira 항목을 [BE] fix / [AI] feat 형식으로 나누는 것을 선호한다.",
        "summary": "Jira 작성 형식 선호",
        "metadata": {"source": "ai.writeback", "tags": ["jira"]},
        "importance": 0.8,
        "confidence": 0.9,
    }
    memory_client = FakeMemoryClient(
        memories=[
            SimpleNamespace(
                id=10,
                memory_type="PREFERENCE",
                store_type="USER_PROFILE",
                scope_type="GLOBAL",
                content="사용자는 Jira 항목을 [AI] feat 형식으로 정리하는 것을 선호한다.",
                summary="Jira 작성 형식 선호",
            )
        ]
    )
    extractor = FakeExtractor([candidate])
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="앞으로 Jira는 [BE] fix / [AI] feat 이렇게 역할별로 나눠줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    saved_candidate = memory_client.calls[0]["candidates"][0]
    assert saved_candidate["operationType"] == "UPDATE"
    assert saved_candidate["targetMemoryId"] == 10
    assert "갱신" in saved_candidate["updateReason"]
    assert observation["operation_types"] == ["UPDATE"]


@pytest.mark.asyncio
async def test_writeback_reconciles_changed_lunch_preference_with_filter_retry():
    candidate = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "ADD",
        "content": "사용자는 최근 점심 추천에서 고기보다 가벼운 샐러드나 생선 메뉴를 더 선호한다.",
        "summary": "점심은 샐러드/생선 우선 선호",
        "metadata": {"source": "ai.writeback", "category": "preference", "tags": ["food", "lunch", "preference"]},
        "importance": 0.82,
        "confidence": 0.95,
    }
    memory_client = FakeMemoryClient(
        memories=[
            SimpleNamespace(
                id=3,
                memory_type="PREFERENCE",
                store_type="USER_PROFILE",
                scope_type="GLOBAL",
                content="사용자는 점심 메뉴로 고기를 가장 좋아하며, 특히 돼지고기나 소고기처럼 든든한 메뉴를 선호한다.",
                summary="점심에 고기, 특히 돼지고기·소고기 선호",
                metadata={"source": "ai.writeback", "category": "preference", "tags": ["food", "lunch", "meat", "pork", "beef"]},
            )
        ]
    )
    extractor = FakeExtractor([candidate])
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="요즘은 고기보다 가벼운 샐러드나 생선 메뉴가 더 좋아. 점심 추천할 때는 이걸 우선해줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    saved_candidate = memory_client.calls[0]["candidates"][0]
    assert len(memory_client.recall_calls) == 1
    assert saved_candidate["operationType"] == "UPDATE"
    assert saved_candidate["targetMemoryId"] == 3
    assert observation["operation_types"] == ["UPDATE"]


@pytest.mark.asyncio
async def test_writeback_retries_preference_reconciliation_without_query_when_semantic_recall_is_empty():
    candidate = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "ADD",
        "content": "사용자는 최근 점심 추천에서 고기보다 가벼운 샐러드나 생선 메뉴를 더 선호한다.",
        "summary": "점심은 샐러드/생선 우선 선호",
        "metadata": {"source": "ai.writeback", "category": "preference", "tags": ["food", "lunch", "preference"]},
        "importance": 0.82,
        "confidence": 0.95,
    }

    class RetryMemoryClient(FakeMemoryClient):
        async def recall(self, **kwargs):
            self.recall_calls.append(kwargs)
            if kwargs.get("query"):
                return []
            return [
                SimpleNamespace(
                    id=3,
                    memory_type="PREFERENCE",
                    store_type="USER_PROFILE",
                    scope_type="GLOBAL",
                    content="사용자는 점심 메뉴로 고기를 가장 좋아하며, 특히 돼지고기나 소고기처럼 든든한 메뉴를 선호한다.",
                    summary="점심에 고기, 특히 돼지고기·소고기 선호",
                    metadata={"source": "ai.writeback", "category": "preference", "tags": ["food", "lunch", "meat"]},
                )
            ]

    memory_client = RetryMemoryClient()
    extractor = FakeExtractor([candidate])
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="요즘은 고기보다 가벼운 샐러드나 생선 메뉴가 더 좋아. 점심 추천할 때는 이걸 우선해줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    saved_candidate = memory_client.calls[0]["candidates"][0]
    assert len(memory_client.recall_calls) == 2
    assert memory_client.recall_calls[0]["query"] == "점심은 샐러드/생선 우선 선호"
    assert memory_client.recall_calls[1]["query"] is None
    assert memory_client.recall_calls[1]["tags"] == ["food", "lunch", "preference"]
    assert saved_candidate["operationType"] == "UPDATE"
    assert saved_candidate["targetMemoryId"] == 3
    assert observation["operation_types"] == ["UPDATE"]


@pytest.mark.asyncio
async def test_writeback_uses_llm_operation_reconciliation_decision():
    candidate = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "ADD",
        "content": "사용자는 점심 추천에서 샐러드나 생선 메뉴를 우선 선호한다.",
        "summary": "점심은 샐러드/생선 우선",
        "metadata": {"source": "ai.writeback", "category": "preference", "tags": ["food", "lunch", "preference"]},
        "importance": 0.82,
        "confidence": 0.95,
    }
    memory_client = FakeMemoryClient(
        memories=[
            SimpleNamespace(
                id=3,
                memory_type="PREFERENCE",
                store_type="USER_PROFILE",
                scope_type="GLOBAL",
                content="사용자는 점심 메뉴로 고기를 가장 좋아한다.",
                summary="점심에 고기 선호",
                metadata={"source": "ai.writeback", "category": "preference", "tags": ["food", "lunch", "meat"]},
            ),
            SimpleNamespace(
                id=8,
                memory_type="PREFERENCE",
                store_type="USER_PROFILE",
                scope_type="GLOBAL",
                content="사용자는 점심 메뉴로 돼지고기나 소고기처럼 든든한 고기 메뉴를 선호한다.",
                summary="점심에 돼지고기/소고기 선호",
                metadata={"source": "ai.writeback", "category": "preference", "tags": ["food", "lunch", "meat", "beef"]},
            )
        ]
    )
    operation_provider = FakeOperationProvider(
        {
            "operationType": "UPDATE",
            "targetMemoryId": 3,
            "additionalTargetMemoryIds": [8, 999, 3, 8],
            "reason": "사용자가 최근 점심 선호를 샐러드/생선 우선으로 바꿨다.",
        }
    )
    extractor = FakeExtractor([candidate])
    app_state = SimpleNamespace(
        backend_memory_client=memory_client,
        memory_extractor=extractor,
        memory_operation_provider=operation_provider,
    )

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="점심은 이제 가벼운 샐러드나 생선 위주로 추천해줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    saved_candidate = memory_client.calls[0]["candidates"][0]
    assert len(operation_provider.calls) == 1
    assert operation_provider.calls[0]["candidate"] == candidate
    assert operation_provider.calls[0]["existing_memories"][0]["id"] == 3
    assert saved_candidate["operationType"] == "UPDATE"
    assert saved_candidate["targetMemoryId"] == 3
    assert saved_candidate["additionalTargetMemoryIds"] == [8]
    assert saved_candidate["updateReason"] == "사용자가 최근 점심 선호를 샐러드/생선 우선으로 바꿨다."
    assert observation["operation_types"] == ["UPDATE"]


@pytest.mark.asyncio
async def test_writeback_keeps_add_when_reconciliation_recall_fails():
    candidate = {
        "memoryType": "FACT",
        "storeType": "AGENT_MEMORY",
        "scopeType": "GLOBAL",
        "operationType": "ADD",
        "content": "프로젝트는 장기기억 후보 저장 기능을 사용한다.",
        "metadata": {"source": "ai.writeback"},
        "importance": 0.7,
        "confidence": 0.9,
    }
    memory_client = FakeMemoryClient(fail_recall=True)
    extractor = FakeExtractor([candidate])
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="기억해줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    assert memory_client.calls == [{"user_id": "1", "candidates": [candidate]}]
    assert observation["status"] == "succeeded"
    assert observation["operation_types"] == ["ADD"]


@pytest.mark.asyncio
async def test_writeback_skips_later_update_candidate_with_same_target_memory():
    first_update = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "UPDATE",
        "targetMemoryId": 10,
        "content": "사용자는 점심으로 샐러드를 선호한다.",
        "metadata": {"source": "ai.writeback"},
        "importance": 0.8,
        "confidence": 0.9,
    }
    second_update = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "UPDATE",
        "targetMemoryId": 10,
        "content": "사용자는 점심으로 생선을 선호한다.",
        "metadata": {"source": "ai.writeback"},
        "importance": 0.8,
        "confidence": 0.9,
    }
    add_candidate = {
        "memoryType": "FACT",
        "storeType": "AGENT_MEMORY",
        "scopeType": "GLOBAL",
        "operationType": "ADD",
        "content": "프로젝트는 장기기억 writeback을 사용한다.",
        "metadata": {"source": "ai.writeback"},
        "importance": 0.7,
        "confidence": 0.9,
    }
    memory_client = FakeMemoryClient()
    extractor = FakeExtractor([first_update, second_update, add_candidate])
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="점심 선호를 바꿔줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    assert memory_client.calls[0]["candidates"] == [first_update, add_candidate]
    assert observation["status"] == "succeeded"
    assert observation["candidate_count"] == 2
    assert observation["original_candidate_count"] == 3
    assert observation["final_candidate_count"] == 2
    assert observation["skipped_candidate_count"] == 1
    assert observation["skipped_target_memory_ids"] == [10]
    assert observation["operation_types"] == ["ADD", "UPDATE"]


@pytest.mark.asyncio
async def test_writeback_skips_later_candidate_overlapping_additional_target_memory():
    first_update = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "UPDATE",
        "targetMemoryId": 10,
        "additionalTargetMemoryIds": [11],
        "content": "사용자는 점심으로 샐러드를 선호한다.",
        "metadata": {"source": "ai.writeback"},
        "importance": 0.8,
        "confidence": 0.9,
    }
    second_update = {
        "memoryType": "PREFERENCE",
        "storeType": "USER_PROFILE",
        "scopeType": "GLOBAL",
        "operationType": "UPDATE",
        "targetMemoryId": 11,
        "content": "사용자는 점심으로 생선을 선호한다.",
        "metadata": {"source": "ai.writeback"},
        "importance": 0.8,
        "confidence": 0.9,
    }
    memory_client = FakeMemoryClient()
    extractor = FakeExtractor([first_update, second_update])
    app_state = SimpleNamespace(backend_memory_client=memory_client, memory_extractor=extractor)

    observation = await writeback_persistent_memory_candidates(
        app_state=app_state,
        user_id="1",
        user_message="점심 선호를 바꿔줘.",
        assistant_message="알겠습니다.",
        session_id="session_1",
    )

    assert memory_client.calls[0]["candidates"] == [first_update]
    assert observation["original_candidate_count"] == 2
    assert observation["final_candidate_count"] == 1
    assert observation["skipped_candidate_count"] == 1
    assert observation["skipped_target_memory_ids"] == [11]
