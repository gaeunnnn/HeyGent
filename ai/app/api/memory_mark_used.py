from __future__ import annotations

import logging
import re
import asyncio
import time
from dataclasses import dataclass
from typing import Any, Protocol

from app.api.memory_observation import MEMORY_CONTEXT_META_KEY
from app.clients.backend_memory import BackendMemoryClientError
from app.domain.orchestration.agent.memory.provider_retry import memory_provider_error_details
from app.domain.orchestration.agent.memory.runtime_context import memory_provider_runtime_context_from_task_input

logger = logging.getLogger(__name__)

_MIN_OVERLAP_TOKENS = 2
_MIN_LLM_USEFULNESS_SCORE = 0.5
_DEFAULT_USEFULNESS_SCORE = 0.6
_MAX_USEFULNESS_SCORE = 0.95
_DEFAULT_ATTRIBUTION_TIMEOUT_SECONDS = 3.0
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9가-힣]{2,}")
_MEMORY_BLOCK_PATTERN = re.compile(r"(?ms)^- id: (?P<id>\d+)\n(?P<body>.*?)(?=^- id: |\Z)")
_FIELD_PATTERN = re.compile(r"(?m)^  (?P<key>type|summary|content): (?P<value>.+)$")
_ATTRIBUTION_QUERY_KEYS = ("prompt", "message", "query", "content", "text", "subject", "title")
_STOPWORDS = {
    "사용자는",
    "사용자",
    "요청",
    "작업",
    "정리",
    "내용",
    "합니다",
    "있습니다",
    "그리고",
    "the",
    "and",
    "for",
    "with",
}

MEMORY_USAGE_ATTRIBUTION_SYSTEM_PROMPT = """
You decide which recalled long-term memories were actually used in the assistant answer.
Return strict JSON only, with this shape:
{"usedMemories":[{"memoryId":10,"usefulnessScore":0.0-1.0,"reason":"..."}]}

Rules:
- Mark a memory used only when the assistant answer reflects information from that memory.
- Do not mark a memory used only because it was recalled.
- Prefer no attribution over weak attribution.
- Use usefulnessScore >= 0.5 only for clearly useful memories.
- Consider semantic use, not just exact word overlap.
- Return only memory ids from recalledMemories.
""".strip()


@dataclass(frozen=True, slots=True)
class _RecalledMemoryText:
    memory_id: int
    memory_type: str
    summary: str
    content: str


