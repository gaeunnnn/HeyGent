from types import SimpleNamespace

import pytest

from app.api.memory_mark_used import mark_used_recalled_memories
from app.clients.backend_memory import BackendMemoryClientError


class FakeMemoryClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls = []

    async def mark_used(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise BackendMemoryClientError("mark used failed")
        return SimpleNamespace(id=kwargs["memory_id"])


class FakeUsageAttributionVerifier:
    def __init__(self, scores=None, fail: bool = False) -> None:
        self.scores = scores or {}
        self.fail = fail
        self.calls = []
        self.last_memory_provider_meta = {
            "provider_name": "fake_memory_provider",
            "selected_model": "gpt-memory-debug",
            "max_attempts": 3,
        }

    async def verify_usage(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("verifier failed")
        return SimpleNamespace(
            scores=dict(self.scores),
            reasons={memory_id: "semantic usage" for memory_id in self.scores},
            source="llm",
            failed=False,
            fallback_reason=None,
            latency_ms=1,
            error_details=None,
        )


def _task_input(memory_ids=None) -> dict:
    memory_ids = memory_ids or [10, 10, 11]
    return {
        "persistent_memory_context": """
<memory-context>
아래 내용은 이전에 저장된 장기기억입니다.

- id: 10
  type: PREFERENCE
  store: USER_PROFILE
  scope: GLOBAL
  summary: MR 작성 형식 선호
  content: 사용자는 MR 작업내용을 짧게 정리하는 것을 선호한다.
- id: 11
  type: FACT
  store: AGENT_MEMORY
  scope: WORKSPACE
  summary: IoT 모델링 진행 상태
  content: IoT 3D 모델링은 1차 초안 단계이다.
</memory-context>
""".strip(),
        "memory_context_meta": {
            "recall": {
                "status": "injected",
                "memory_ids": memory_ids,
            }
        },
    }


def _instruction_task_input(memory_ids=None) -> dict:
    memory_ids = memory_ids or [11]
    return {
        "persistent_memory_context": """
<memory-context>
아래 내용은 이전에 저장된 장기기억입니다.

- id: 11
  type: INSTRUCTION
  store: AGENT_MEMORY
  scope: GLOBAL
  summary: 여행 계획 절차
  content: 여행 계획 요청 시 날짜와 예산을 먼저 확인한 뒤 교통편, 숙소, 식당 순서로 계획한다.
</memory-context>
""".strip(),
        "memory_context_meta": {
            "recall": {
                "status": "injected",
                "memory_ids": memory_ids,
            }
        },
    }


@pytest.mark.asyncio
async def test_mark_used_recalled_memories_marks_attributed_memory_once():
    memory_client = FakeMemoryClient()

    observation = await mark_used_recalled_memories(
        app_state=SimpleNamespace(backend_memory_client=memory_client),
        task_input=_task_input(),
        user_id="7",
        assistant_message="MR 작업내용은 짧게 정리했습니다.",
        task_run_id="task_1",
    )

    assert memory_client.calls == [
        {
            "user_id": "7",
            "memory_id": 10,
            "usefulness_score": 0.7,
            "source_task_run_id": "task_1",
        }
    ]
    assert observation["status"] == "completed"
    assert observation["attempted"] is True
    assert observation["recalled_memory_ids"] == [10, 11]
    assert observation["used_memory_ids"] == [10]
    assert observation["skipped_memory_ids"] == [11]
    assert observation["scores"] == {"10": 0.7}
    assert observation["deduplicated"] is True
    assert observation["task_run_id_present"] is True
    assert observation["attribution"]["heuristic_used_memory_ids"] == [10]
    assert observation["attribution"]["llm_source"] == "unavailable"


@pytest.mark.asyncio
async def test_mark_used_recalled_memories_does_not_heuristically_mark_instruction_by_topic_overlap():
    memory_client = FakeMemoryClient()

    observation = await mark_used_recalled_memories(
        app_state=SimpleNamespace(backend_memory_client=memory_client),
        task_input=_instruction_task_input(),
        user_id="7",
        assistant_message="서울 2박 3일 여행 계획은 경복궁, 성수동, 한강을 중심으로 구성하면 좋습니다.",
        task_run_id="task_1",
    )

    assert memory_client.calls == []
    assert observation["status"] == "skipped"
    assert observation["reason"] == "no_memory_attribution"
    assert observation["used_memory_ids"] == []
    assert observation["skipped_memory_ids"] == [11]


@pytest.mark.asyncio
async def test_mark_used_recalled_memories_uses_llm_attribution_when_semantic_match_has_low_overlap():
    memory_client = FakeMemoryClient()
    verifier = FakeUsageAttributionVerifier(scores={11: 0.88})

    observation = await mark_used_recalled_memories(
        app_state=SimpleNamespace(
            backend_memory_client=memory_client,
            memory_usage_attribution_verifier=verifier,
        ),
        task_input={
            **_task_input(memory_ids=[11]),
            "model": "gpt-current",
            "provider_name": "openai_api_key",
            "session_id": "session_1",
        },
        user_id="7",
        assistant_message="해당 흐름을 이어서 반영했습니다.",
        task_run_id="task_1",
    )

    assert memory_client.calls == [
        {
            "user_id": "7",
            "memory_id": 11,
            "usefulness_score": 0.88,
            "source_task_run_id": "task_1",
        }
    ]
    assert verifier.calls
    assert verifier.calls[0]["runtime_context"] == {
        "user_id": "7",
        "provider_name": "openai_api_key",
        "task_run_id": "task_1",
        "session_id": "session_1",
        "model": "gpt-current",
    }
    assert observation["status"] == "completed"
    assert observation["reason"] == "llm_attribution_verifier"
    assert observation["used_memory_ids"] == [11]
    assert observation["scores"] == {"11": 0.88}
    assert observation["attribution"]["llm_used_memory_ids"] == [11]


@pytest.mark.asyncio
async def test_mark_used_recalled_memories_skips_without_attribution():
    memory_client = FakeMemoryClient()

    observation = await mark_used_recalled_memories(
        app_state=SimpleNamespace(backend_memory_client=memory_client),
        task_input=_task_input(memory_ids=[10]),
        user_id="7",
        assistant_message="새로운 테스트 결과를 정리했습니다.",
        task_run_id="task_1",
    )

    assert memory_client.calls == []
    assert observation["status"] == "skipped"
    assert observation["reason"] == "no_memory_attribution"
    assert observation["used_memory_ids"] == []
    assert observation["skipped_memory_ids"] == [10]


@pytest.mark.asyncio
async def test_mark_used_recalled_memories_is_nonfatal_on_backend_failure():
    memory_client = FakeMemoryClient(fail=True)

    observation = await mark_used_recalled_memories(
        app_state=SimpleNamespace(backend_memory_client=memory_client),
        task_input=_task_input(memory_ids=[10]),
        user_id="7",
        assistant_message="MR 작업내용은 짧게 정리했습니다.",
        task_run_id="task_1",
    )

    assert len(memory_client.calls) == 1
    assert observation["status"] == "failed"
    assert observation["failed"] is True
    assert observation["failed_memory_ids"] == [10]
    assert observation["used_memory_ids"] == []


@pytest.mark.asyncio
async def test_mark_used_recalled_memories_skips_without_memory_client():
    observation = await mark_used_recalled_memories(
        app_state=SimpleNamespace(),
        task_input=_task_input(memory_ids=[10]),
        user_id="7",
        assistant_message="MR 작업내용은 짧게 정리했습니다.",
        task_run_id="task_1",
    )

    assert observation["status"] == "skipped"
    assert observation["reason"] == "memory_client_unavailable"
