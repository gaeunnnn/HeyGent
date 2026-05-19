from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, replace
from typing import Any, Protocol

from app.api.memory_observation import MEMORY_CONTEXT_META_KEY, build_recall_observation
from app.clients.backend_memory import BackendMemoryClientError
from app.domain.orchestration.agent.memory.provider_retry import memory_provider_error_details
from app.domain.orchestration.agent.memory.runtime_context import memory_provider_runtime_context_from_task_input
from app.domain.orchestration.prompts.persistent_memory_prompt import build_persistent_memory_prompt

logger = logging.getLogger(__name__)

DEFAULT_MEMORY_RECALL_LIMIT = 5
DEFAULT_MEMORY_RECALL_PLANNER_TIMEOUT_SECONDS = 10.0
MEMORY_CONTEXT_KEYS = ("persistent_memory_context", "memory_context")
MEMORY_RECALL_QUERY_KEYS = ("prompt", "message", "query", "content", "text", "subject", "title")

MEMORY_RECALL_PLANNER_SYSTEM_PROMPT = """
You decide whether the AI runtime should recall long-term memory before answering.
Return strict JSON only, with this shape:
{"shouldRecall":true,"query":"...","reason":"...","limit":5,"filters":{"storeType":"USER_PROFILE|AGENT_MEMORY|null","memoryType":"PREFERENCE|PROFILE|FACT|INSTRUCTION|PROCEDURE|null","scopeType":"GLOBAL|WORKSPACE|null","metadataCategories":["preference|profile|fact|instruction|procedure|event|reason|task_state"]},"additionalRecallPlans":[{"query":"...","reason":"...","filters":{"storeType":"USER_PROFILE|AGENT_MEMORY|null","memoryType":"PREFERENCE|PROFILE|FACT|INSTRUCTION|PROCEDURE|null","scopeType":"GLOBAL|WORKSPACE|null","metadataCategories":["preference|profile|fact|instruction|procedure|event|reason|task_state"]}}]}

Rules:
- Skip recall for greetings, thanks, or trivial requests. If user or project history could change, personalize, or improve the answer, recall it even when the current input is answerable on its own.
- Use USER_PROFILE/PREFERENCE/GLOBAL/preference for stable user style, format, or preference.
- Requests about what to call the user, preferred name, nickname, addressing, likes, dislikes, or saved personal preferences should recall USER_PROFILE/PREFERENCE/GLOBAL/preference.
- Use USER_PROFILE/PROFILE/GLOBAL/profile for user role, identity, or working habit.
- Do not skip open-ended recommendations, suggestions, choices, or "what should I do/eat/use" questions. These should recall USER_PROFILE/PREFERENCE/GLOBAL/preference because preferences may materially change the answer.
- Use AGENT_MEMORY/FACT/GLOBAL/event,fact,reason for recent events, temporary constraints, health/diet restrictions, situational limitations, or other non-durable facts that should affect the current recommendation.
- Use AGENT_MEMORY/FACT/GLOBAL/fact,event for current user situations embedded in task requests, such as interview preparation, job search status, travel plans, health constraints, schedule constraints, or temporary workload. These are not PROFILE unless they describe durable identity or habit.
- Use AGENT_MEMORY/FACT/WORKSPACE/task_state,fact for continuing project implementation or current project state.
- Use AGENT_MEMORY/INSTRUCTION/GLOBAL/instruction,procedure for durable user instructions about how the assistant should answer or what process it should follow.
- Use AGENT_MEMORY/PROCEDURE/procedure,instruction for reusable workflow or repeated project procedure.
- Do not classify saved answer-format instructions, response workflows, or assistant behavior procedures as FACT/task_state. FACT/task_state is only for factual project/session state, not for how to respond.
- Do not classify temporary restrictions, recent events, or situational facts as USER_PROFILE/PROFILE. PROFILE is only for durable identity, role, or habit.
- If the user asks for a plan, recommendation, or advice based on a current situation, recall related FACT/event memories in addition to preference memories when useful.
- Use reason/event categories when the user asks why, history, records, schedule, or previous event context.
- If multiple memory classes could materially affect the answer, keep the primary plan narrow and add additionalRecallPlans for the other classes. For example, retrieve durable user preferences separately from reusable assistant instructions or procedures when both could matter.
- When the user asks the assistant to perform a task and a saved response workflow could control the answer structure, include an additional AGENT_MEMORY recall plan with memoryType INSTRUCTION or PROCEDURE and metadataCategories instruction,procedure.
- For repeated agent workflows such as "지난번처럼 docs/logs 작업하고 커밋해줘", recall reusable PROCEDURE/INSTRUCTION memories instead of treating the request itself as new memory.
- When both instruction and procedure memories could apply, avoid narrowing memoryType to only one of them; let metadataCategories instruction,procedure retrieve both.
- If a request may need both user preference and project state, or both user preference and reusable instructions, avoid over-narrowing; use additionalRecallPlans or omit uncertain filters.
- Do not use tags, sessionKey, or resourceId in this first implementation.
- Prefer omitting a filter over adding a weak or uncertain filter.
""".strip()


