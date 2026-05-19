from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Protocol

from app.clients.backend_memory import BackendMemoryClientError

logger = logging.getLogger(__name__)


MEMORY_OPERATION_RECONCILIATION_SYSTEM_PROMPT = """
You decide how a new long-term memory candidate should be reconciled with existing memories.
Return strict JSON only, with this shape:
{"operationType":"ADD|UPDATE|MERGE|INVALIDATE","targetMemoryId":123|null,"additionalTargetMemoryIds":[456,789],"reason":"short Korean reason"}

Rules:
- Use ADD when the candidate is genuinely new and does not replace or refine an existing memory.
- Use UPDATE when the candidate changes the current value of an existing preference, profile, or instruction.
- Use MERGE when the candidate adds compatible detail to an existing memory without replacing it.
- Use INVALIDATE when the user says an existing memory is no longer true or should be forgotten.
- Choose targetMemoryId only from the provided existingMemories.
- Use additionalTargetMemoryIds for other provided memories that also conflict with, are replaced by, or should be superseded by the same new candidate.
- If operationType is UPDATE, MERGE, or INVALIDATE, targetMemoryId is required.
- Do not infer from keyword rules alone. Compare the candidate meaning, the user message, and existing memories.
- Prefer the user's most recent explicit statement when preferences conflict.
- If uncertain, return ADD with targetMemoryId null.
""".strip()


class MemoryRecallClient(Protocol):
    async def recall(
        self,
        *,
        user_id: str,
        query: str | None = None,
        limit: int = 5,
        workspace_key: str | None = None,
        store_type: str | None = None,
        memory_type: str | None = None,
        scope_type: str | None = None,
        resource_id: str | None = None,
        tags: list[str] | None = None,
        metadata_categories: list[str] | None = None,
    ) -> list[Any]:
        """Return recalled memories from backend."""


class MemoryOperationDecisionProvider(Protocol):
    async def reconcile_memory_operation_json(
        self,
        *,
        system_prompt: str,
        user_message: str,
        candidate: dict[str, Any],
        existing_memories: list[dict[str, Any]],
        context: "MemoryReconciliationContext",
    ) -> dict[str, Any]:
        """Return model-produced operation reconciliation JSON."""


@dataclass(slots=True)
class MemoryReconciliationContext:
    user_id: str
    user_message: str
    workspace_key: str | None = None
    session_id: str | None = None
    task_run_id: str | None = None
    step_run_id: str | None = None
    provider_name: str | None = None
    model: str | None = None


