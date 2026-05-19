from __future__ import annotations

from copy import deepcopy
from typing import Any


_SEMANTIC_STATUS_BY_LIFECYCLE = {
    "pending": "pending",
    "running": "running",
    "resuming": "running",
    "waiting": "waiting",
    "completed": "completed",
    "failed": "failed",
    "canceled": "canceled",
    "cancelled": "canceled",
}

_OPERATION_KIND_ALIASES = {
    "prepare": "prepare",
    "mapping": "prepare",
    "plan": "prepare",
    "input": "prepare",
    "execute": "execute",
    "tool": "execute",
    "local": "execute",
    "llm": "execute",
    "summarize": "summarize",
    "summary": "summarize",
    "handoff": "handoff",
    "delegate": "handoff",
    "finalize": "finalize",
    "finalise": "finalize",
    "finish": "finalize",
}


# StepRun detail 은 v1 에서 별도 invocation 테이블 대신 한 곳에 모아 둔다.
# 나중에 tool / agent / llm 계층을 분리하더라도 이 구조를 기준점으로 삼을 수 있게
# 키 이름을 먼저 고정해 둔다.
DEFAULT_STEP_DETAIL: dict[str, Any] = {
    "semanticDetail": {
        # semanticKey 는 StepRun 을 어떤 의미 단위로 묶는지 나타낸다.
        # handler/step_type 이 바뀌어도 "사용자에게 설명되는 단계"를 이 값으로 계속 추적한다.
        "semanticKey": None,
        # 화면과 이벤트 로그에서 보여 줄 semantic step 이름.
        # step.title 과 유사하지만, 나중에 실행 세부가 더 쪼개져도 대표 이름으로 유지할 수 있게 분리한다.
        "semanticStep": None,
        # 이 step 이 왜 존재하는지 설명하는 한 줄 목적.
        # StepRun 을 단순 UI 카드가 아니라 의미 단위 상태로 유지하려면 목적 문장을 같이 보존해야 한다.
        "goal": None,
        # semantic step 이 어떤 lifecycle 에 있는지 기록한다.
        # WAITING/RESUME/COMPLETED 전이를 detail 안에도 남겨 두어 이벤트만으로 잃어버리지 않게 한다.
        "lifecycle": "pending",
        # semantic step 의 현재 의미 단위 상태.
        # operation 진행 수와 lifecycle 을 같이 해석해야 하므로 별도 상태 필드로 유지한다.
        "status": "pending",
        # semantic step 의 operational anchor 인 StepRun ID.
        # approval, waiting, resume, child linkage 가 모두 결국 이 anchor 로 되돌아오게 하기 위해 넣는다.
        "anchorStepRunId": None,
    },
    "agentDetail": {
        # 다른 agent 를 실제로 호출했는지 여부.
        # 단순 LLM 호출과 agent orchestration 을 구분하려고 필요하다.
        "called": False,
        # 호출한 agent 의 식별자.
        # 어떤 agent 에 위임됐는지 추적해야 디버깅과 상세 화면 연결이 가능하다.
        "agentId": None,
        # worker가 별도 transcript/session으로 실행되면 해당 agent_session ID를 저장한다.
        # 부모 StepRun은 worker 중간 로그를 섞지 않고 이 세션 ID와 handoff summary만 참조한다.
        "workerSessionId": None,
        # worker profile key는 재시작 뒤에도 어떤 실행 설정이 주입됐는지 확인하는 힌트다.
        "profileKey": None,
        # worker agent 가 남긴 한 줄 요약.
        # parent step 이 worker 전체 로그를 열지 않아도 delegation 결과를 바로 보여 주기 위해 둔다.
        "summary": None,
        # worker agent 의 최종 상태.
        # parent step 이 linkage 만 보고도 worker 성공/실패/대기를 바로 판단할 수 있게 남긴다.
        "status": None,
    },
    "toolDetail": {
        # 사용한 tool 이름 목록.
        # 한 step 안에서 어떤 외부 도구를 건드렸는지 빠르게 파악할 수 있다.
        "toolNames": [],
        # 가장 핵심적으로 사용한 대표 tool 이름.
        # 목록이 길어질 때 UI 한 줄 요약용으로 쓰기 좋다.
        "primaryTool": None,
    },
    "llmDetail": {
        # 사용한 모델명.
        # 결과 품질/비용/재현성 이슈가 생겼을 때 모델 단위 추적이 필요하다.
        "model": None,
        # 해당 step 에서 LLM 을 몇 번 호출했는지 카운트.
        # 재시도나 다중 호출 여부를 파악해 비용/지연 분석에 쓴다.
        "callCount": 0,
    },
    "operationDetail": {
        # semantic step 안에서 실제로 수행된 하위 operation 목록.
        # StepRun 을 더 잘게 쪼개지 않더라도 어떤 내부 동작이 있었는지 여기서 추적한다.
        "operations": [],
        # 등록된 operation 전체 개수.
        "totalCount": 0,
        # 완료된 operation 개수.
        "completedCount": 0,
    },
    "planningDetail": {
        # semantic step 내부 계획 항목.
        # 다음 행동을 강제하는 엔진이 아니라, 현재 step 안에 어떤 하위 작업이 남았는지 보여 주는 외부 상태다.
        "todoItems": [],
        "currentKey": None,
        "totalCount": 0,
        "completedCount": 0,
    },
    "approvalDetail": {
        # 이 step 이 approval lifecycle 에 실제로 들어갔는지 여부.
        # WAITING step 중에서도 사용자 승인 기준으로 멈춘 것인지 구분해야 resume 정책을 단순하게 유지할 수 있다.
        "approvalRequested": False,
        # 현재 step 에 연결된 approval 식별자.
        # approval.step_run_id 와 함께 exact resume 를 복원하는 운영 기준점이다.
        "approvalId": None,
        # 어떤 이유로 승인을 요청했는지 저장한다.
        # StepRun 단독 조회만으로도 왜 멈췄는지 파악할 수 있어야 해서 request payload 를 복제 보관한다.
        "request": None,
        # 승인 응답 payload.
        # resume 가 끝난 뒤에도 어떤 입력으로 재개되었는지 이 step 에서 바로 볼 수 있게 남긴다.
        "response": None,
    },
    "modelDecisionDetail": {
        # 모델이 현재 턴에서 어떤 유형의 행동을 골랐는지 나타낸다.
        # action 은 엔진 상태 전이를 대신하지 않고, 모델 선택 의도를 복기하는 용도다.
        "action": None,
        # 왜 이 행동을 골랐는지에 대한 한 줄 요약.
        # step summary 와 handoff 품질을 보강할 때 쓴다.
        "actionSummary": None,
        # 다음 단계로 넘기기 좋은 짧은 요약.
        # workflow handoff 시 raw payload 대신 먼저 참고할 수 있는 모델측 요약이다.
        "handoffSummary": None,
        # 현재 semantic 단계에 대한 soft hint.
        # agent.loop에서는 runtime이 만든 StepRun 실행 anchor에 모델의 진행 설명을 누적한다.
        "semanticHint": None,
    },
}


