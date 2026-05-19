from __future__ import annotations

import pytest

from app.domain.orchestration.agent.memory.memory_extractor import LlmMemoryExtractor, MemoryExtractionContext


class FakeStructuredProvider:
    def __init__(self, payload, *, fail: bool = False):
        self.payload = payload
        self.fail = fail
        self.calls = []

    async def extract_memory_json(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("provider failed")
        return self.payload


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_preference_candidate_for_backend_contract():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "preference",
                    "scopeType": "global",
                    "content": "사용자는 답변을 짧게 받는 것을 선호한다.",
                    "summary": "짧은 답변 선호",
                    "metadata": {"tags": ["style"]},
                    "importance": 0.8,
                    "confidence": 0.9,
                    "evidence": "짧게 답해줘.",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="앞으로는 짧게 답해줘.",
        assistant_message="알겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", task_run_id="task_1", assistant_message_id="msg_2"),
    )

    assert candidates == [
        {
            "memoryType": "PREFERENCE",
            "storeType": "USER_PROFILE",
            "scopeType": "GLOBAL",
            "operationType": "ADD",
            "content": "사용자는 답변을 짧게 받는 것을 선호한다.",
            "metadata": {"source": "ai.writeback", "category": "preference", "sensitivity": "low", "ttl": "long", "tags": ["style"]},
            "importance": 0.8,
            "confidence": 0.9,
            "summary": "짧은 답변 선호",
            "evidence": "짧게 답해줘.",
            "sourceTaskRunId": "task_1",
            "sourceMessageId": "msg_2",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_drops_low_score_candidates():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "content": "불확실한 사실",
                    "importance": 0.8,
                    "confidence": 0.6,
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="아마 그럴 수도 있어.",
        assistant_message="확인했습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_llm_profile_candidate_without_explicit_remember_request():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "profile",
                    "scopeType": "global",
                    "content": "사용자의 이름은 김상지이다.",
                    "summary": "사용자 이름",
                    "metadata": {"category": "profile", "tags": ["name"]},
                    "importance": 0.9,
                    "confidence": 0.95,
                    "evidence": "내 이름은 김상지야",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="내 이름은 김상지야",
        assistant_message="알겠습니다. 앞으로 김상지님이라고 불러드릴까요?",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", task_run_id="task_1", assistant_message_id="msg_2"),
    )

    assert candidates == [
        {
            "memoryType": "PROFILE",
            "storeType": "USER_PROFILE",
            "scopeType": "GLOBAL",
            "operationType": "ADD",
            "content": "사용자의 이름은 김상지이다.",
            "metadata": {"source": "ai.writeback", "category": "profile", "sensitivity": "low", "ttl": "long", "tags": ["name"]},
            "importance": 0.9,
            "confidence": 0.95,
            "summary": "사용자 이름",
            "evidence": "내 이름은 김상지야",
            "sourceTaskRunId": "task_1",
            "sourceMessageId": "msg_2",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_llm_preference_candidate_without_explicit_remember_request():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "preference",
                    "scopeType": "global",
                    "content": "사용자는 국수를 좋아한다.",
                    "summary": "국수 선호",
                    "metadata": {"category": "preference", "tags": ["food"]},
                    "importance": 0.8,
                    "confidence": 0.9,
                    "evidence": "나 국수 좋아해",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="나 국수 좋아해",
        assistant_message="국수도 좋죠.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates[0]["memoryType"] == "PREFERENCE"
    assert candidates[0]["storeType"] == "USER_PROFILE"
    assert candidates[0]["scopeType"] == "GLOBAL"
    assert candidates[0]["content"] == "사용자는 국수를 좋아한다."
    assert candidates[0]["metadata"]["category"] == "preference"


def test_memory_extractor_prompt_distinguishes_current_task_from_completed_event():
    from app.domain.orchestration.agent.memory.memory_extractor import MEMORY_EXTRACTION_SYSTEM_PROMPT

    assert "uncompleted current task request" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "booking, purchase, scheduling" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "assistant or tool result confirms" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "metadata.eventTime" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "metadata.sourceTimestamp" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "one-off research, summarization" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "durable preference or profile fact" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "future-facing assistant instructions" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "reusable multi-step workflows" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "A task request can contain a separable user fact" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "context.requestDate" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "나 오늘 어디 가는 기차 예약해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "이 문서 요약해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "나는 짧은 답변 좋아하니까 이 문서 요약해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "부산 가는 KTX 예약해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "오늘 이 부분 코드 개발해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "The user's request alone is not enough" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "해당 프로젝트의 코드 개발 작업이 완료됐다." in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "오늘 부산 가는 KTX 예약했어" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "나 백엔드 면접 준비중인데 면접 준비 계획서 만들어줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "앞으로 MR 정리할 때 테스트 결과 먼저 써줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "이 프로젝트에서는 항상 기능별 브랜치로 나눠서 작업해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "우리 프로젝트 API 명세서 계속 Notion에 정리해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT
    assert "지난번처럼 docs/logs 작업하고 커밋해줘" in MEMORY_EXTRACTION_SYSTEM_PROMPT


@pytest.mark.asyncio
async def test_memory_extractor_keeps_one_off_document_summary_request_empty():
    provider = FakeStructuredProvider({"candidates": []})
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="이 문서 요약해줘",
        assistant_message="문서를 요약해드릴게요.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_memory_extractor_keeps_uncompleted_booking_request_empty():
    provider = FakeStructuredProvider({"candidates": []})
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="부산 가는 KTX 예약해줘",
        assistant_message="출발일과 시간을 알려주세요.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", request_date="2026-05-16"),
    )

    assert candidates == []
    assert provider.calls[0]["user_message"] == "부산 가는 KTX 예약해줘"


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_preference_embedded_in_task_request_only():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "PREFERENCE",
                    "scopeType": "GLOBAL",
                    "content": "사용자는 짧은 답변을 선호한다.",
                    "summary": "짧은 답변 선호",
                    "metadata": {"category": "preference", "tags": ["style", "brevity"]},
                    "importance": 0.8,
                    "confidence": 0.9,
                    "evidence": "나는 짧은 답변 좋아하니까 이 문서 요약해줘",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="나는 짧은 답변 좋아하니까 이 문서 요약해줘",
        assistant_message="짧게 요약해드릴게요.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates == [
        {
            "memoryType": "PREFERENCE",
            "storeType": "USER_PROFILE",
            "scopeType": "GLOBAL",
            "operationType": "ADD",
            "content": "사용자는 짧은 답변을 선호한다.",
            "metadata": {
                "source": "ai.writeback",
                "category": "preference",
                "sensitivity": "low",
                "ttl": "long",
                "tags": ["style", "brevity"],
            },
            "importance": 0.8,
            "confidence": 0.9,
            "summary": "짧은 답변 선호",
            "evidence": "나는 짧은 답변 좋아하니까 이 문서 요약해줘",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_user_fact_embedded_in_task_request():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "content": "사용자는 2026-05-16 기준 백엔드 면접을 준비 중이다.",
                    "summary": "백엔드 면접 준비 중",
                    "metadata": {
                        "category": "fact",
                        "ttl": "short",
                        "tags": ["interview", "current_state"],
                        "sourceTimestamp": "2026-05-16",
                    },
                    "importance": 0.75,
                    "confidence": 0.9,
                    "evidence": "나 백엔드 면접 준비중인데 면접 준비 계획서 만들어줘",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="나 백엔드 면접 준비중인데 면접 준비 계획서 만들어줘",
        assistant_message="면접 준비 계획을 세워드릴게요.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", request_date="2026-05-16"),
    )

    assert candidates == [
        {
            "memoryType": "FACT",
            "storeType": "AGENT_MEMORY",
            "scopeType": "GLOBAL",
            "operationType": "ADD",
            "content": "사용자는 2026-05-16 기준 백엔드 면접을 준비 중이다.",
            "metadata": {
                "source": "ai.writeback",
                "category": "fact",
                "sensitivity": "low",
                "ttl": "short",
                "tags": ["interview", "current_state"],
                "sourceTimestamp": "2026-05-16T00:00:00",
            },
            "importance": 0.75,
            "confidence": 0.9,
            "summary": "백엔드 면접 준비 중",
            "evidence": "나 백엔드 면접 준비중인데 면접 준비 계획서 만들어줘",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_future_instruction_for_mr_summary():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "INSTRUCTION",
                    "scopeType": "GLOBAL",
                    "content": "MR 정리 시 테스트 결과를 먼저 작성한다.",
                    "summary": "MR 정리 테스트 결과 우선",
                    "metadata": {"category": "instruction", "tags": ["mr", "test_result"]},
                    "importance": 0.75,
                    "confidence": 0.9,
                    "evidence": "앞으로 MR 정리할 때 테스트 결과 먼저 써줘",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="앞으로 MR 정리할 때 테스트 결과 먼저 써줘",
        assistant_message="앞으로 MR 정리에는 테스트 결과를 먼저 쓰겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates == [
        {
            "memoryType": "INSTRUCTION",
            "storeType": "AGENT_MEMORY",
            "scopeType": "GLOBAL",
            "operationType": "ADD",
            "content": "MR 정리 시 테스트 결과를 먼저 작성한다.",
            "metadata": {
                "source": "ai.writeback",
                "category": "instruction",
                "sensitivity": "low",
                "ttl": "long",
                "tags": ["mr", "test_result"],
            },
            "importance": 0.75,
            "confidence": 0.9,
            "summary": "MR 정리 테스트 결과 우선",
            "evidence": "앞으로 MR 정리할 때 테스트 결과 먼저 써줘",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_workspace_branching_procedure():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "PROCEDURE",
                    "scopeType": "WORKSPACE",
                    "content": "이 프로젝트에서는 작업을 기능별 브랜치로 나누어 진행한다.",
                    "summary": "기능별 브랜치 작업 절차",
                    "metadata": {"category": "procedure", "tags": ["branch", "workflow"]},
                    "importance": 0.8,
                    "confidence": 0.9,
                    "evidence": "이 프로젝트에서는 항상 기능별 브랜치로 나눠서 작업해줘",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="이 프로젝트에서는 항상 기능별 브랜치로 나눠서 작업해줘",
        assistant_message="이 프로젝트에서는 기능별 브랜치로 나눠서 작업하겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", workspace_key="workspace-a"),
    )

    assert candidates == [
        {
            "memoryType": "PROCEDURE",
            "storeType": "AGENT_MEMORY",
            "scopeType": "WORKSPACE",
            "operationType": "ADD",
            "content": "이 프로젝트에서는 작업을 기능별 브랜치로 나누어 진행한다.",
            "metadata": {
                "source": "ai.writeback",
                "category": "procedure",
                "sensitivity": "low",
                "ttl": "long",
                "workspaceKey": "workspace-a",
                "tags": ["branch", "workflow"],
            },
            "importance": 0.8,
            "confidence": 0.9,
            "summary": "기능별 브랜치 작업 절차",
            "evidence": "이 프로젝트에서는 항상 기능별 브랜치로 나눠서 작업해줘",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_recurring_notion_api_spec_procedure():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "PROCEDURE",
                    "scopeType": "WORKSPACE",
                    "content": "이 프로젝트의 API 명세서는 계속 Notion에 정리한다.",
                    "summary": "API 명세서 Notion 정리 절차",
                    "metadata": {"category": "procedure", "tags": ["api_spec", "notion", "documentation"]},
                    "importance": 0.8,
                    "confidence": 0.9,
                    "evidence": "우리 프로젝트 API 명세서 계속 Notion에 정리해줘",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="우리 프로젝트 API 명세서 계속 Notion에 정리해줘",
        assistant_message="앞으로 이 프로젝트 API 명세서는 Notion에 계속 정리하겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", workspace_key="workspace-a"),
    )

    assert candidates[0]["memoryType"] == "PROCEDURE"
    assert candidates[0]["storeType"] == "AGENT_MEMORY"
    assert candidates[0]["scopeType"] == "WORKSPACE"
    assert candidates[0]["metadata"]["category"] == "procedure"
    assert candidates[0]["metadata"]["workspaceKey"] == "workspace-a"
    assert candidates[0]["metadata"]["tags"] == ["api_spec", "notion", "documentation"]
    assert candidates[0]["content"] == "이 프로젝트의 API 명세서는 계속 Notion에 정리한다."


@pytest.mark.asyncio
async def test_memory_extractor_keeps_repeat_docs_logs_task_empty_without_new_procedure():
    provider = FakeStructuredProvider({"candidates": []})
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="지난번처럼 docs/logs 작업하고 커밋해줘",
        assistant_message="기존 절차대로 작업하겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", workspace_key="workspace-a"),
    )

    assert candidates == []


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_completed_user_event():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "content": "사용자는 2026-05-16에 부산 가는 KTX를 예약했다.",
                    "summary": "부산 KTX 예약",
                    "metadata": {
                        "category": "event",
                        "ttl": "medium",
                        "tags": ["travel", "train"],
                        "eventTime": "2026-05-16",
                    },
                    "importance": 0.7,
                    "confidence": 0.9,
                    "evidence": "오늘 부산 가는 KTX 예약했어",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="오늘 부산 가는 KTX 예약했어",
        assistant_message="예약해두셨군요.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", request_date="2026-05-16"),
    )

    assert candidates[0]["memoryType"] == "FACT"
    assert candidates[0]["storeType"] == "AGENT_MEMORY"
    assert candidates[0]["metadata"]["category"] == "event"
    assert candidates[0]["metadata"]["ttl"] == "medium"
    assert candidates[0]["metadata"]["eventTime"] == "2026-05-16T00:00:00"
    assert candidates[0]["metadata"]["tags"] == ["travel", "train"]


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_confirmed_booking_tool_result_as_event():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "content": "사용자는 2026-05-20 09:00 서울역 출발 부산행 KTX를 예약했다.",
                    "summary": "부산행 KTX 예약 완료",
                    "metadata": {
                        "category": "event",
                        "ttl": "short",
                        "tags": ["travel", "train", "booking"],
                        "eventTime": "2026-05-20T09:00:00",
                        "sourceTimestamp": "2026-05-16T15:30:00",
                    },
                    "expiresAt": "2026-05-20T12:00:00",
                    "importance": 0.75,
                    "confidence": 0.92,
                    "evidence": "2026-05-20 09:00 서울역 출발 부산행 KTX 예약이 완료됐습니다.",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="부산 가는 KTX 예약해줘",
        assistant_message="2026-05-20 09:00 서울역 출발 부산행 KTX 예약이 완료됐습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", request_date="2026-05-16"),
    )

    assert candidates == [
        {
            "memoryType": "FACT",
            "storeType": "AGENT_MEMORY",
            "scopeType": "GLOBAL",
            "operationType": "ADD",
            "content": "사용자는 2026-05-20 09:00 서울역 출발 부산행 KTX를 예약했다.",
            "metadata": {
                "source": "ai.writeback",
                "category": "event",
                "sensitivity": "low",
                "ttl": "short",
                "tags": ["travel", "train", "booking"],
                "sourceTimestamp": "2026-05-16T15:30:00",
                "eventTime": "2026-05-20T09:00:00",
            },
            "importance": 0.75,
            "confidence": 0.92,
            "summary": "부산행 KTX 예약 완료",
            "evidence": "2026-05-20 09:00 서울역 출발 부산행 KTX 예약이 완료됐습니다.",
            "expiresAt": "2026-05-20T12:00:00",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_completed_project_code_work():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "WORKSPACE",
                    "content": "2026-05-16에 장기기억 fact/event 저장 고도화 코드 개발 작업이 완료됐다.",
                    "summary": "장기기억 fact/event 저장 고도화 완료",
                    "metadata": {
                        "category": "task_state",
                        "ttl": "medium",
                        "tags": ["memory", "fact_event", "implementation"],
                        "eventTime": "2026-05-16",
                    },
                    "importance": 0.8,
                    "confidence": 0.9,
                    "evidence": "구현했고 테스트도 통과했습니다.",
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="오늘 이 부분 코드 개발해줘",
        assistant_message="구현했고 테스트도 통과했습니다.",
        context=MemoryExtractionContext(
            user_id="1",
            session_id="session_1",
            workspace_key="workspace-a",
            request_date="2026-05-16",
        ),
    )

    assert candidates == [
        {
            "memoryType": "FACT",
            "storeType": "AGENT_MEMORY",
            "scopeType": "WORKSPACE",
            "operationType": "ADD",
            "content": "2026-05-16에 장기기억 fact/event 저장 고도화 코드 개발 작업이 완료됐다.",
            "metadata": {
                "source": "ai.writeback",
                "category": "task_state",
                "sensitivity": "low",
                "ttl": "medium",
                "workspaceKey": "workspace-a",
                "tags": ["memory", "fact_event", "implementation"],
                "eventTime": "2026-05-16T00:00:00",
            },
            "importance": 0.8,
            "confidence": 0.9,
            "summary": "장기기억 fact/event 저장 고도화 완료",
            "evidence": "구현했고 테스트도 통과했습니다.",
        }
    ]


@pytest.mark.asyncio
async def test_memory_extractor_reraises_provider_failure_without_rule_fallback_storage():
    provider = FakeStructuredProvider({"candidates": []}, fail=True)
    extractor = LlmMemoryExtractor(provider=provider)

    with pytest.raises(RuntimeError, match="provider failed"):
        await extractor.extract_candidates(
            user_message="나 국수 좋아해",
            assistant_message="답변입니다.",
            context=MemoryExtractionContext(user_id="1", session_id="session_1"),
        )


@pytest.mark.asyncio
async def test_memory_extractor_requires_workspace_key_for_workspace_scope():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "INSTRUCTION",
                    "scopeType": "WORKSPACE",
                    "content": "이 프로젝트에서는 PR 요약을 한국어로 작성한다.",
                    "importance": 0.7,
                    "confidence": 0.9,
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    without_workspace = await extractor.extract_candidates(
        user_message="이 프로젝트에서는 PR 요약을 한국어로 작성해.",
        assistant_message="알겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )
    with_workspace = await extractor.extract_candidates(
        user_message="이 프로젝트에서는 PR 요약을 한국어로 작성해.",
        assistant_message="알겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", workspace_key="workspace-a"),
    )

    assert without_workspace == []
    assert with_workspace[0]["storeType"] == "AGENT_MEMORY"
    assert with_workspace[0]["metadata"]["workspaceKey"] == "workspace-a"
    assert with_workspace[0]["metadata"]["category"] == "instruction"


@pytest.mark.asyncio
async def test_memory_extractor_preserves_event_reason_task_state_categories():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "WORKSPACE",
                    "content": "장기기억 구현은 operation reconciliation 이후 candidate 분류 작업이 남아 있다.",
                    "summary": "장기기억 구현 task state",
                    "metadata": {"category": "task-state", "tags": ["memory", "implementation"]},
                    "importance": 0.8,
                    "confidence": 0.9,
                },
                {
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "content": "사용자가 Jira 형식 변경을 요청한 이유는 발표와 협업 정리를 쉽게 하기 위해서다.",
                    "summary": "Jira 형식 변경 이유",
                    "category": "reason",
                    "importance": 0.7,
                    "confidence": 0.85,
                },
                {
                    "memoryType": "FACT",
                    "scopeType": "WORKSPACE",
                    "content": "IoT 3D 모델링은 1차 초안 후 부품 테스트를 거쳐 고도화하기로 했다.",
                    "summary": "IoT 모델링 진행 이벤트",
                    "memoryCategory": "event",
                    "importance": 0.75,
                    "confidence": 0.9,
                },
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="장기기억 작업 상태와 Jira 이유, IoT 진행 이벤트를 기억해줘.",
        assistant_message="정리했습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", workspace_key="workspace-a"),
    )

    assert [candidate["metadata"]["category"] for candidate in candidates] == ["task_state", "reason", "event"]
    assert candidates[0]["metadata"]["tags"] == ["memory", "implementation"]
    assert candidates[0]["metadata"]["workspaceKey"] == "workspace-a"
    assert candidates[2]["metadata"]["workspaceKey"] == "workspace-a"