class MemoryOperationReconciler:
    """기존 장기기억과 새 후보를 비교해 backend operation payload를 보강한다."""

    def __init__(
        self,
        memory_client: MemoryRecallClient,
        *,
        operation_provider: MemoryOperationDecisionProvider | None = None,
        recall_limit: int = 5,
    ) -> None:
        self._memory_client = memory_client
        self._operation_provider = operation_provider
        self._recall_limit = max(1, min(recall_limit, 10))

    async def reconcile_candidates(
        self,
        *,
        candidates: list[dict[str, Any]],
        context: MemoryReconciliationContext,
    ) -> list[dict[str, Any]]:
        reconciled: list[dict[str, Any]] = []
        for candidate in candidates:
            reconciled.append(await self._reconcile_candidate(candidate, context=context))
        return reconciled

    async def _reconcile_candidate(
        self,
        candidate: dict[str, Any],
        *,
        context: MemoryReconciliationContext,
    ) -> dict[str, Any]:
        current_operation = _operation(candidate.get("operationType"))
        if current_operation != "ADD":
            return dict(candidate)

        query = _recall_query(candidate)
        if not query:
            return dict(candidate)

        try:
            recall_kwargs = {
                "user_id": context.user_id,
                "query": query,
                "limit": self._recall_limit,
                "workspace_key": context.workspace_key if candidate.get("scopeType") == "WORKSPACE" else None,
                "store_type": _string(candidate.get("storeType")),
                "memory_type": _string(candidate.get("memoryType")),
                "scope_type": _string(candidate.get("scopeType")),
                "tags": _tags(candidate),
            }
            memories = await self._memory_client.recall(**recall_kwargs)
            if not memories and _should_retry_recall_by_filter(candidate):
                filter_recall_kwargs = dict(recall_kwargs)
                filter_recall_kwargs["query"] = None
                if not filter_recall_kwargs.get("tags"):
                    filter_recall_kwargs["metadata_categories"] = _metadata_categories(candidate)
                memories = await self._memory_client.recall(**filter_recall_kwargs)
        except BackendMemoryClientError:
            logger.warning("장기기억 operation 판단용 recall에 실패했습니다.", exc_info=True)
            return dict(candidate)
        except Exception:
            logger.warning("장기기억 operation 판단 중 예기치 않은 recall 오류가 발생했습니다.", exc_info=True)
            return dict(candidate)

        target = _best_related_memory(candidate, memories)
        if target is None:
            return dict(candidate)

        llm_decision = await self._decide_with_llm(candidate, memories=memories, context=context)
        if llm_decision is not None:
            return llm_decision

        return _apply_heuristic_decision(candidate, target, user_message=context.user_message)

    async def _decide_with_llm(
        self,
        candidate: dict[str, Any],
        *,
        memories: list[Any],
        context: MemoryReconciliationContext,
    ) -> dict[str, Any] | None:
        if self._operation_provider is None:
            return None
        memory_items = [_memory_item_payload(memory) for memory in memories if _same_contract(candidate, memory)]
        if not memory_items:
            return None
        try:
            decision = await self._operation_provider.reconcile_memory_operation_json(
                system_prompt=MEMORY_OPERATION_RECONCILIATION_SYSTEM_PROMPT,
                user_message=context.user_message,
                candidate=candidate,
                existing_memories=memory_items,
                context=context,
            )
        except Exception:
            logger.warning("LLM 장기기억 operation 판단에 실패했습니다.", exc_info=True)
            return None
        return _apply_llm_decision(candidate, memories=memories, decision=decision)


def _recall_query(candidate: dict[str, Any]) -> str | None:
    for key in ("summary", "content", "evidence"):
        value = _string(candidate.get(key))
        if value:
            return value
    return None


def _best_related_memory(candidate: dict[str, Any], memories: list[Any]) -> Any | None:
    candidate_content = _string(candidate.get("content")) or ""
    candidate_summary = _string(candidate.get("summary")) or ""
    candidate_text = f"{candidate_summary} {candidate_content}".strip()
    candidate_tokens = _tokens(candidate_text)
    candidate_tags = _metadata_tags(candidate.get("metadata"))
    candidate_category = _metadata_category(candidate.get("metadata"))

    best_memory: Any | None = None
    best_score = 0.0
    for memory in memories:
        if not _same_contract(candidate, memory):
            continue
        memory_text = f"{getattr(memory, 'summary', '') or ''} {getattr(memory, 'content', '') or ''}".strip()
        score = _similarity(candidate_tokens, _tokens(memory_text)) + _metadata_similarity(
            candidate_tags,
            candidate_category,
            _metadata_tags(getattr(memory, "metadata", None)),
            _metadata_category(getattr(memory, "metadata", None)),
        )
        if score > best_score:
            best_score = score
            best_memory = memory

    if best_memory is None or best_score < 0.2:
        return None
    return best_memory


def _same_contract(candidate: dict[str, Any], memory: Any) -> bool:
    return (
        _string(candidate.get("memoryType")) == getattr(memory, "memory_type", None)
        and _string(candidate.get("storeType")) == getattr(memory, "store_type", None)
        and _string(candidate.get("scopeType")) == getattr(memory, "scope_type", None)
    )