def build_default_step_detail() -> dict[str, Any]:
    """StepRun 이 기본적으로 가져야 하는 detail 구조를 만든다.

    deepcopy 를 쓰는 이유는 dataclass default 로 같은 dict 인스턴스가 재사용되면
    다른 step 의 detail 이 섞일 수 있기 때문이다.
    """

    return deepcopy(DEFAULT_STEP_DETAIL)


def build_semantic_step_detail(
    *,
    step_run_id: str,
    semantic_key: str,
    semantic_step: str,
    semantic_goal: str,
    lifecycle: str,
    status: str | None = None,
) -> dict[str, Any]:
    """semantic step + operational anchor 메타데이터를 만든다.

    StepRun 은 지금 단계에서 UI 카드가 아니라, waiting/resume/approval 를 묶는 기준점이다.
    그래서 semantic 이름과 goal, 그리고 exact anchor 인 step_run_id 를 항상 같이 움직이게 한다.
    """

    return {
        "semanticDetail": {
            "semanticKey": semantic_key,
            "semanticStep": semantic_step,
            "goal": semantic_goal,
            "lifecycle": lifecycle,
            "status": status or infer_semantic_status(lifecycle=lifecycle),
            "anchorStepRunId": step_run_id,
        }
    }


def semantic_key_of(detail: dict[str, Any] | None) -> str | None:
    """StepRun detail 에 저장된 semanticKey 를 안전하게 꺼낸다."""

    semantic_key = (_safe_dict(detail).get("semanticDetail") or {}).get("semanticKey")
    normalized = str(semantic_key or "").strip()
    return normalized or None