@pytest.mark.asyncio
async def test_memory_extractor_normalizes_sensitivity_ttl_and_validity_metadata():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "WORKSPACE",
                    "content": "IoT 모델링 초안은 2026년 5월 20일까지 유효한 1차 시연 기준이다.",
                    "summary": "IoT 모델링 1차 시연 기준",
                    "validFrom": "2026-05-11",
                    "validUntil": "2026-05-20T18:00:00+09:00",
                    "expiresAt": "2026-06-01T00:00:00",
                    "metadata": {
                        "category": "event",
                        "sensitivity": "MEDIUM",
                        "ttl": "short",
                        "sourceTimestamp": "2026-05-11T10:30:00+09:00",
                        "eventTime": "2026-05-20T15:00:00",
                        "reason": "발표 시연 기준을 명확히 하기 위해 저장한다.",
                    },
                    "importance": 0.8,
                    "confidence": 0.9,
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="IoT 모델링 초안 시연 기준을 기억해줘.",
        assistant_message="정리했습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1", workspace_key="workspace-a"),
    )

    candidate = candidates[0]
    assert candidate["validFrom"] == "2026-05-11T00:00:00"
    assert candidate["validUntil"] == "2026-05-20T18:00:00"
    assert candidate["expiresAt"] == "2026-06-01T00:00:00"
    assert candidate["metadata"] == {
        "source": "ai.writeback",
        "category": "event",
        "sensitivity": "medium",
        "ttl": "short",
        "workspaceKey": "workspace-a",
        "sourceTimestamp": "2026-05-11T10:30:00",
        "eventTime": "2026-05-20T15:00:00",
        "reason": "발표 시연 기준을 명확히 하기 위해 저장한다.",
    }