def _decide_operation(candidate: dict[str, Any], memory: Any, *, user_message: str) -> str:
    candidate_content = _normalize_text(_string(candidate.get("content")) or "")
    memory_content = _normalize_text(getattr(memory, "content", "") or "")
    if candidate_content and candidate_content == memory_content:
        return "ADD"

    user_text = _normalize_text(user_message)
    if _has_update_signal(user_text):
        return "UPDATE"
    if _has_invalidation_signal(user_text):
        return "INVALIDATE"
    if _has_merge_signal(user_text):
        return "MERGE"

    memory_type = _string(candidate.get("memoryType"))
    if memory_type in {"PREFERENCE", "PROFILE", "INSTRUCTION"}:
        return "UPDATE"
    return "MERGE"


def _apply_llm_decision(candidate: dict[str, Any], *, memories: list[Any], decision: Any) -> dict[str, Any] | None:
    if not isinstance(decision, dict):
        return None
    operation = _operation(decision.get("operationType", decision.get("operation_type")))
    if operation == "ADD":
        return dict(candidate)

    target = _target_memory_from_decision(decision, memories=memories)
    if target is None or not _same_contract(candidate, target):
        return None

    result = dict(candidate)
    result["operationType"] = operation
    result["targetMemoryId"] = getattr(target, "id")
    additional_target_ids = _additional_target_ids_from_decision(decision, memories=memories, primary_target_id=getattr(target, "id"))
    if additional_target_ids:
        result["additionalTargetMemoryIds"] = additional_target_ids
    reason = _string(decision.get("reason")) or _update_reason(operation, candidate, target, "")
    result["updateReason"] = _trim(reason)
    return result


def _apply_heuristic_decision(candidate: dict[str, Any], memory: Any, *, user_message: str) -> dict[str, Any]:
    operation = _decide_operation(candidate, memory, user_message=user_message)
    if operation == "ADD":
        return dict(candidate)

    result = dict(candidate)
    result["operationType"] = operation
    result["targetMemoryId"] = getattr(memory, "id")
    result["updateReason"] = _update_reason(operation, candidate, memory, user_message)
    return result


def _additional_target_ids_from_decision(
    decision: dict[str, Any],
    *,
    memories: list[Any],
    primary_target_id: Any,
) -> list[int]:
    raw_ids = decision.get("additionalTargetMemoryIds", decision.get("additional_target_memory_ids"))
    if not isinstance(raw_ids, list):
        return []
    valid_ids = {
        int(getattr(memory, "id"))
        for memory in memories
        if isinstance(getattr(memory, "id", None), int)
    }
    result: list[int] = []
    try:
        normalized_primary_target_id = int(primary_target_id)
    except (TypeError, ValueError):
        normalized_primary_target_id = None
    for raw_id in raw_ids:
        try:
            memory_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if memory_id == normalized_primary_target_id or memory_id not in valid_ids or memory_id in result:
            continue
        result.append(memory_id)
    return result


def _target_memory_from_decision(decision: dict[str, Any], *, memories: list[Any]) -> Any | None:
    target_id = decision.get("targetMemoryId", decision.get("target_memory_id"))
    try:
        normalized_target_id = int(target_id)
    except (TypeError, ValueError):
        return None
    for memory in memories:
        if getattr(memory, "id", None) == normalized_target_id:
            return memory
    return None


def _has_update_signal(text: str) -> bool:
    return any(signal in text for signal in _UPDATE_SIGNALS)


def _has_merge_signal(text: str) -> bool:
    return any(signal in text for signal in _MERGE_SIGNALS)


def _has_invalidation_signal(text: str) -> bool:
    return any(signal in text for signal in _INVALIDATE_SIGNALS)


def _update_reason(operation: str, candidate: dict[str, Any], memory: Any, user_message: str) -> str:
    summary = _string(candidate.get("summary")) or _string(candidate.get("content")) or "장기기억 후보"
    old_summary = getattr(memory, "summary", None) or getattr(memory, "content", "") or "기존 기억"
    if operation == "UPDATE":
        return _trim(f"사용자 발화를 기준으로 기존 기억('{old_summary}')을 새 후보('{summary}')로 갱신함")
    if operation == "MERGE":
        return _trim(f"사용자 발화에서 기존 기억('{old_summary}')에 보완 정보('{summary}')가 추가됨")
    if operation == "INVALIDATE":
        return _trim(f"사용자 발화에서 기존 기억('{old_summary}')이 더 이상 유효하지 않음을 확인함")
    return _trim(f"사용자 발화 기반 operation 판단: {user_message}")