def should_open_new_semantic_step(
    *,
    current_detail: dict[str, Any] | None,
    next_semantic_key: str,
    requires_independent_anchor: bool = False,
) -> bool:
    """다음 동작이 새 StepRun anchor 를 요구하는지 판단한다.

    StepRun 은 내부 operation 조각이 아니라 의미 단위 anchor 다. 같은 semanticKey 의
    prepare/execute/summarize/finalize 는 기존 StepRun 에 누적하고, semanticKey 가
    실제로 바뀌거나 별도 waiting/resume/delegation anchor 가 필요할 때만 새 step 후보로 본다.
    """

    if requires_independent_anchor:
        return True

    current_semantic_key = semantic_key_of(current_detail)
    normalized_next_key = str(next_semantic_key or "").strip()
    if not current_semantic_key or not normalized_next_key:
        return False
    return current_semantic_key != normalized_next_key


def should_reuse_semantic_step(current_detail: dict[str, Any] | None, next_semantic_key: str) -> bool:
    return not should_open_new_semantic_step(
        current_detail=current_detail,
        next_semantic_key=next_semantic_key,
    )


def build_approval_detail(
    *,
    approval_requested: bool,
    approval_id: str | None,
    request_payload: dict[str, Any] | None = None,
    response_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """approval lifecycle 메타데이터 patch 를 만든다."""

    detail: dict[str, Any] = {
        "approvalRequested": approval_requested,
        "approvalId": approval_id,
    }
    if request_payload is not None:
        detail["request"] = request_payload
    if response_payload is not None:
        detail["response"] = response_payload
    return {
        "approvalDetail": detail
    }


def build_model_decision_detail(
    *,
    action: str | None,
    action_summary: str | None = None,
    handoff_summary: str | None = None,
    semantic_hint: dict[str, Any] | None = None,
) -> dict[str, Any]:
    detail: dict[str, Any] = {
        "action": action,
        "actionSummary": action_summary,
        "handoffSummary": handoff_summary,
        "semanticHint": semantic_hint,
    }
    return {
        "modelDecisionDetail": detail
    }


def build_operation_detail(operations: list[dict[str, Any]], *, current_detail: dict[str, Any] | None = None) -> dict[str, Any]:
    existing_operations = ((_safe_dict(current_detail).get("operationDetail") or {}).get("operations") or [])
    normalized_operations = _merge_operations(existing_operations=existing_operations, new_operations=operations)
    status_counts = _operation_status_counts(normalized_operations)
    return {
        "operationDetail": {
            "operations": normalized_operations,
            "totalCount": len(normalized_operations),
            "completedCount": status_counts["completed"],
            "failedCount": status_counts["failed"],
            "canceledCount": status_counts["canceled"],
            "waitingCount": status_counts["waiting"],
            "runningCount": status_counts["running"],
            "statusCounts": status_counts,
        }
    }


def build_planning_detail(*, todo_items: list[dict[str, Any]], current_key: str | None) -> dict[str, Any]:
    normalized_items = [
        {
            "key": str(item.get("key") or ""),
            "title": str(item.get("title") or ""),
            "kind": str(item.get("kind") or "operation"),
            "status": str(item.get("status") or "pending"),
        }
        for item in todo_items
        if item.get("key")
    ]
    return {
        "planningDetail": {
            "todoItems": normalized_items,
            "currentKey": current_key,
            "totalCount": len(normalized_items),
            "completedCount": sum(1 for item in normalized_items if item["status"] == "completed"),
        }
    }


def merge_step_detail(current: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
    """StepRun detail 에 부분 patch 를 합친다.

    v1 에서는 detailJson 을 StepRun 아래에 보관하기 때문에,
    loop 실행 중 계산된 일부 정보만 덮어쓸 수 있게 얕은-중첩 merge 를 제공한다.
    """

    merged = build_default_step_detail()
    for source in [current or {}, patch or {}]:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = {**merged[key], **value}
            else:
                merged[key] = value
    return merged


def infer_semantic_status(*, lifecycle: str, operation_detail: dict[str, Any] | None = None) -> str:
    normalized_lifecycle = str(lifecycle or "pending").strip().lower()
    mapped = _SEMANTIC_STATUS_BY_LIFECYCLE.get(normalized_lifecycle, "running")
    if mapped not in {"running", "pending"}:
        return mapped

    detail = _safe_dict(operation_detail)
    operation_counts = _operation_status_counts(list(detail.get("operations") or []))
    total_count = _safe_int(detail.get("totalCount"))
    completed_count = _safe_int(detail.get("completedCount"))
    failed_count = _safe_int(detail.get("failedCount")) or operation_counts["failed"]
    canceled_count = _safe_int(detail.get("canceledCount")) or operation_counts["canceled"]
    waiting_count = _safe_int(detail.get("waitingCount")) or operation_counts["waiting"]
    if total_count == 0 and operation_counts:
        total_count = sum(operation_counts.values())
    if completed_count == 0 and operation_counts:
        completed_count = operation_counts["completed"]
    if failed_count > 0:
        return "failed"
    if canceled_count > 0 and completed_count + canceled_count >= total_count:
        return "canceled"
    if waiting_count > 0:
        return "waiting"
    if total_count > 0 and 0 < completed_count < total_count:
        return "partially_completed"
    return mapped


def normalize_operation_kind(kind: str | None) -> str:
    normalized = str(kind or "execute").strip().lower()
    if not normalized:
        return "execute"
    return _OPERATION_KIND_ALIASES.get(normalized, "execute")


def normalize_operation_status(status: str | None) -> str:
    normalized = str(status or "completed").strip().lower()
    if normalized == "cancelled":
        return "canceled"
    if normalized in {"pending", "running", "waiting", "completed", "failed", "canceled"}:
        return normalized
    return "completed"


def _merge_operations(*, existing_operations: list[dict[str, Any]], new_operations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    order: list[str] = []

    for operation in existing_operations:
        normalized = _normalize_operation(operation)
        if normalized is None:
            continue
        order.append(normalized["key"])
        merged.append(normalized)

    index_by_key = {operation["key"]: idx for idx, operation in enumerate(merged)}
    for operation in new_operations:
        normalized = _normalize_operation(operation)
        if normalized is None:
            continue
        existing_index = index_by_key.get(normalized["key"])
        if existing_index is None:
            index_by_key[normalized["key"]] = len(merged)
            order.append(normalized["key"])
            merged.append(normalized)
            continue
        merged[existing_index] = normalized

    return [merged[index_by_key[key]] for key in order if key in index_by_key]


def _normalize_operation(operation: dict[str, Any] | None) -> dict[str, Any] | None:
    raw = _safe_dict(operation)
    key = str(raw.get("key") or "").strip()
    if not key:
        return None

    raw_kind = str(raw.get("kind") or "execute").strip()
    normalized_kind = normalize_operation_kind(raw_kind)
    normalized = {
        "key": key,
        "title": str(raw.get("title") or key),
        "kind": normalized_kind,
        "status": normalize_operation_status(raw.get("status")),
        "summary": raw.get("summary"),
    }
    operation_error = _normalize_operation_error(raw, fallback_summary=normalized["summary"], status=normalized["status"])
    if operation_error is not None:
        normalized["error"] = operation_error
    if raw_kind and normalized_kind != raw_kind.lower():
        normalized["rawKind"] = raw_kind
    return normalized


def _normalize_operation_error(
    raw: dict[str, Any],
    *,
    fallback_summary: Any,
    status: str,
) -> dict[str, Any] | None:
    raw_error = raw.get("error")
    source = raw_error if isinstance(raw_error, dict) else {}
    retryable = source.get("retryable")
    if not isinstance(retryable, bool):
        retryable = raw.get("retryable")

    normalized: dict[str, Any] = {}
    code = _safe_text(source.get("code") or raw.get("error_code") or raw.get("errorCode") or raw.get("code"))
    message = _safe_text(
        source.get("message")
        or raw.get("error_message")
        or raw.get("errorMessage")
        or (raw_error if isinstance(raw_error, str) else None)
    )
    error_type = _safe_text(source.get("type") or raw.get("error_type") or raw.get("errorType"))

    if code:
        normalized["code"] = code
    if message:
        normalized["message"] = message
    if error_type:
        normalized["type"] = error_type
    if isinstance(retryable, bool):
        normalized["retryable"] = retryable

    if not normalized and status == "failed":
        summary = _safe_text(fallback_summary)
        if summary:
            normalized["message"] = summary

    return normalized or None


def _operation_status_counts(operations: list[dict[str, Any]]) -> dict[str, int]:
    counts = {
        "pending": 0,
        "running": 0,
        "waiting": 0,
        "completed": 0,
        "failed": 0,
        "canceled": 0,
    }
    for operation in operations:
        status = normalize_operation_status(_safe_dict(operation).get("status"))
        counts[status] = counts.get(status, 0) + 1
    return counts


def _safe_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_text(value: Any, *, max_length: int = 500) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.strip().split())
    if not text:
        return None
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text