@dataclass(frozen=True, slots=True)
class MemoryRecallPlan:
    should_recall: bool
    query: str | None
    reason: str
    limit: int = DEFAULT_MEMORY_RECALL_LIMIT
    store_type: str | None = None
    memory_type: str | None = None
    scope_type: str | None = None
    workspace_key: str | None = None
    metadata_categories: tuple[str, ...] = ()
    planner_source: str = "rule"
    fallback_reason: str | None = None
    planner_latency_ms: int | None = None
    fallback_error_type: str | None = None
    fallback_status_code: int | None = None
    fallback_provider_name: str | None = None
    fallback_selected_model: str | None = None
    fallback_retry_attempts: int | None = None
    fallback_max_attempts: int | None = None
    fallback_provider_error_message: str | None = None
    additional_plans: tuple["MemoryRecallPlan", ...] = ()

    def filters(self) -> dict[str, Any]:
        filters: dict[str, Any] = {}
        _put_if_present(filters, "store_type", self.store_type)
        _put_if_present(filters, "memory_type", self.memory_type)
        _put_if_present(filters, "scope_type", self.scope_type)
        _put_if_present(filters, "workspace_key", self.workspace_key)
        if self.metadata_categories:
            filters["metadata_categories"] = list(self.metadata_categories)
        return filters