def _tags(candidate: dict[str, Any]) -> list[str] | None:
    metadata = candidate.get("metadata")
    if not isinstance(metadata, dict):
        return None
    tags = metadata.get("tags")
    if not isinstance(tags, list):
        return None
    result = [tag for tag in (_string(tag) for tag in tags) if tag]
    return result or None


def _metadata_categories(candidate: dict[str, Any]) -> list[str] | None:
    category = _metadata_category(candidate.get("metadata"))
    return [category] if category else None


def _should_retry_recall_by_filter(candidate: dict[str, Any]) -> bool:
    memory_type = _string(candidate.get("memoryType"))
    store_type = _string(candidate.get("storeType"))
    has_metadata_filter = bool(_tags(candidate) or _metadata_categories(candidate))
    return memory_type in {"PREFERENCE", "PROFILE", "INSTRUCTION"} and store_type == "USER_PROFILE" and has_metadata_filter


def _memory_item_payload(memory: Any) -> dict[str, Any]:
    return {
        "id": getattr(memory, "id", None),
        "memoryType": getattr(memory, "memory_type", None),
        "storeType": getattr(memory, "store_type", None),
        "scopeType": getattr(memory, "scope_type", None),
        "summary": getattr(memory, "summary", None),
        "content": getattr(memory, "content", None),
        "metadata": getattr(memory, "metadata", None) or {},
    }


def _operation(value: Any) -> str:
    text = _string(value)
    return text if text in {"ADD", "UPDATE", "MERGE", "INVALIDATE"} else "ADD"


def _string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _tokens(text: str) -> set[str]:
    normalized = _normalize_text(text)
    tokens = set(re.findall(r"[0-9A-Za-z가-힣_]{2,}", normalized))
    tags = set(re.findall(r"\[[^\]]+\]", normalized))
    return tokens | tags


def _similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _metadata_similarity(
    candidate_tags: set[str],
    candidate_category: str | None,
    memory_tags: set[str],
    memory_category: str | None,
) -> float:
    score = 0.0
    tag_score = _similarity(candidate_tags, memory_tags)
    if tag_score > 0:
        score += min(0.25, 0.15 + tag_score * 0.2)
    if candidate_category and candidate_category == memory_category:
        score += 0.1
    return score


def _metadata_tags(metadata: Any) -> set[str]:
    if not isinstance(metadata, dict):
        return set()
    tags = metadata.get("tags")
    if not isinstance(tags, list):
        return set()
    return {
        tag
        for tag in (_normalize_metadata_token(tag) for tag in tags)
        if tag and tag not in _GENERIC_METADATA_TAGS
    }


def _metadata_category(metadata: Any) -> str | None:
    if not isinstance(metadata, dict):
        return None
    return _normalize_metadata_token(metadata.get("category"))


def _normalize_metadata_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().lower()
    return text or None


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _trim(text: str) -> str:
    return text[:500]


_UPDATE_SIGNALS = (
    "앞으로",
    "이제",
    "대신",
    "바꿔",
    "변경",
    "수정",
    "더 이상",
    "요즘",
    "최근",
    "보다",
    "더 좋아",
    "우선",
    "우선해",
    "from now on",
    "instead",
    "change",
    "update",
)
_MERGE_SIGNALS = (
    "추가",
    "그리고",
    "또",
    "포함",
    "also",
    "additionally",
    "include",
)
_INVALIDATE_SIGNALS = (
    "더 이상 아니",
    "이제 아니",
    "취소",
    "무효",
    "not valid",
    "no longer",
)
_GENERIC_METADATA_TAGS = {
    "preference",
    "profile",
    "instruction",
    "user_profile",
    "ai.writeback",
}