class MemoryUsageAttributionProvider(Protocol):
    async def verify_memory_usage_json(
        self,
        *,
        system_prompt: str,
        user_query: str,
        assistant_message: str,
        recalled_memories: list[dict[str, Any]],
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return model-produced memory usage attribution JSON."""


@dataclass(frozen=True, slots=True)
class _AttributionResult:
    scores: dict[int, float]
    reasons: dict[int, str]
    source: str
    failed: bool = False
    fallback_reason: str | None = None
    latency_ms: int | None = None
    error_details: dict[str, Any] | None = None


class LlmMemoryUsageAttributionVerifier:
    """LLM이 답변에 실제 반영된 recalled memory를 구조화해 검증한다."""

    def __init__(
        self,
        provider: MemoryUsageAttributionProvider,
        *,
        timeout_seconds: float = _DEFAULT_ATTRIBUTION_TIMEOUT_SECONDS,
    ) -> None:
        self._provider = provider
        self._timeout_seconds = max(0.001, float(timeout_seconds))

    async def verify_usage(
        self,
        *,
        user_query: str,
        assistant_message: str,
        recalled_memories: list[_RecalledMemoryText],
        runtime_context: dict[str, Any] | None = None,
    ) -> _AttributionResult:
        started_at = time.perf_counter()
        try:
            raw = await asyncio.wait_for(
                self._provider.verify_memory_usage_json(
                    system_prompt=MEMORY_USAGE_ATTRIBUTION_SYSTEM_PROMPT,
                    user_query=user_query,
                    assistant_message=assistant_message,
                    recalled_memories=[_memory_text_payload(memory) for memory in recalled_memories],
                    runtime_context=runtime_context,
                ),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError:
            latency_ms = _elapsed_ms(started_at)
            logger.warning("LLM memory usage attribution timed out; falling back to heuristic", exc_info=True)
            return _AttributionResult(
                scores={},
                reasons={},
                source="llm",
                failed=True,
                fallback_reason="llm_attribution_timeout",
                latency_ms=latency_ms,
                error_details=_memory_provider_meta(self._provider),
            )
        except Exception as exc:
            latency_ms = _elapsed_ms(started_at)
            logger.warning("LLM memory usage attribution failed; falling back to heuristic", exc_info=True)
            error_details = memory_provider_error_details(exc)
            return _AttributionResult(
                scores={},
                reasons={},
                source="llm",
                failed=True,
                fallback_reason=_llm_attribution_fallback_reason(exc, error_details),
                latency_ms=latency_ms,
                error_details=error_details,
            )
        return _normalize_llm_attribution(
            raw,
            recalled_ids=[memory.memory_id for memory in recalled_memories],
            latency_ms=_elapsed_ms(started_at),
        )


async def mark_used_recalled_memories(
    *,
    app_state: Any,
    task_input: dict[str, Any] | None,
    user_id: str,
    assistant_message: str | None,
    task_run_id: str | None = None,
) -> dict[str, Any]:
    """응답에 실제 반영된 것으로 보이는 recalled memory를 backend에 markUsed한다.

    1차 구현은 deterministic heuristic attribution을 사용한다. 실패해도 agent
    응답 저장 흐름을 깨지 않게 observation만 남긴다.
    """

    input_payload = dict(task_input or {})
    answer = str(assistant_message or "").strip()
    recalled_ids = _recalled_memory_ids(input_payload)
    if not recalled_ids:
        return _skipped("no_recalled_memories", task_run_id=task_run_id)
    if not answer:
        return _skipped("assistant_message_unavailable", task_run_id=task_run_id, recalled_ids=recalled_ids)

    memory_client = getattr(app_state, "backend_memory_client", None)
    if memory_client is None:
        return _skipped("memory_client_unavailable", task_run_id=task_run_id, recalled_ids=recalled_ids)

    memory_texts = _memory_texts_by_id(input_payload)
    heuristic_attributions = _attribute_used_memories(
        recalled_ids=recalled_ids,
        memory_texts=memory_texts,
        assistant_message=answer,
    )
    llm_result = await _verify_used_memories_with_llm(
        app_state=app_state,
        input_payload=input_payload,
        user_id=user_id,
        task_run_id=task_run_id,
        assistant_message=answer,
        recalled_ids=recalled_ids,
        memory_texts=memory_texts,
    )
    attributions = _merge_attributions(heuristic_attributions, llm_result.scores)
    if not attributions:
        observation = {
            "status": "skipped",
            "reason": "no_memory_attribution",
            "attempted": False,
            "recalled_memory_ids": recalled_ids,
            "used_memory_ids": [],
            "skipped_memory_ids": recalled_ids,
            "scores": {},
            "deduplicated": len(recalled_ids) != len(_raw_recalled_memory_ids(input_payload)),
            "task_run_id_present": bool(str(task_run_id or "").strip()),
        }
        _put_attribution_meta(observation, heuristic_attributions, llm_result)
        return observation

    used_ids: list[int] = []
    failed_ids: list[int] = []
    scores: dict[str, float] = {}
    for memory_id, score in attributions.items():
        try:
            await memory_client.mark_used(
                user_id=str(user_id),
                memory_id=memory_id,
                usefulness_score=score,
                source_task_run_id=str(task_run_id or "").strip() or None,
            )
        except BackendMemoryClientError:
            logger.warning("backend memory markUsed failed; continuing task completion", exc_info=True)
            failed_ids.append(memory_id)
            continue
        used_ids.append(memory_id)
        scores[str(memory_id)] = score

    skipped_ids = [memory_id for memory_id in recalled_ids if memory_id not in used_ids]
    status = "completed" if used_ids and not failed_ids else "partial" if used_ids else "failed"
    observation = {
        "status": status,
        "reason": _attribution_reason(heuristic_attributions, llm_result),
        "attempted": True,
        "recalled_memory_ids": recalled_ids,
        "used_memory_ids": used_ids,
        "skipped_memory_ids": skipped_ids,
        "failed_memory_ids": failed_ids,
        "scores": scores,
        "deduplicated": len(recalled_ids) != len(_raw_recalled_memory_ids(input_payload)),
        "task_run_id_present": bool(str(task_run_id or "").strip()),
        "failed": bool(failed_ids),
    }
    _put_attribution_meta(observation, heuristic_attributions, llm_result)
    return observation


def _attribute_used_memories(
    *,
    recalled_ids: list[int],
    memory_texts: dict[int, _RecalledMemoryText],
    assistant_message: str,
) -> dict[int, float]:
    answer_tokens = _tokens(assistant_message)
    if not answer_tokens:
        return {}

    attributions: dict[int, float] = {}
    for memory_id in recalled_ids:
        memory_text = memory_texts.get(memory_id)
        if memory_text is None:
            continue
        source_text = f"{memory_text.summary} {memory_text.content}".strip()
        source_tokens = _tokens(source_text)
        overlap = source_tokens.intersection(answer_tokens)
        if _is_instruction_or_procedure(memory_text):
            if not _has_direct_phrase(source_text, assistant_message):
                continue
            score = _DEFAULT_USEFULNESS_SCORE
            attributions[memory_id] = round(score, 2)
            continue
        if len(overlap) < _MIN_OVERLAP_TOKENS and not _has_direct_phrase(source_text, assistant_message):
            continue
        score = min(_MAX_USEFULNESS_SCORE, _DEFAULT_USEFULNESS_SCORE + len(overlap) * 0.05)
        attributions[memory_id] = round(score, 2)
    return attributions


def _is_instruction_or_procedure(memory_text: _RecalledMemoryText) -> bool:
    return str(memory_text.memory_type or "").strip().upper() in {"INSTRUCTION", "PROCEDURE"}


async def _verify_used_memories_with_llm(
    *,
    app_state: Any,
    input_payload: dict[str, Any],
    user_id: str,
    task_run_id: str | None,
    assistant_message: str,
    recalled_ids: list[int],
    memory_texts: dict[int, _RecalledMemoryText],
) -> _AttributionResult:
    verifier = getattr(app_state, "memory_usage_attribution_verifier", None)
    if verifier is None:
        return _AttributionResult(scores={}, reasons={}, source="unavailable")

    recalled_memories = [memory_texts[memory_id] for memory_id in recalled_ids if memory_id in memory_texts]
    if not recalled_memories:
        return _AttributionResult(scores={}, reasons={}, source="llm", fallback_reason="memory_text_unavailable")

    user_query = _attribution_user_query(input_payload)
    return await verifier.verify_usage(
        user_query=user_query,
        assistant_message=assistant_message,
        recalled_memories=recalled_memories,
        runtime_context=memory_provider_runtime_context_from_task_input(
            input_payload,
            user_id=user_id,
            task_run_id=task_run_id,
        ),
    )


def _normalize_llm_attribution(
    raw: Any,
    *,
    recalled_ids: list[int],
    latency_ms: int,
) -> _AttributionResult:
    if not isinstance(raw, dict):
        return _AttributionResult(
            scores={},
            reasons={},
            source="llm",
            failed=True,
            fallback_reason="invalid_llm_attribution_response",
            latency_ms=latency_ms,
        )
    allowed_ids = set(recalled_ids)
    raw_items = raw.get("usedMemories", raw.get("used_memories"))
    if not isinstance(raw_items, list):
        return _AttributionResult(scores={}, reasons={}, source="llm", latency_ms=latency_ms)

    scores: dict[int, float] = {}
    reasons: dict[int, str] = {}
    for item in raw_items[: len(recalled_ids)]:
        if not isinstance(item, dict):
            continue
        memory_id = _int_id(item.get("memoryId", item.get("memory_id")))
        if memory_id is None or memory_id not in allowed_ids:
            continue
        score = _score(item.get("usefulnessScore", item.get("usefulness_score")))
        if score is None or score < _MIN_LLM_USEFULNESS_SCORE:
            continue
        scores[memory_id] = score
        reason = str(item.get("reason") or "").strip()
        if reason:
            reasons[memory_id] = reason[:300]
    return _AttributionResult(scores=scores, reasons=reasons, source="llm", latency_ms=latency_ms)


def _merge_attributions(heuristic: dict[int, float], llm_scores: dict[int, float]) -> dict[int, float]:
    merged = dict(heuristic)
    for memory_id, score in llm_scores.items():
        merged[memory_id] = max(score, merged.get(memory_id, 0.0))
    return merged


def _attribution_reason(heuristic: dict[int, float], llm_result: _AttributionResult) -> str:
    if heuristic and llm_result.scores:
        return "heuristic_and_llm_attribution"
    if llm_result.scores:
        return "llm_attribution_verifier"
    return "heuristic_attribution"


def _put_attribution_meta(
    observation: dict[str, Any],
    heuristic: dict[int, float],
    llm_result: _AttributionResult,
) -> None:
    observation["attribution"] = {
        "heuristic_used_memory_ids": list(heuristic.keys()),
        "llm_used_memory_ids": list(llm_result.scores.keys()),
        "llm_source": llm_result.source,
        "llm_failed": llm_result.failed,
    }
    if llm_result.reasons:
        observation["attribution"]["llm_reasons"] = {str(key): value for key, value in llm_result.reasons.items()}
    if llm_result.fallback_reason:
        observation["attribution"]["llm_fallback_reason"] = llm_result.fallback_reason
    if llm_result.latency_ms is not None:
        observation["attribution"]["llm_latency_ms"] = llm_result.latency_ms
    if llm_result.error_details:
        observation["attribution"]["llm_error_details"] = dict(llm_result.error_details)


def _recalled_memory_ids(input_payload: dict[str, Any]) -> list[int]:
    return list(dict.fromkeys(_raw_recalled_memory_ids(input_payload)))


def _raw_recalled_memory_ids(input_payload: dict[str, Any]) -> list[int]:
    raw_meta = input_payload.get(MEMORY_CONTEXT_META_KEY)
    recall = raw_meta.get("recall") if isinstance(raw_meta, dict) and isinstance(raw_meta.get("recall"), dict) else {}
    raw_ids = recall.get("memory_ids") if isinstance(recall, dict) else None
    if not isinstance(raw_ids, list):
        return []
    memory_ids: list[int] = []
    for value in raw_ids:
        if isinstance(value, int) and not isinstance(value, bool):
            memory_ids.append(value)
    return memory_ids


def _memory_texts_by_id(input_payload: dict[str, Any]) -> dict[int, _RecalledMemoryText]:
    prompt = str(input_payload.get("persistent_memory_context") or "")
    memory_texts: dict[int, _RecalledMemoryText] = {}
    for match in _MEMORY_BLOCK_PATTERN.finditer(prompt):
        memory_id = int(match.group("id"))
        fields = {
            field.group("key"): field.group("value").strip()
            for field in _FIELD_PATTERN.finditer(match.group("body"))
        }
        memory_texts[memory_id] = _RecalledMemoryText(
            memory_id=memory_id,
            memory_type=fields.get("type", ""),
            summary=fields.get("summary", ""),
            content=fields.get("content", ""),
        )
    return memory_texts


def _memory_text_payload(memory: _RecalledMemoryText) -> dict[str, Any]:
    return {
        "memoryId": memory.memory_id,
        "memoryType": memory.memory_type,
        "summary": memory.summary,
        "content": memory.content,
    }


def _attribution_user_query(input_payload: dict[str, Any]) -> str:
    for key in _ATTRIBUTION_QUERY_KEYS:
        value = input_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _int_id(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _score(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    if score < 0.0 or score > 1.0:
        return None
    return round(score, 2)


def _tokens(value: str) -> set[str]:
    tokens: set[str] = set()
    for match in _TOKEN_PATTERN.finditer(value.lower()):
        token = match.group(0)
        if token not in _STOPWORDS:
            tokens.add(token)
    return tokens


def _has_direct_phrase(source_text: str, assistant_message: str) -> bool:
    normalized_answer = " ".join(assistant_message.lower().split())
    for token in _tokens(source_text):
        if len(token) >= 4 and token in normalized_answer:
            return True
    return False


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _llm_attribution_fallback_reason(exc: BaseException, error_details: dict[str, Any]) -> str:
    status_code = error_details.get("provider_status_code")
    if isinstance(status_code, int):
        return f"llm_attribution_http_error:{status_code}"
    return f"llm_attribution_error:{type(exc).__name__}"


def _memory_provider_meta(provider: Any) -> dict[str, Any]:
    meta = getattr(provider, "last_memory_provider_meta", None)
    return dict(meta) if isinstance(meta, dict) else {}


def _skipped(reason: str, *, task_run_id: str | None, recalled_ids: list[int] | None = None) -> dict[str, Any]:
    recalled_ids = list(recalled_ids or [])
    return {
        "status": "skipped",
        "reason": reason,
        "attempted": False,
        "recalled_memory_ids": recalled_ids,
        "used_memory_ids": [],
        "skipped_memory_ids": recalled_ids,
        "scores": {},
        "deduplicated": False,
        "task_run_id_present": bool(str(task_run_id or "").strip()),
    }