class MemoryRecallPlannerProvider(Protocol):
    async def plan_memory_recall_json(
        self,
        *,
        system_prompt: str,
        query: str,
        workspace_key: str | None,
        rule_plan: MemoryRecallPlan,
        model: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return the model-produced memory recall planning JSON."""


class LlmMemoryRecallPlanner:
    """LLM이 요청별 장기기억 recall 필요성과 backend filter를 판단한다."""

    def __init__(
        self,
        provider: MemoryRecallPlannerProvider,
        *,
        fallback_to_rules: bool = True,
        timeout_seconds: float = DEFAULT_MEMORY_RECALL_PLANNER_TIMEOUT_SECONDS,
    ) -> None:
        self._provider = provider
        self._fallback_to_rules = fallback_to_rules
        self._timeout_seconds = max(0.001, float(timeout_seconds))

    async def plan_recall(
        self,
        query: str | None,
        *,
        workspace_key: str | None = None,
        limit: int = DEFAULT_MEMORY_RECALL_LIMIT,
        model: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> MemoryRecallPlan:
        rule_plan = plan_memory_recall(query, workspace_key=workspace_key, limit=limit)
        if not rule_plan.query:
            return rule_plan
        started_at = time.perf_counter()
        try:
            raw = await asyncio.wait_for(
                self._provider.plan_memory_recall_json(
                    system_prompt=MEMORY_RECALL_PLANNER_SYSTEM_PROMPT,
                    query=rule_plan.query,
                    workspace_key=workspace_key,
                    rule_plan=rule_plan,
                    model=str(model or "").strip() or None,
                    runtime_context=runtime_context,
                ),
                timeout=self._timeout_seconds,
            )
            latency_ms = _elapsed_ms(started_at)
            return _normalize_llm_recall_plan(
                raw,
                rule_plan=rule_plan,
                workspace_key=workspace_key,
                limit=limit,
                planner_latency_ms=latency_ms,
            )
        except asyncio.TimeoutError:
            if not self._fallback_to_rules:
                raise
            latency_ms = _elapsed_ms(started_at)
            logger.warning("LLM memory recall planner timed out; falling back to rule planner", exc_info=True)
            return _fallback_rule_plan(
                rule_plan,
                reason="llm_planner_timeout",
                latency_ms=latency_ms,
                error_details=_memory_provider_meta(self._provider),
            )
        except Exception as exc:
            if not self._fallback_to_rules:
                raise
            latency_ms = _elapsed_ms(started_at)
            logger.warning("LLM memory recall planner failed; falling back to rule planner", exc_info=True)
            return _fallback_rule_plan(
                rule_plan,
                reason=_planner_fallback_reason(exc),
                latency_ms=latency_ms,
                error_details=memory_provider_error_details(exc),
            )


def clear_client_memory_context(task_input: dict[str, Any]) -> None:
    for key in MEMORY_CONTEXT_KEYS:
        task_input.pop(key, None)
    task_input.pop(MEMORY_CONTEXT_META_KEY, None)


def select_memory_recall_query(input_payload: dict[str, Any]) -> str | None:
    for key in MEMORY_RECALL_QUERY_KEYS:
        value = input_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def plan_memory_recall(
    query: str | None,
    *,
    workspace_key: str | None = None,
    limit: int = DEFAULT_MEMORY_RECALL_LIMIT,
) -> MemoryRecallPlan:
    normalized_query = str(query or "").strip()
    if not normalized_query:
        return MemoryRecallPlan(
            should_recall=False,
            query=None,
            reason="query_unavailable",
            limit=limit,
        )

    normalized_workspace_key = str(workspace_key or "").strip() or None
    compact = " ".join(normalized_query.lower().split())
    if _is_low_value_recall_query(compact):
        return MemoryRecallPlan(
            should_recall=False,
            query=normalized_query,
            reason="low_value_query",
            limit=limit,
        )

    wants_preference = _contains_any(compact, _PREFERENCE_HINTS)
    wants_profile = _contains_any(compact, _PROFILE_HINTS)
    wants_workspace = _contains_any(compact, _WORKSPACE_HINTS)
    wants_procedure = _contains_any(compact, _PROCEDURE_HINTS)
    wants_reason = _contains_any(compact, _REASON_HINTS)
    wants_event = _contains_any(compact, _EVENT_HINTS)

    if wants_preference and not (wants_workspace or wants_procedure or wants_reason or wants_event):
        return MemoryRecallPlan(
            should_recall=True,
            query=normalized_query,
            reason="user_preference_needed",
            limit=limit,
            store_type="USER_PROFILE",
            memory_type="PREFERENCE",
            scope_type="GLOBAL",
            metadata_categories=("preference",),
        )

    if wants_profile and not (wants_workspace or wants_procedure or wants_reason or wants_event):
        return MemoryRecallPlan(
            should_recall=True,
            query=normalized_query,
            reason="user_profile_needed",
            limit=limit,
            store_type="USER_PROFILE",
            memory_type="PROFILE",
            scope_type="GLOBAL",
            metadata_categories=("profile",),
        )

    if wants_workspace:
        categories = _workspace_categories(
            wants_procedure=wants_procedure,
            wants_reason=wants_reason,
            wants_event=wants_event,
        )
        return MemoryRecallPlan(
            should_recall=True,
            query=normalized_query,
            reason="workspace_memory_needed",
            limit=limit,
            store_type="AGENT_MEMORY",
            memory_type="PROCEDURE" if wants_procedure and not (wants_reason or wants_event) else "FACT",
            scope_type="WORKSPACE" if normalized_workspace_key else None,
            workspace_key=normalized_workspace_key,
            metadata_categories=categories,
        )

    if wants_procedure:
        return MemoryRecallPlan(
            should_recall=True,
            query=normalized_query,
            reason="procedure_memory_needed",
            limit=limit,
            store_type="AGENT_MEMORY",
            memory_type="PROCEDURE",
            metadata_categories=("procedure", "instruction"),
        )

    if wants_reason:
        return MemoryRecallPlan(
            should_recall=True,
            query=normalized_query,
            reason="reason_memory_needed",
            limit=limit,
            store_type="AGENT_MEMORY",
            memory_type="FACT",
            metadata_categories=("reason", "fact"),
        )

    if wants_event:
        return MemoryRecallPlan(
            should_recall=True,
            query=normalized_query,
            reason="event_memory_needed",
            limit=limit,
            store_type="AGENT_MEMORY",
            memory_type="FACT",
            metadata_categories=("event", "task_state", "fact"),
        )

    return MemoryRecallPlan(
        should_recall=True,
        query=normalized_query,
        reason="general_semantic_recall",
        limit=limit,
    )


async def attach_persistent_memory_context(
    *,
    app_state: Any,
    task_input: dict[str, Any],
    user_id: str,
    query: str | None,
    workspace_key: str | None = None,
    limit: int = DEFAULT_MEMORY_RECALL_LIMIT,
    force_workspace_key: bool = False,
) -> None:
    clear_client_memory_context(task_input)
    recall_planner = getattr(app_state, "memory_recall_planner", None)
    if recall_planner is not None:
        recall_plan = await recall_planner.plan_recall(
            query,
            workspace_key=workspace_key,
            limit=limit,
            model=_memory_provider_model(task_input),
            runtime_context=memory_provider_runtime_context_from_task_input(
                task_input,
                user_id=user_id,
                session_id=task_input.get("session_id") or task_input.get("sessionId"),
                model=_memory_provider_model(task_input),
            ),
        )
    else:
        recall_plan = plan_memory_recall(query, workspace_key=workspace_key, limit=limit)
    if force_workspace_key and workspace_key and recall_plan.workspace_key is None:
        recall_plan = replace(recall_plan, workspace_key=str(workspace_key).strip() or None)
    if not recall_plan.should_recall:
        _set_recall_meta(
            task_input,
            _with_recall_plan(
                build_recall_observation(
                    status="skipped",
                    query=recall_plan.query,
                    workspace_key=recall_plan.workspace_key,
                    reason=recall_plan.reason,
                ),
                recall_plan,
            ),
        )
        return

    normalized_query = str(recall_plan.query or "").strip()
    if not normalized_query:
        _set_recall_meta(
            task_input,
            _with_recall_plan(
                build_recall_observation(
                    status="skipped",
                    query=query,
                    workspace_key=workspace_key,
                    reason="query_unavailable",
                ),
                recall_plan,
            ),
        )
        return

    memory_client = getattr(app_state, "backend_memory_client", None)
    if memory_client is None:
        _set_recall_meta(
            task_input,
            _with_recall_plan(
                build_recall_observation(
                    status="skipped",
                    query=normalized_query,
                    workspace_key=recall_plan.workspace_key,
                    reason="memory_client_unavailable",
                ),
                recall_plan,
            ),
        )
        return

    try:
        memories = await _recall_memories_for_plans(
            memory_client=memory_client,
            user_id=str(user_id),
            plans=_ordered_recall_plans(recall_plan),
            fallback_query=normalized_query,
        )
    except BackendMemoryClientError:
        logger.warning("backend memory recall failed; continuing without persistent memory context", exc_info=True)
        _set_recall_meta(
            task_input,
            _with_recall_plan(
                build_recall_observation(
                    status="failed",
                    query=normalized_query,
                    workspace_key=recall_plan.workspace_key,
                    reason="backend_memory_client_error",
                    failed=True,
                ),
                recall_plan,
            ),
        )
        return

    memory_prompt = build_persistent_memory_prompt(memories)
    _set_recall_meta(
        task_input,
        _with_recall_plan(
            build_recall_observation(
                status="injected" if memory_prompt else "empty",
                query=normalized_query,
                workspace_key=recall_plan.workspace_key,
                memories=memories,
            ),
            recall_plan,
        ),
    )
    if memory_prompt:
        task_input["persistent_memory_context"] = memory_prompt


async def _recall_memories_for_plans(
    *,
    memory_client: Any,
    user_id: str,
    plans: tuple[MemoryRecallPlan, ...],
    fallback_query: str,
) -> list[Any]:
    memories: list[Any] = []
    seen_ids: set[int] = set()
    for plan in plans:
        query = str(plan.query or fallback_query).strip() or None
        plan_memories = await _recall_memories_for_plan(
            memory_client=memory_client,
            user_id=user_id,
            query=query,
            plan=plan,
        )
        for memory in plan_memories:
            memory_id = getattr(memory, "id", None)
            if isinstance(memory_id, int) and not isinstance(memory_id, bool):
                if memory_id in seen_ids:
                    continue
                seen_ids.add(memory_id)
            memories.append(memory)
    return memories


async def _recall_memories_for_plan(
    *,
    memory_client: Any,
    user_id: str,
    query: str | None,
    plan: MemoryRecallPlan,
) -> list[Any]:
    memories = await memory_client.recall(
        user_id=user_id,
        query=query,
        limit=plan.limit,
        workspace_key=plan.workspace_key,
        store_type=plan.store_type,
        memory_type=plan.memory_type,
        scope_type=plan.scope_type,
        metadata_categories=list(plan.metadata_categories) or None,
    )
    if not memories and _should_retry_recall_without_query(plan):
        memories = await memory_client.recall(
            user_id=user_id,
            query=None,
            limit=plan.limit,
            workspace_key=plan.workspace_key,
            store_type=plan.store_type,
            memory_type=plan.memory_type,
            scope_type=plan.scope_type,
            metadata_categories=list(plan.metadata_categories) or None,
        )
    return list(memories or [])


def _ordered_recall_plans(recall_plan: MemoryRecallPlan) -> tuple[MemoryRecallPlan, ...]:
    plans: list[MemoryRecallPlan] = [replace(recall_plan, additional_plans=())]
    seen = {_plan_identity(plans[0])}
    for additional_plan in recall_plan.additional_plans:
        if not additional_plan.should_recall:
            continue
        identity = _plan_identity(additional_plan)
        if identity in seen:
            continue
        plans.append(replace(additional_plan, additional_plans=()))
        seen.add(identity)
    return tuple(plans)


def _plan_identity(plan: MemoryRecallPlan) -> tuple[Any, ...]:
    return (
        plan.query,
        plan.store_type,
        plan.memory_type,
        plan.scope_type,
        plan.workspace_key,
        plan.metadata_categories,
    )


def _set_recall_meta(task_input: dict[str, Any], recall_meta: dict[str, Any]) -> None:
    task_input[MEMORY_CONTEXT_META_KEY] = {"recall": recall_meta}


def _with_recall_plan(recall_meta: dict[str, Any], recall_plan: MemoryRecallPlan) -> dict[str, Any]:
    enriched = dict(recall_meta)
    enriched["planner"] = {
        "should_recall": recall_plan.should_recall,
        "reason": recall_plan.reason,
        "source": recall_plan.planner_source,
        "filters": recall_plan.filters(),
    }
    if recall_plan.fallback_reason:
        enriched["planner"]["fallback_reason"] = recall_plan.fallback_reason
    if recall_plan.planner_latency_ms is not None:
        enriched["planner"]["latency_ms"] = recall_plan.planner_latency_ms
    if recall_plan.fallback_error_type:
        enriched["planner"]["fallback_error_type"] = recall_plan.fallback_error_type
    if recall_plan.fallback_status_code is not None:
        enriched["planner"]["fallback_status_code"] = recall_plan.fallback_status_code
    if recall_plan.fallback_provider_name:
        enriched["planner"]["fallback_provider_name"] = recall_plan.fallback_provider_name
    if recall_plan.fallback_selected_model:
        enriched["planner"]["fallback_selected_model"] = recall_plan.fallback_selected_model
    if recall_plan.fallback_retry_attempts is not None:
        enriched["planner"]["fallback_retry_attempts"] = recall_plan.fallback_retry_attempts
    if recall_plan.fallback_max_attempts is not None:
        enriched["planner"]["fallback_max_attempts"] = recall_plan.fallback_max_attempts
    if recall_plan.fallback_provider_error_message:
        enriched["planner"]["fallback_provider_error_message"] = recall_plan.fallback_provider_error_message
    if recall_plan.additional_plans:
        enriched["planner"]["additional_plans"] = [
            {
                "reason": plan.reason,
                "source": plan.planner_source,
                "filters": plan.filters(),
                "query_present": bool(str(plan.query or "").strip()),
            }
            for plan in recall_plan.additional_plans
        ]
    return enriched


def _should_retry_recall_without_query(recall_plan: MemoryRecallPlan) -> bool:
    return (
        recall_plan.store_type in {"USER_PROFILE", "AGENT_MEMORY"}
        and (recall_plan.memory_type in {"PREFERENCE", "PROFILE", "FACT", "INSTRUCTION", "PROCEDURE", None})
        and recall_plan.scope_type in {"GLOBAL", "WORKSPACE", None}
        and bool(recall_plan.metadata_categories)
    )


def _normalize_llm_recall_plan(
    raw: Any,
    *,
    rule_plan: MemoryRecallPlan,
    workspace_key: str | None,
    limit: int,
    planner_latency_ms: int,
) -> MemoryRecallPlan:
    if not isinstance(raw, dict):
        return _fallback_rule_plan(rule_plan, reason="invalid_llm_planner_response", latency_ms=planner_latency_ms)
    should_recall = raw.get("shouldRecall", raw.get("should_recall"))
    if not isinstance(should_recall, bool):
        should_recall = rule_plan.should_recall

    query = _trimmed(raw.get("query"), max_length=500) or rule_plan.query
    reason = _trimmed(raw.get("reason"), max_length=200) or "llm_recall_planner"
    normalized_limit = _limit(raw.get("limit"), default=limit)
    filters = raw.get("filters")
    filters = filters if isinstance(filters, dict) else {}

    store_type = _enum(filters.get("storeType", filters.get("store_type")), _ALLOWED_STORE_TYPES)
    memory_type = _enum(filters.get("memoryType", filters.get("memory_type")), _ALLOWED_MEMORY_TYPES)
    scope_type = _enum(filters.get("scopeType", filters.get("scope_type")), _ALLOWED_SCOPE_TYPES)
    metadata_categories = _metadata_categories(filters.get("metadataCategories", filters.get("metadata_categories")))

    normalized_workspace_key = str(workspace_key or "").strip() or None
    if scope_type == "WORKSPACE" and not normalized_workspace_key:
        scope_type = None

    store_type, memory_type = _align_store_and_memory_type(store_type, memory_type)
    store_type, memory_type, metadata_categories = _align_filters_with_metadata_categories(
        store_type,
        memory_type,
        metadata_categories,
    )

    primary_plan = MemoryRecallPlan(
        should_recall=should_recall,
        query=query,
        reason=reason,
        limit=normalized_limit,
        store_type=store_type,
        memory_type=memory_type,
        scope_type=scope_type,
        workspace_key=normalized_workspace_key if scope_type == "WORKSPACE" else None,
        metadata_categories=metadata_categories,
        planner_source="llm",
        planner_latency_ms=planner_latency_ms,
    )
    additional_plans = _normalize_additional_llm_recall_plans(
        raw.get("additionalRecallPlans", raw.get("additional_recall_plans")),
        primary_plan=primary_plan,
        workspace_key=workspace_key,
        limit=normalized_limit,
        planner_latency_ms=planner_latency_ms,
    )
    if additional_plans:
        return replace(primary_plan, additional_plans=additional_plans)
    return primary_plan


def _normalize_additional_llm_recall_plans(
    raw_plans: Any,
    *,
    primary_plan: MemoryRecallPlan,
    workspace_key: str | None,
    limit: int,
    planner_latency_ms: int,
) -> tuple[MemoryRecallPlan, ...]:
    if not isinstance(raw_plans, list):
        return ()

    normalized_workspace_key = str(workspace_key or "").strip() or None
    plans: list[MemoryRecallPlan] = []
    seen = {_plan_identity(primary_plan)}
    for raw_plan in raw_plans[:3]:
        if not isinstance(raw_plan, dict):
            continue
        raw_should_recall = raw_plan.get("shouldRecall", raw_plan.get("should_recall", True))
        if raw_should_recall is False:
            continue
        query = _trimmed(raw_plan.get("query"), max_length=500) or primary_plan.query
        reason = _trimmed(raw_plan.get("reason"), max_length=200) or "llm_additional_recall_plan"
        plan_limit = _limit(raw_plan.get("limit"), default=limit)
        filters = raw_plan.get("filters")
        filters = filters if isinstance(filters, dict) else {}

        store_type = _enum(filters.get("storeType", filters.get("store_type")), _ALLOWED_STORE_TYPES)
        memory_type = _enum(filters.get("memoryType", filters.get("memory_type")), _ALLOWED_MEMORY_TYPES)
        scope_type = _enum(filters.get("scopeType", filters.get("scope_type")), _ALLOWED_SCOPE_TYPES)
        metadata_categories = _metadata_categories(filters.get("metadataCategories", filters.get("metadata_categories")))
        if scope_type == "WORKSPACE" and not normalized_workspace_key:
            scope_type = None
        store_type, memory_type = _align_store_and_memory_type(store_type, memory_type)
        store_type, memory_type, metadata_categories = _align_filters_with_metadata_categories(
            store_type,
            memory_type,
            metadata_categories,
        )

        plan = MemoryRecallPlan(
            should_recall=True,
            query=query,
            reason=reason,
            limit=plan_limit,
            store_type=store_type,
            memory_type=memory_type,
            scope_type=scope_type,
            workspace_key=normalized_workspace_key if scope_type == "WORKSPACE" else None,
            metadata_categories=metadata_categories,
            planner_source="llm",
            planner_latency_ms=planner_latency_ms,
        )
        identity = _plan_identity(plan)
        if identity in seen:
            continue
        plans.append(plan)
        seen.add(identity)
    return tuple(plans)


def _fallback_rule_plan(
    rule_plan: MemoryRecallPlan,
    *,
    reason: str,
    latency_ms: int,
    error_details: dict[str, Any] | None = None,
) -> MemoryRecallPlan:
    details = dict(error_details or {})
    return replace(
        rule_plan,
        planner_source="rule_fallback",
        fallback_reason=reason,
        planner_latency_ms=latency_ms,
        fallback_error_type=details.get("error_type") if isinstance(details.get("error_type"), str) else None,
        fallback_status_code=details.get("provider_status_code") if isinstance(details.get("provider_status_code"), int) else None,
        fallback_provider_name=details.get("provider_name") if isinstance(details.get("provider_name"), str) else None,
        fallback_selected_model=details.get("selected_model") if isinstance(details.get("selected_model"), str) else None,
        fallback_retry_attempts=details.get("retry_attempts") if isinstance(details.get("retry_attempts"), int) else None,
        fallback_max_attempts=details.get("max_attempts") if isinstance(details.get("max_attempts"), int) else None,
        fallback_provider_error_message=details.get("provider_error_message") if isinstance(details.get("provider_error_message"), str) else None,
    )


def _planner_fallback_reason(exc: BaseException) -> str:
    details = memory_provider_error_details(exc)
    status_code = details.get("provider_status_code")
    if isinstance(status_code, int):
        return f"llm_planner_http_error:{status_code}"
    return f"llm_planner_error:{type(exc).__name__}"


def _memory_provider_meta(provider: Any) -> dict[str, Any]:
    meta = getattr(provider, "last_memory_provider_meta", None)
    return dict(meta) if isinstance(meta, dict) else {}


def _align_store_and_memory_type(store_type: str | None, memory_type: str | None) -> tuple[str | None, str | None]:
    if memory_type in {"PREFERENCE", "PROFILE"}:
        return "USER_PROFILE", memory_type
    if memory_type in {"FACT", "INSTRUCTION", "PROCEDURE"}:
        return "AGENT_MEMORY", memory_type
    return store_type, memory_type


def _align_filters_with_metadata_categories(
    store_type: str | None,
    memory_type: str | None,
    metadata_categories: tuple[str, ...],
) -> tuple[str | None, str | None, tuple[str, ...]]:
    categories = list(metadata_categories)
    category_set = set(categories)

    if memory_type in {"INSTRUCTION", "PROCEDURE"} and {"instruction", "procedure"}.issubset(category_set):
        memory_type = None

    fact_like_categories = {"fact", "event", "reason", "task_state"}
    if memory_type == "PROFILE" and category_set.intersection(fact_like_categories):
        store_type = "AGENT_MEMORY"
        memory_type = "FACT"
        categories = [category for category in categories if category != "profile"]
        if not categories:
            categories = ["fact"]
    elif memory_type == "FACT" and "profile" in category_set:
        categories = [category for category in categories if category != "profile"]

    if not memory_type and category_set.intersection({"instruction", "procedure"}):
        store_type = "AGENT_MEMORY"
    if not memory_type and category_set.intersection(fact_like_categories) and "profile" not in category_set:
        store_type = "AGENT_MEMORY"

    return store_type, memory_type, tuple(dict.fromkeys(categories))


def _workspace_categories(*, wants_procedure: bool, wants_reason: bool, wants_event: bool) -> tuple[str, ...]:
    categories: list[str] = []
    if wants_procedure:
        categories.extend(["procedure", "instruction"])
    if wants_reason:
        categories.append("reason")
    if wants_event:
        categories.append("event")
    categories.extend(["task_state", "fact"])
    return tuple(dict.fromkeys(categories))


def _is_low_value_recall_query(compact_query: str) -> bool:
    return compact_query in _LOW_VALUE_RECALL_QUERIES or any(
        compact_query.startswith(prefix) and len(compact_query) <= len(prefix) + 4
        for prefix in _LOW_VALUE_RECALL_PREFIXES
    )


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    return any(hint in text for hint in hints)


def _put_if_present(payload: dict[str, Any], key: str, value: str | None) -> None:
    if value:
        payload[key] = value


def _memory_provider_model(task_input: dict[str, Any]) -> str | None:
    model = task_input.get("model") or task_input.get("provider_model") or task_input.get("providerModel")
    return str(model or "").strip() or None


def _elapsed_ms(started_at: float) -> int:
    return max(0, round((time.perf_counter() - started_at) * 1000))


def _trimmed(value: Any, *, max_length: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length]


def _limit(value: Any, *, default: int) -> int:
    if isinstance(value, bool):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if parsed < 1:
        return default
    return min(parsed, 20)


def _enum(value: Any, allowed: set[str]) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip().upper()
    return normalized if normalized in allowed else None


def _metadata_categories(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    categories: list[str] = []
    for item in value[:8]:
        if not isinstance(item, str):
            continue
        normalized = item.strip().lower().replace("-", "_")
        if normalized in _ALLOWED_METADATA_CATEGORIES:
            categories.append(normalized)
    return tuple(dict.fromkeys(categories))


_LOW_VALUE_RECALL_QUERIES = {
    "안녕",
    "안녕하세요",
    "고마워",
    "감사",
    "감사합니다",
    "thanks",
    "thank you",
    "hi",
    "hello",
}
_LOW_VALUE_RECALL_PREFIXES = ("안녕", "고마", "감사", "thanks", "thank you", "hi", "hello")
_PREFERENCE_HINTS = (
    "선호",
    "말투",
    "톤",
    "형식",
    "짧게",
    "길게",
    "앞으로",
    "복붙",
    "jira",
    "지라",
    "mr",
)
_PROFILE_HINTS = ("내 담당", "내 역할", "프로필", "나는 ", "제가 ")
_WORKSPACE_HINTS = (
    "이어서",
    "아까",
    "방금",
    "기존",
    "현재 구현",
    "구현",
    "브랜치",
    "코드",
    "문서",
    "docs",
    "logs",
    "장기기억",
    "작업",
    "테스트",
    "검증",
    "backend",
    "프론트",
)
_PROCEDURE_HINTS = ("작업해줘", "docs/logs", "로그", "mr", "절차", "방법")
_REASON_HINTS = ("왜", "이유", "근거")
_EVENT_HINTS = ("언제", "지난", "기록", "이력", "시연", "일정")
_ALLOWED_STORE_TYPES = {"USER_PROFILE", "AGENT_MEMORY"}
_ALLOWED_MEMORY_TYPES = {"PREFERENCE", "PROFILE", "FACT", "INSTRUCTION", "PROCEDURE"}
_ALLOWED_SCOPE_TYPES = {"GLOBAL", "WORKSPACE"}
_ALLOWED_METADATA_CATEGORIES = {
    "preference",
    "profile",
    "fact",
    "instruction",
    "procedure",
    "event",
    "reason",
    "task_state",
}
