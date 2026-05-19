from __future__ import annotations

import logging
from datetime import date
from typing import Any

from app.api.memory_observation import build_writeback_observation
from app.clients.backend_memory import BackendMemoryClientError
from app.domain.orchestration.agent.memory.memory_extractor import MemoryExtractionContext
from app.domain.orchestration.agent.memory.memory_reconciler import (
    MemoryOperationReconciler,
    MemoryReconciliationContext,
)
from app.domain.orchestration.agent.memory.provider_retry import memory_provider_error_details
from app.domain.orchestration.agent.memory.runtime_context import resolve_memory_provider_name


logger = logging.getLogger(__name__)


async def writeback_persistent_memory_candidates(
    *,
    app_state: Any,
    user_id: str,
    user_message: str,
    assistant_message: str,
    session_id: str,
    workspace_key: str | None = None,
    task_run_id: str | None = None,
    user_message_id: str | None = None,
    assistant_message_id: str | None = None,
    model: str | None = None,
    request_date: str | None = None,
    provider_name: str | None = None,
    step_run_id: str | None = None,
) -> dict[str, Any]:
    """대화 완료 후 장기기억 후보를 추출해 backend에 저장 요청한다.

    writeback은 부가 기능이므로 실패해도 대화 저장/응답 흐름을 깨지 않는다.
    """

    memory_client = getattr(app_state, "backend_memory_client", None)
    memory_extractor = getattr(app_state, "memory_extractor", None)
    if memory_client is None:
        return build_writeback_observation(
            status="skipped",
            attempted=False,
            reason="memory_client_unavailable",
        )
    if memory_extractor is None:
        return build_writeback_observation(
            status="skipped",
            attempted=False,
            reason="memory_extractor_unavailable",
        )

    resolved_provider_name = resolve_memory_provider_name(provider_name, model)
    context = MemoryExtractionContext(
        user_id=user_id,
        session_id=session_id,
        workspace_key=workspace_key,
        task_run_id=task_run_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        model=str(model or "").strip() or None,
        request_date=_request_date(request_date),
        provider_name=resolved_provider_name,
        step_run_id=str(step_run_id or "").strip() or None,
    )
    try:
        candidates = await memory_extractor.extract_candidates(
            user_message=user_message,
            assistant_message=assistant_message,
            context=context,
        )
    except Exception as exc:
        logger.warning("장기기억 후보 추출에 실패했습니다.", exc_info=True)
        error_details = memory_provider_error_details(exc)
        return build_writeback_observation(
            status="extract_failed",
            attempted=False,
            reason=_memory_extractor_error_reason(error_details),
            failed=True,
            extra=error_details,
        )
    if not candidates:
        return build_writeback_observation(
            status="no_candidates",
            attempted=False,
        )

    reconciler = getattr(app_state, "memory_operation_reconciler", None)
    if reconciler is None:
        reconciler = MemoryOperationReconciler(
            memory_client,
            operation_provider=getattr(app_state, "memory_operation_provider", None),
        )
    candidates = await reconciler.reconcile_candidates(
        candidates=candidates,
        context=MemoryReconciliationContext(
            user_id=user_id,
            user_message=user_message,
            workspace_key=workspace_key,
            session_id=session_id,
            task_run_id=task_run_id,
            step_run_id=step_run_id,
            provider_name=resolved_provider_name,
            model=str(model or "").strip() or None,
        ),
    )
    original_candidate_count = len(candidates)
    candidates, deconflict_meta = _deconflict_target_changing_candidates(candidates)

    try:
        await memory_client.create_candidates(user_id=user_id, candidates=candidates)
    except BackendMemoryClientError as exc:
        logger.warning("backend 장기기억 후보 저장 요청에 실패했습니다.", exc_info=True)
        return build_writeback_observation(
            status="store_failed",
            attempted=True,
            candidates=candidates,
            reason="backend_memory_client_error",
            failed=True,
            extra={
                **deconflict_meta,
                "original_candidate_count": original_candidate_count,
                "final_candidate_count": len(candidates),
                **_backend_error_observation(exc),
            },
        )
    except Exception:
        logger.warning("장기기억 후보 저장 중 예기치 않은 예외가 발생했습니다.", exc_info=True)
        return build_writeback_observation(
            status="store_failed",
            attempted=True,
            candidates=candidates,
            reason="unexpected_store_error",
            failed=True,
            extra={
                **deconflict_meta,
                "original_candidate_count": original_candidate_count,
                "final_candidate_count": len(candidates),
            },
        )
    return build_writeback_observation(
        status="succeeded",
        attempted=True,
        candidates=candidates,
        extra={
            **deconflict_meta,
            "original_candidate_count": original_candidate_count,
            "final_candidate_count": len(candidates),
        },
    )


def _deconflict_target_changing_candidates(
    candidates: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    touched_target_ids: set[int] = set()
    skipped_target_ids: list[int] = []
    skipped_candidate_count = 0

    for candidate in candidates:
        target_ids = _candidate_target_ids(candidate)
        if target_ids and touched_target_ids.intersection(target_ids):
            skipped_candidate_count += 1
            for target_id in sorted(target_ids):
                if target_id not in skipped_target_ids:
                    skipped_target_ids.append(target_id)
            continue
        kept.append(candidate)
        touched_target_ids.update(target_ids)

    return kept, {
        "skipped_candidate_count": skipped_candidate_count,
        "skipped_target_memory_ids": skipped_target_ids,
    }


def _candidate_target_ids(candidate: dict[str, Any]) -> set[int]:
    operation_type = str(candidate.get("operationType") or "ADD").strip().upper()
    if operation_type not in {"UPDATE", "MERGE", "INVALIDATE"}:
        return set()

    target_ids: set[int] = set()
    _add_positive_int(target_ids, candidate.get("targetMemoryId"))
    additional_target_ids = candidate.get("additionalTargetMemoryIds")
    if isinstance(additional_target_ids, list):
        for value in additional_target_ids:
            _add_positive_int(target_ids, value)
    return target_ids


def _add_positive_int(target_ids: set[int], value: Any) -> None:
    if isinstance(value, bool):
        return
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return
    if parsed > 0:
        target_ids.add(parsed)


def _backend_error_observation(exc: BackendMemoryClientError) -> dict[str, Any]:
    observation: dict[str, Any] = {}
    if exc.status_code is not None:
        observation["backend_status"] = exc.status_code
    if exc.error_code:
        observation["backend_error_code"] = exc.error_code
    if exc.response_message:
        observation["backend_error_message"] = exc.response_message
    return observation


def _memory_extractor_error_reason(error_details: dict[str, Any]) -> str:
    if error_details.get("provider_status_code") is not None:
        return "memory_extractor_http_error"
    return "memory_extractor_error"


def _request_date(value: str | None) -> str:
    normalized = str(value or "").strip()
    return normalized or date.today().isoformat()
