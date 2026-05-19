from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

MEMORY_CONTEXT_META_KEY = "memory_context_meta"
MEMORY_OBSERVATION_RESULT_KEY = "memory_observation"

_MARK_USED_SKIPPED = {
    "status": "skipped",
    "reason": "usage_attribution_not_available",
}


def build_recall_observation(
    *,
    status: str,
    query: str | None,
    workspace_key: str | None,
    memories: list[Any] | None = None,
    reason: str | None = None,
    failed: bool = False,
) -> dict[str, Any]:
    """TaskRun input에 남길 recall 관측 metadata를 만든다.

    기억 원문은 prompt에만 사용하고 metadata에는 식별자/분류만 남긴다.
    """

    items = list(memories or [])
    observation: dict[str, Any] = {
        "status": status,
        "source": "backend",
        "query_present": bool(str(query or "").strip()),
        "workspace_key_present": bool(str(workspace_key or "").strip()),
        "count": len(items),
        "memory_ids": _memory_ids(items),
        "memory_types": _sorted_unique(_field_values(items, "memory_type")),
        "store_types": _sorted_unique(_field_values(items, "store_type")),
        "scope_types": _sorted_unique(_field_values(items, "scope_type")),
        "failed": failed,
    }
    if reason:
        observation["reason"] = reason
    return observation


def build_writeback_observation(
    *,
    status: str,
    attempted: bool,
    candidates: list[dict[str, Any]] | None = None,
    reason: str | None = None,
    failed: bool = False,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    items = list(candidates or [])
    observation: dict[str, Any] = {
        "status": status,
        "attempted": attempted,
        "candidate_count": len(items),
        "memory_types": _sorted_unique(_candidate_field_values(items, "memoryType")),
        "store_types": _sorted_unique(_candidate_field_values(items, "storeType")),
        "scope_types": _sorted_unique(_candidate_field_values(items, "scopeType")),
        "operation_types": _sorted_unique(_candidate_field_values(items, "operationType")),
        "failed": failed,
    }
    if reason:
        observation["reason"] = reason
    if extra:
        observation.update(extra)
    return observation


def build_memory_observation(
    *,
    task_input: dict[str, Any] | None,
    writeback: dict[str, Any] | None = None,
    mark_used: dict[str, Any] | None = None,
) -> dict[str, Any]:
    input_payload = dict(task_input or {})
    raw_meta = input_payload.get(MEMORY_CONTEXT_META_KEY)
    recall = raw_meta.get("recall") if isinstance(raw_meta, dict) and isinstance(raw_meta.get("recall"), dict) else None
    return {
        "recall": dict(recall or build_recall_observation(
            status="skipped",
            query=None,
            workspace_key=None,
            reason="recall_metadata_unavailable",
        )),
        "writeback": dict(writeback or build_writeback_observation(
            status="skipped",
            attempted=False,
            reason="writeback_not_applicable",
        )),
        "mark_used": dict(mark_used or _MARK_USED_SKIPPED),
    }


def attach_memory_observation_to_task(
    *,
    task: Any,
    repository: Any,
    writeback: dict[str, Any] | None = None,
    mark_used: dict[str, Any] | None = None,
) -> None:
    """TaskRun 결과 payload에 memory 관측값을 보강한다.

    관측값 저장 실패가 사용자 응답 완료 흐름을 깨지 않게 한다.
    """

    try:
        result_payload = dict(getattr(task, "result_payload", {}) or {})
        result_payload[MEMORY_OBSERVATION_RESULT_KEY] = build_memory_observation(
            task_input=dict(getattr(task, "input_payload", {}) or {}),
            writeback=writeback,
            mark_used=mark_used,
        )
        task.result_payload = result_payload
        repository.update_task(task)
    except Exception:
        logger.warning("TaskRun memory observation 저장에 실패했습니다.", exc_info=True)


def _memory_ids(items: list[Any]) -> list[int]:
    ids: list[int] = []
    for item in items:
        value = getattr(item, "id", None)
        if isinstance(value, int) and not isinstance(value, bool):
            ids.append(value)
    return ids


def _field_values(items: list[Any], field_name: str) -> list[str]:
    values: list[str] = []
    for item in items:
        value = getattr(item, field_name, None)
        if isinstance(value, str) and value:
            values.append(value)
    return values


def _candidate_field_values(items: list[dict[str, Any]], field_name: str) -> list[str]:
    values: list[str] = []
    for item in items:
        value = item.get(field_name)
        if isinstance(value, str) and value:
            values.append(value)
    return values


def _sorted_unique(values: list[str]) -> list[str]:
    return sorted(set(values))