@pytest.mark.asyncio
async def test_memory_extractor_ignores_invalid_validity_metadata_and_defaults_ttl():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "content": "장기기억 구현 task state는 metadata 고도화 단계다.",
                    "metadata": {
                        "category": "task_state",
                        "sensitivity": "unknown",
                        "ttl": "forever",
                        "sourceTimestamp": "어제",
                    },
                    "validFrom": "다음 주",
                    "importance": 0.8,
                    "confidence": 0.9,
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="장기기억 구현 상태를 기억해줘.",
        assistant_message="정리했습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    candidate = candidates[0]
    assert "validFrom" not in candidate
    assert "sourceTimestamp" not in candidate["metadata"]
    assert candidate["metadata"]["sensitivity"] == "low"
    assert candidate["metadata"]["ttl"] == "medium"


@pytest.mark.asyncio
async def test_memory_extractor_does_not_call_llm_when_user_denies_storage():
    provider = FakeStructuredProvider({"candidates": [{"memoryType": "FACT", "content": "x", "importance": 1, "confidence": 1}]})
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="이 내용은 저장하지 마.",
        assistant_message="알겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates == []
    assert provider.calls == []


@pytest.mark.asyncio
async def test_memory_extractor_allows_security_policy_without_secret_value():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "INSTRUCTION",
                    "scopeType": "GLOBAL",
                    "content": "이 프로젝트에서는 access token을 task input에 넣지 않는다.",
                    "importance": 0.8,
                    "confidence": 0.9,
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="앞으로 access token은 task input에 넣지 않는 걸 기억해줘.",
        assistant_message="알겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates[0]["content"] == "이 프로젝트에서는 access token을 task input에 넣지 않는다."


@pytest.mark.asyncio
async def test_memory_extractor_drops_secret_value_candidates():
    provider = FakeStructuredProvider(
        {
            "candidates": [
                {
                    "memoryType": "FACT",
                    "scopeType": "GLOBAL",
                    "content": "사용자의 access_token=abcdef1234567890",
                    "importance": 0.8,
                    "confidence": 0.9,
                }
            ]
        }
    )
    extractor = LlmMemoryExtractor(provider=provider)

    candidates = await extractor.extract_candidates(
        user_message="기억해줘.",
        assistant_message="알겠습니다.",
        context=MemoryExtractionContext(user_id="1", session_id="session_1"),
    )

    assert candidates == []
