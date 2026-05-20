from __future__ import annotations

from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request

from app.api.deps.http_auth import authenticate_http_user, ensure_owner
from app.api.deps.openapi_auth import document_bearer_auth
from app.api.deps.task_context import TaskContext, get_task_context
from app.api.memory_context import attach_persistent_memory_context, select_memory_recall_query
from app.api.memory_mark_used import mark_used_recalled_memories
from app.api.memory_observation import attach_memory_observation_to_task
from app.core.time import utc_now
from app.contracts.task.step_status import StepStatus
from app.contracts.task.task_request import CreateTaskRequest, ResumeTaskRequest
from app.contracts.task.task_response import (
    ActiveTaskRunCurrentStepResponse,
    ActiveTaskRunListItemResponse,
    ActiveTaskRunListResponse,
    PendingApprovalResponse,
    StepRunResponse,
    StepRunSummaryResponse,
    TaskEventResponse,
    TaskRunDisplayContextResponse,
    TaskRunFlowActivityResponse,
    TaskRunFlowEdgeResponse,
    TaskRunFlowNodeResponse,
    TaskRunFlowResponse,
    TaskRunFlowSemanticResponse,
    TaskRunFlowWorkerSessionResponse,
    TaskRunListItemResponse,
    TaskRunListResponse,
    TaskRunResponse,
)
from app.contracts.task.task_status import TaskStatus
from app.domain.orchestration.contracts import OrchestrationRequest
from app.domain.tasks.display_context import build_task_display_context
from app.domain.tasks.models import StepRun
from app.domain.work import WorkService

router = APIRouter(prefix="/taskRuns", tags=["taskRuns"], dependencies=[Depends(document_bearer_auth)])

_ACTIVE_TASK_STATUSES = [status.value for status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.BLOCKED)]
_RECENT_TERMINAL_TASK_STATUSES = [status.value for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED)]
_ACTIVE_STEP_STATUSES = {status.value for status in (StepStatus.PENDING, StepStatus.RUNNING, StepStatus.WAITING, StepStatus.BLOCKED)}
_RECENT_ACTIVE_TTL_SECONDS = 300
_TASK_TITLE_FALLBACKS = {
    "agent.loop": "agent loop 실행",
}


def _normalize_session_id(session_id: str | None) -> str | None:
    if session_id is not None:
        normalized = session_id.strip()
        if normalized:
            return normalized
    return None


def _reject_removed_session_aliases(request: Request) -> None:
    removed = sorted({"productSessionId", "sessionKey"}.intersection(request.query_params.keys()))
    if removed:
        raise HTTPException(status_code=422, detail=f"removed session query parameter: {', '.join(removed)}; use sessionId")


def _select_page_size(request: Request, page_size: int) -> int:
    if "pageSize" in request.query_params or "page_size" not in request.query_params:
        return page_size
    raw_legacy_page_size = str(request.query_params.get("page_size") or "").strip()
    try:
        legacy_page_size = int(raw_legacy_page_size)
    except ValueError as error:
        raise HTTPException(status_code=422, detail="page_size must be an integer") from error
    if legacy_page_size < 1 or legacy_page_size > 20:
        raise HTTPException(status_code=422, detail="page_size must be between 1 and 20")
    return legacy_page_size


def _normalize_task_status_filter(raw_status: str) -> str | None:
    normalized = (raw_status or "ALL").strip().upper()
    if normalized == "ALL":
        return None
    if normalized not in {status.value for status in TaskStatus}:
        raise HTTPException(status_code=400, detail=f"invalid status filter: {raw_status}")
    return normalized


def _select_current_step(task, steps: list[StepRun]) -> StepRun | None:
    """상세/목록 양쪽에서 보여 줄 대표 StepRun 을 고른다.

    아직 여러 step 이 쌓이지 않는 MVP 구조라도,
    앞으로 멀티 스텝으로 확장될 것을 감안해 활성 step 우선 규칙을 고정해 둔다.
    """

    if task.current_step_run_id:
        for step in steps:
            if step.step_run_id == task.current_step_run_id:
                return step
    for step in steps:
        if step.status in _ACTIVE_STEP_STATUSES:
            return step
    return steps[-1] if steps else None


def _truncate_text(value: str, *, limit: int = 56) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"



def _find_first_scalar(payload: dict) -> str | None:
    for value in payload.values():
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float, bool)):
            return str(value)
    return None



def _summarize_task_input_payload(payload: dict) -> str | None:
    """Task 목록에서 사용자 의도를 빠르게 파악할 수 있도록 입력을 한 줄로 요약한다."""

    preferred_keys = ["prompt", "message", "subject", "title", "query", "content", "text"]
    for key in preferred_keys:
        raw_value = payload.get(key)
        if isinstance(raw_value, str) and raw_value.strip():
            return _truncate_text(raw_value)
    first_scalar = _find_first_scalar(payload)
    if first_scalar:
        return _truncate_text(first_scalar)
    if payload:
        return _truncate_text(str(payload))
    return None



def _display_task_title(task, *, input_summary: str | None) -> str:
    raw_title = (task.title or "").strip()
    if raw_title and raw_title != task.task_type:
        return raw_title
    if task.task_type in _TASK_TITLE_FALLBACKS:
        return _TASK_TITLE_FALLBACKS[task.task_type]
    if input_summary:
        return _truncate_text(input_summary, limit=28)
    return task.task_type


def _display_context_response(task, step: StepRun | None = None) -> TaskRunDisplayContextResponse:
    return TaskRunDisplayContextResponse.model_validate(build_task_display_context(task, step))


def _build_task_list_item(task, steps: list[StepRun]) -> TaskRunListItemResponse:
    current_step = _select_current_step(task, steps)
    current_step_response = None
    if current_step is not None:
        current_step_response = StepRunSummaryResponse.model_validate(current_step, from_attributes=True)
        current_step_response.display_context = _display_context_response(task, current_step)
    input_summary = _summarize_task_input_payload(task.input_payload)
    return TaskRunListItemResponse(
        task_run_id=task.task_run_id,
        task_type=task.task_type,
        session_key=task.session_key,
        status=task.status,
        title=_display_task_title(task, input_summary=input_summary),
        input_summary=input_summary,
        step_count=len(steps),
        progress_summary=task.progress_summary,
        created_at=task.created_at,
        updated_at=task.updated_at,
        current_step=current_step_response,
        display_context=_display_context_response(task),
    )


def _build_active_task_item(
    task,
    steps: list[StepRun],
    *,
    source: str,
    pending_approval: PendingApprovalResponse | None = None,
) -> ActiveTaskRunListItemResponse:
    current_step = _select_current_step(task, steps)
    current_step_response = None
    if current_step is not None:
        current_step_response = ActiveTaskRunCurrentStepResponse(
            step_run_id=current_step.step_run_id,
            title=current_step.title,
            status=current_step.status,
            display_context=_display_context_response(task, current_step),
        )
    input_summary = _summarize_task_input_payload(task.input_payload)
    return ActiveTaskRunListItemResponse(
        task_run_id=task.task_run_id,
        source=source,
        session_key=task.session_key,
        status=task.status,
        title=_display_task_title(task, input_summary=input_summary),
        current_step_run_id=task.current_step_run_id,
        current_step=current_step_response,
        updated_at=task.updated_at,
        wait_reason=(task.wait_payload or {}).get("reason"),
        pending_approval=pending_approval,
        display_context=_display_context_response(task),
    )


def _projection_steps(context: TaskContext, task_run_id: str) -> list[StepRun]:
    """Redis projection에 남은 StepRun snapshot을 순서대로 복원한다."""

    projection = context.task_projection_store
    if projection is None:
        return []
    steps: list[StepRun] = []
    for step_run_id in projection.list_task_steps(task_run_id):
        step = projection.get_step_snapshot(step_run_id)
        if step is not None:
            steps.append(step)
    return steps


def _build_active_items_from_projection(
    *,
    session_key: str,
    context: TaskContext,
) -> dict[str, ActiveTaskRunListItemResponse]:
    """Redis projection이 살아 있으면 active 목록을 DB 조회 전에 빠르게 만든다."""

    projection = context.task_projection_store
    if projection is None:
        return {}

    items_by_task_run_id: dict[str, ActiveTaskRunListItemResponse] = {}
    for task_run_id in projection.list_active_task_ids(session_key=session_key):
        task = projection.get_task_snapshot(task_run_id)
        if task is None:
            continue
        steps = _projection_steps(context, task.task_run_id)
        pending_approval = _build_pending_approval_response(context.repository.get_open_approval(task.task_run_id))
        items_by_task_run_id[task.task_run_id] = _build_active_task_item(
            task,
            steps,
            source="active",
            pending_approval=pending_approval,
        )
    return items_by_task_run_id


def _build_pending_approval_response(approval: dict | None) -> PendingApprovalResponse | None:
    """저장소의 approval row를 UI/API가 쓰는 pending approval 응답으로 정규화한다."""

    if approval is None or approval.get("status") != "PENDING":
        return None
    request_payload = approval.get("request_payload") or {}
    reason = request_payload.get("reason") or request_payload.get("approvalReason")
    tool_call_id = (
        request_payload.get("pending_tool_call_id")
        or request_payload.get("tool_call_id")
        or request_payload.get("toolCallId")
    )
    tool_name = (
        request_payload.get("pending_tool_name")
        or request_payload.get("tool_name")
        or request_payload.get("toolName")
    )
    return PendingApprovalResponse(
        approval_id=approval["approval_id"],
        step_run_id=approval.get("step_run_id"),
        status=approval["status"],
        reason=reason,
        tool_call_id=tool_call_id,
        tool_name=tool_name,
        requested_at=approval.get("created_at"),
        can_approve=True,
        can_reject=True,
    )


def _build_task_response(task, context: TaskContext) -> TaskRunResponse:
    """TaskRun 응답에는 현재 열려 있는 approval 정보를 함께 붙인다."""

    response = TaskRunResponse.model_validate(task, from_attributes=True)
    response.pending_approval = _build_pending_approval_response(context.repository.get_open_approval(task.task_run_id))
    response.display_context = _display_context_response(task)
    return response


def _has_active_task_for_owner_session(context: TaskContext, *, owner_key: str, session_key: str) -> bool:
    """sessionId 중복 실행 제한은 인증 owner 범위 안에서만 적용한다."""

    active_total = context.repository.count_tasks_by_statuses(_ACTIVE_TASK_STATUSES, session_key=session_key, owner_key=owner_key)
    active_tasks = context.repository.list_tasks_by_statuses(
        _ACTIVE_TASK_STATUSES,
        session_key=session_key,
        owner_key=owner_key,
        limit=max(active_total, 1),
        offset=0,
    )
    return bool(active_tasks)


def _recent_task_reference_time(task):
    return task.ended_at or task.updated_at or task.created_at


def _is_recent_terminal_task(task, *, now, ttl_seconds: int) -> bool:
    if task.status not in _RECENT_TERMINAL_TASK_STATUSES:
        return False
    reference_time = _recent_task_reference_time(task)
    if reference_time is None:
        return False
    return reference_time >= now - timedelta(seconds=ttl_seconds)


def _sort_active_snapshot_items(items: list[ActiveTaskRunListItemResponse]) -> list[ActiveTaskRunListItemResponse]:
    source_priority = {"active": 0, "recent": 1}
    return sorted(
        items,
        key=lambda item: (
            source_priority.get(item.source, 99),
            -(item.updated_at.timestamp() if item.updated_at is not None else 0),
        ),
    )


def _build_flow_activity_map(events: list) -> dict[str, list[TaskRunFlowActivityResponse]]:
    activity_by_step: dict[str, list[TaskRunFlowActivityResponse]] = {}
    for event in events:
        step_run_id = str(event.step_run_id or "").strip()
        if not step_run_id:
            continue
        activity_by_step.setdefault(step_run_id, []).append(
            TaskRunFlowActivityResponse(
                event_type=event.event_type,
                status=event.status,
                summary_message=event.summary_message,
                occurred_at=event.occurred_at,
            )
        )
    return activity_by_step


def _build_flow_nodes(task, steps: list[StepRun], *, activity_by_step: dict[str, list[TaskRunFlowActivityResponse]]) -> list[TaskRunFlowNodeResponse]:
    nodes: list[TaskRunFlowNodeResponse] = []
    for step in steps:
        semantic_detail = (step.detail_json or {}).get("semanticDetail") or {}
        agent_detail = (step.detail_json or {}).get("agentDetail") or {}
        semantic = None
        if semantic_detail:
            semantic = TaskRunFlowSemanticResponse(
                key=semantic_detail.get("semanticKey"),
                step=semantic_detail.get("semanticStep") or step.title,
                goal=semantic_detail.get("goal"),
                status=semantic_detail.get("status"),
            )
        worker_session = None
        worker_session_id = str(agent_detail.get("workerSessionId") or "").strip() or None
        if worker_session_id is not None:
            worker_session = TaskRunFlowWorkerSessionResponse(
                session_id=worker_session_id,
                status=agent_detail.get("status"),
                summary=agent_detail.get("summary"),
                agent_id=agent_detail.get("agentId"),
                profile_key=agent_detail.get("profileKey"),
            )
        nodes.append(
            TaskRunFlowNodeResponse(
                step_run_id=step.step_run_id,
                step_order=step.step_order,
                title=step.title,
                status=step.status,
                step_type=step.step_type,
                semantic=semantic,
                is_current=step.step_run_id == task.current_step_run_id,
                is_projected=bool((step.input_payload or {}).get("todo_key")),
                worker_session_id=worker_session_id,
                worker_session=worker_session,
                activity=activity_by_step.get(step.step_run_id, []),
            )
        )
    return nodes


def _build_step_response(
    task,
    step: StepRun,
    *,
    pending_approval: PendingApprovalResponse | None = None,
) -> StepRunResponse:
    semantic_detail = (step.detail_json or {}).get("semanticDetail") or {}
    agent_detail = (step.detail_json or {}).get("agentDetail") or {}
    semantic = None
    if semantic_detail:
        semantic = TaskRunFlowSemanticResponse(
            key=semantic_detail.get("semanticKey"),
            step=semantic_detail.get("semanticStep") or step.title,
            goal=semantic_detail.get("goal"),
            status=semantic_detail.get("status"),
        )
    worker_session = None
    worker_session_id = str(agent_detail.get("workerSessionId") or "").strip() or None
    if worker_session_id is not None:
        worker_session = TaskRunFlowWorkerSessionResponse(
            session_id=worker_session_id,
            status=agent_detail.get("status"),
            summary=agent_detail.get("summary"),
            agent_id=agent_detail.get("agentId"),
            profile_key=agent_detail.get("profileKey"),
        )
    return StepRunResponse(
        step_run_id=step.step_run_id,
        task_run_id=step.task_run_id,
        step_order=step.step_order,
        step_type=step.step_type,
        status=step.status,
        title=step.title,
        semantic=semantic,
        is_current=step.step_run_id == task.current_step_run_id,
        is_projected=bool((step.input_payload or {}).get("todo_key")),
        worker_session_id=worker_session_id,
        worker_session=worker_session,
        input_payload=step.input_payload,
        output_payload=step.output_payload,
        wait_payload=step.wait_payload,
        pending_approval=pending_approval,
        display_context=_display_context_response(task, step),
        detail_json=step.detail_json,
        summary_message=step.summary_message,
        error_message=step.error_message,
        created_at=step.created_at,
        updated_at=step.updated_at,
        started_at=step.started_at,
        ended_at=step.ended_at,
    )


def _build_flow_edges(steps: list[StepRun]) -> list[TaskRunFlowEdgeResponse]:
    edges: list[TaskRunFlowEdgeResponse] = []
    for previous_step, next_step in zip(steps, steps[1:]):
        edges.append(
            TaskRunFlowEdgeResponse(
                from_step_run_id=previous_step.step_run_id,
                to_step_run_id=next_step.step_run_id,
                relation="next",
            )
        )
    for step in steps:
        worker_session_id = str((((step.detail_json or {}).get("agentDetail") or {}).get("workerSessionId")) or "").strip()
        if not worker_session_id:
            continue
        edges.append(
            TaskRunFlowEdgeResponse(
                from_step_run_id=step.step_run_id,
                to_agent_session_id=worker_session_id,
                relation="delegates_to",
            )
        )
    return edges


def _events_from_projection(
    context: TaskContext,
    task_run_id: str,
    *,
    after_sequence: int | None,
    limit: int,
) -> list[dict[str, Any]]:
    """재연결 복구용 recent event projection을 sequence window로 잘라낸다."""

    projection = context.task_projection_store
    if projection is None:
        return []

    events = projection.list_recent_events(task_run_id)
    if after_sequence is not None:
        events = [event for event in events if int(event.get("sequence") or 0) > after_sequence]
    return events[:limit]


@router.get(
    "",
    response_model=TaskRunListResponse,
    summary="TaskRun(사용자 요청 실행 묶음) 목록 조회",
    description=(
        "현재 사용자의 TaskRun 목록을 페이지 단위로 조회합니다. "
        "TaskRun은 사용자가 한 번 보낸 요청이 시작부터 완료/실패/취소될 때까지 이어지는 실행 묶음입니다. "
        "프론트 목록 화면, 운영 확인, 재현 테스트에서 사용합니다. "
        "sessionId를 넣으면 특정 AI 세션에서 실행된 TaskRun만 조회합니다."
    ),
)
async def list_tasks(
    request: Request,
    page: int = Query(default=1, ge=1, description="페이지 번호입니다. 1부터 시작합니다."),
    page_size: int = Query(default=8, ge=1, le=20, alias="pageSize", description="한 페이지에 가져올 TaskRun 개수입니다. 최소 1, 최대 20입니다."),
    status: str = Query(
        default="ALL",
        description="상태 필터입니다. `ALL`, `PENDING`, `RUNNING`, `WAITING`, `BLOCKED`, `COMPLETED`, `FAILED`, `CANCELED` 중 하나를 넣습니다.",
    ),
    session_id: str | None = Query(
        default=None,
        alias="sessionId",
        description="sessionId(AI 세션 ID)로 TaskRun 목록을 좁힙니다.",
    ),
    context: TaskContext = Depends(get_task_context),
) -> TaskRunListResponse:
    user = await authenticate_http_user(request)
    _reject_removed_session_aliases(request)
    page_size = _select_page_size(request, page_size)
    session_key = _normalize_session_id(session_id)
    status_filter = _normalize_task_status_filter(status)
    offset = (page - 1) * page_size
    tasks = context.repository.list_tasks(status=status_filter, session_key=session_key, limit=page_size, offset=offset)
    if user is not None:
        tasks = [task for task in tasks if str(task.owner_key) == str(user.user_id)]
    total_count = context.repository.count_tasks(status=status_filter, session_key=session_key)
    if user is not None:
        # repository 계약이 owner filter를 아직 직접 받지 않으므로 인증 사용자의 현재 page 범위만 노출한다.
        total_count = len(tasks)
    items = [_build_task_list_item(task, context.repository.list_steps(task.task_run_id)) for task in tasks]
    return TaskRunListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total_count=total_count,
        has_previous=page > 1,
        has_next=offset + len(items) < total_count,
        status_filter=status_filter or "ALL",
    )


@router.get(
    "/active",
    response_model=ActiveTaskRunListResponse,
    summary="현재 세션의 활성 TaskRun 조회",
    description=(
        "sessionId 기준으로 아직 진행 중인 TaskRun과 방금 끝난 TaskRun을 조회합니다. "
        "`source=active`는 실행/대기 중인 작업, `source=recent`는 최근 300초 안에 완료/실패/취소된 작업입니다. "
        "프론트가 새로고침 후 현재 작업 상태를 복원할 때 사용합니다."
    ),
)
async def list_active_tasks(
    request: Request,
    session_id: str | None = Query(
        default=None,
        alias="sessionId",
        description="sessionId(AI 세션 ID)입니다. 같은 세션의 현재 작업을 찾을 때 사용합니다.",
    ),
    context: TaskContext = Depends(get_task_context),
) -> ActiveTaskRunListResponse:
    user = await authenticate_http_user(request)
    _reject_removed_session_aliases(request)
    session_key = _normalize_session_id(session_id)
    now = utc_now()
    items_by_task_run_id = (
        _build_active_items_from_projection(session_key=session_key, context=context)
        if session_key
        else {}
    )

    owner_key = str(user.user_id) if user is not None else None
    active_total_count = context.repository.count_tasks_by_statuses(_ACTIVE_TASK_STATUSES, session_key=session_key, owner_key=owner_key)
    active_tasks = context.repository.list_tasks_by_statuses(
        _ACTIVE_TASK_STATUSES,
        session_key=session_key,
        owner_key=owner_key,
        limit=max(active_total_count, 1),
        offset=0,
    )

    recent_total_pool = context.repository.count_tasks_by_statuses(_RECENT_TERMINAL_TASK_STATUSES, session_key=session_key, owner_key=owner_key)
    recent_candidates = context.repository.list_tasks_by_statuses(
        _RECENT_TERMINAL_TASK_STATUSES,
        session_key=session_key,
        owner_key=owner_key,
        limit=max(recent_total_pool, 1),
        offset=0,
    )

    for task in active_tasks:
        if task.task_run_id in items_by_task_run_id:
            continue
        steps = context.repository.list_steps(task.task_run_id)
        pending_approval = _build_pending_approval_response(context.repository.get_open_approval(task.task_run_id))
        items_by_task_run_id[task.task_run_id] = _build_active_task_item(
            task,
            steps,
            source="active",
            pending_approval=pending_approval,
        )

    for task in recent_candidates:
        if not _is_recent_terminal_task(task, now=now, ttl_seconds=_RECENT_ACTIVE_TTL_SECONDS):
            continue
        if task.task_run_id in items_by_task_run_id:
            continue
        steps = context.repository.list_steps(task.task_run_id)
        items_by_task_run_id[task.task_run_id] = _build_active_task_item(task, steps, source="recent")

    items = _sort_active_snapshot_items(list(items_by_task_run_id.values()))
    if user is not None:
        filtered_items = []
        for item in items:
            task = context.repository.get_task(item.task_run_id)
            if task is not None and str(task.owner_key) == str(user.user_id):
                filtered_items.append(item)
        items = filtered_items
    return ActiveTaskRunListResponse(
        items=items,
        total_count=len(items),
    )


@router.post(
    "",
    response_model=TaskRunResponse,
    summary="세션 루틴/디버깅용 TaskRun 직접 실행",
    description=(
        "메시지 저장 없이 TaskRun을 바로 생성해 Orchestrator(작업 시작/재개를 맡는 내부 실행 관리자)에 실행을 맡깁니다. "
        "일반 채팅 입력은 `/sessions/messages` 또는 `/sessions/{sessionId}/messages`를 사용합니다. "
        "이 API는 세션 루틴 즉시 실행, 예약/외부 트리거, 운영 재현 테스트처럼 이미 실행할 세션과 입력이 정해진 경우에 사용합니다. "
        "Authorization 토큰이 있으면 토큰의 사용자 ID가 owner(작업 소유자)가 됩니다. "
        "같은 사용자와 같은 sessionId 안에서는 동시에 실행 중인 TaskRun을 하나만 허용합니다."
    ),
)
async def create_task(request: Request, payload: CreateTaskRequest, context: TaskContext = Depends(get_task_context)) -> TaskRunResponse:
    user = await authenticate_http_user(request)
    owner_key = user.user_id if user is not None else payload.owner_key
    task_input = dict(payload.input_payload)
    await attach_persistent_memory_context(
        app_state=request.app.state,
        task_input=task_input,
        user_id=str(owner_key),
        query=select_memory_recall_query(task_input),
        workspace_key=user.workspace_key if user is not None else None,
        force_workspace_key=user is not None and bool(user.workspace_key),
    )
    orchestrator = request.app.state.orchestrator
    task_execution_supervisor = getattr(request.app.state, "task_execution_supervisor", None)
    active_lock_task_id = None
    if payload.session_key:
        if _has_active_task_for_owner_session(context, owner_key=owner_key, session_key=payload.session_key):
            # 같은 사용자의 동일 AI 세션만 막아 다른 사용자의 같은 문자열 session id와 충돌하지 않게 한다.
            raise HTTPException(status_code=409, detail="active task already exists in this session")
        projection = context.task_projection_store
        if projection is not None:
            active_lock_task_id = f"pending:{owner_key}:{payload.session_key}"
            if not projection.acquire_active_session_lock(payload.session_key, active_lock_task_id, owner_key=owner_key):
                raise HTTPException(status_code=409, detail="active task already exists in this session")
    try:
        orchestration_request = OrchestrationRequest(
            owner_key=owner_key,
            session_key=payload.session_key,
            input_payload=task_input,
        )
        if task_execution_supervisor is not None:
            task = await task_execution_supervisor.submit(orchestration_request)
        else:
            task = await orchestrator.start(orchestration_request)
        if payload.session_key and active_lock_task_id and context.task_projection_store is not None:
            context.task_projection_store.release_active_session_lock(payload.session_key, active_lock_task_id, owner_key=owner_key)
            context.task_projection_store.acquire_active_session_lock(payload.session_key, task.task_run_id, owner_key=owner_key)
        if task_execution_supervisor is None:
            mark_used_observation = await mark_used_recalled_memories(
                app_state=request.app.state,
                task_input=dict(task.input_payload or {}),
                user_id=str(owner_key),
                assistant_message=_assistant_content_from_task_result(task),
                task_run_id=task.task_run_id,
            )
            attach_memory_observation_to_task(
                task=task,
                repository=context.repository,
                mark_used=mark_used_observation,
            )
    except KeyError as error:
        if payload.session_key and active_lock_task_id and context.task_projection_store is not None:
            context.task_projection_store.release_active_session_lock(payload.session_key, active_lock_task_id, owner_key=owner_key)
        raise HTTPException(status_code=404, detail=f"unknown execution route: {error.args[0]}") from error
    except ValueError as error:
        if payload.session_key and active_lock_task_id and context.task_projection_store is not None:
            context.task_projection_store.release_active_session_lock(payload.session_key, active_lock_task_id, owner_key=owner_key)
        raise HTTPException(status_code=400, detail=str(error)) from error
    work_repository = getattr(request.app.state, "work_repository", None)
    if work_repository is not None:
        WorkService(work_repository).apply_linked_task_result(task=task)
    return _build_task_response(task, context)


@router.get(
    "/{taskRunId}/flow",
    response_model=TaskRunFlowResponse,
    summary="TaskRun 진행 흐름 조회",
    description=(
        "UI 진행도/그래프용 현재 스냅샷입니다. StepRun(작업 안의 세부 단계), semantic step(계획상 의미 단계), "
        "worker/subagent가 만든 AgentSession(하위 AI 대화/도구 기록 세션)의 관계를 nodes/edges로 반환합니다. "
        "현재 그래프 복원은 `/flow`, 시간순 누락 복구는 `/events`, worker 대화 추적은 `/agentSessions/{agentSessionId}/messages`를 사용합니다."
    ),
)
async def get_task_flow(
    request: Request,
    taskRunId: str = Path(..., description="조회할 TaskRun ID입니다. `POST /taskRuns` 응답의 `task_run_id` 값을 넣습니다."),
    context: TaskContext = Depends(get_task_context),
) -> TaskRunFlowResponse:
    task_run_id = taskRunId
    user = await authenticate_http_user(request)
    task = context.repository.get_task(task_run_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    ensure_owner(user, task.owner_key)
    steps = context.repository.list_steps(task_run_id)
    events = context.repository.list_events(task_run_id)
    input_summary = _summarize_task_input_payload(task.input_payload)
    activity_by_step = _build_flow_activity_map(events)
    return TaskRunFlowResponse(
        task_run_id=task.task_run_id,
        status=task.status,
        title=_display_task_title(task, input_summary=input_summary),
        current_step_run_id=task.current_step_run_id,
        summary=task.progress_summary,
        pending_approval=_build_pending_approval_response(context.repository.get_open_approval(task.task_run_id)),
        nodes=_build_flow_nodes(task, steps, activity_by_step=activity_by_step),
        edges=_build_flow_edges(steps),
    )


@router.get(
    "/{taskRunId}",
    response_model=TaskRunResponse,
    summary="TaskRun 상세 조회",
    description="TaskRun의 현재 상태, 입력, 결과, 승인 대기 정보, 진행 요약을 조회합니다.",
)
async def get_task(
    request: Request,
    taskRunId: str = Path(..., description="조회할 TaskRun ID입니다."),
    context: TaskContext = Depends(get_task_context),
) -> TaskRunResponse:
    task_run_id = taskRunId
    user = await authenticate_http_user(request)
    task = context.repository.get_task(task_run_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    ensure_owner(user, task.owner_key)
    return _build_task_response(task, context)


@router.get(
    "/{taskRunId}/steps",
    response_model=list[StepRunResponse],
    summary="StepRun 목록 조회",
    description=(
        "TaskRun(사용자 요청 하나의 실행 묶음)에 속한 StepRun 목록을 순서대로 조회합니다. "
        "여기서 StepRun은 TaskRun 내부에서 실제로 저장된 세부 실행 단위입니다. "
        "각 StepRun의 step_run_id, 상태, 제목, 입력/결과 요약, 승인 대기 정보를 확인할 때 사용합니다."
    ),
)
async def list_steps(
    request: Request,
    taskRunId: str = Path(..., description="StepRun 목록을 조회할 부모 TaskRun ID입니다."),
    context: TaskContext = Depends(get_task_context),
) -> list[StepRunResponse]:
    task_run_id = taskRunId
    user = await authenticate_http_user(request)
    task = context.repository.get_task(task_run_id)
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    ensure_owner(user, task.owner_key)
    steps = context.repository.list_steps(task_run_id)
    pending_approval = _build_pending_approval_response(context.repository.get_open_approval(task_run_id))
    return [
        _build_step_response(
            task,
            step,
            pending_approval=pending_approval if pending_approval and pending_approval.step_run_id == step.step_run_id else None,
        )
        for step in steps
    ]


@router.get(
    "/{taskRunId}/events",
    response_model=list[TaskEventResponse],
    summary="TaskRun event 증분 조회",
    description=(
        "WebSocket 유실/재연결 복구용 append-only event(시간순 진행 기록) 목록입니다. "
        "실시간 연결은 `/realtime/user/ws`에 접속한 뒤 `auth.start` -> `auth.ok` -> `subscribe.task` -> `task.event` 순서로 받습니다. "
        "`task.event.sequence`가 있으면 재연결 후 `afterSequence`에 마지막 sequence를 넣어 누락분을 복구합니다. "
        "클라이언트 전송 예시는 `{\"type\":\"auth.start\",\"accessToken\":\"...\"}` 다음 "
        "`{\"type\":\"subscribe.task\",\"taskRunId\":\"task_...\"}`입니다."
    ),
)
async def list_events(
    request: Request,
    taskRunId: str = Path(..., description="event를 조회할 TaskRun ID입니다."),
    after_sequence: int | None = Query(default=None, ge=0, alias="afterSequence", description="이 sequence보다 큰 event만 조회합니다. 처음 조회할 때는 비워 둡니다."),
    limit: int = Query(default=200, ge=1, le=500, description="최대 event 개수입니다. 최소 1, 최대 500입니다."),
    context: TaskContext = Depends(get_task_context),
) -> list[TaskEventResponse]:
    task_run_id = taskRunId
    user = await authenticate_http_user(request)
    task = context.repository.get_task(task_run_id)
    if task is None and user is not None:
        raise HTTPException(status_code=404, detail="task not found")
    if task is not None:
        ensure_owner(user, task.owner_key)
    projected_events = _events_from_projection(
        context,
        task_run_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    if projected_events:
        return [TaskEventResponse.model_validate(event, from_attributes=True) for event in projected_events]

    events = context.repository.list_events(task_run_id)
    return [TaskEventResponse.model_validate(event, from_attributes=True) for event in events[:limit]]


def _assistant_content_from_task_result(task: Any) -> str:
    result_payload = dict(getattr(task, "result_payload", {}) or {})
    for key in ("text", "output_text", "summary", "message", "content"):
        value = result_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if getattr(task, "progress_summary", None):
        return str(task.progress_summary)
    return ""


@router.post(
    "/{taskRunId}/resume",
    response_model=TaskRunResponse,
    summary="승인/추가 입력 후 TaskRun 재개",
    description=(
        "승인 대기나 사용자 추가 입력 때문에 멈춘 TaskRun을 다시 진행합니다. "
        "`pendingApproval.approval_id`가 있으면 요청 본문의 `approval_id`로 그대로 전달합니다."
    ),
)
async def resume_task(
    request: Request,
    payload: ResumeTaskRequest,
    taskRunId: str = Path(..., description="재개할 TaskRun ID입니다."),
    context: TaskContext = Depends(get_task_context),
) -> TaskRunResponse:
    task_run_id = taskRunId
    user = await authenticate_http_user(request)
    current_task = context.repository.get_task(task_run_id)
    if current_task is None:
        raise HTTPException(status_code=404, detail="task not found")
    ensure_owner(user, current_task.owner_key)
    try:
        task = await request.app.state.orchestrator.resume(
            task_run_id=task_run_id,
            approval_id=payload.approval_id or "",
            payload=payload.payload,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _build_task_response(task, context)


@router.post(
    "/{taskRunId}/cancel",
    response_model=TaskRunResponse,
    summary="TaskRun 취소",
    description="아직 완료되지 않은 TaskRun을 취소합니다. 취소 후 상태는 보통 `CANCELED`가 됩니다.",
)
async def cancel_task(
    request: Request,
    taskRunId: str = Path(..., description="취소할 TaskRun ID입니다."),
    context: TaskContext = Depends(get_task_context),
) -> TaskRunResponse:
    task_run_id = taskRunId
    user = await authenticate_http_user(request)
    current_task = context.repository.get_task(task_run_id)
    if current_task is None:
        raise HTTPException(status_code=404, detail="task not found")
    ensure_owner(user, current_task.owner_key)
    try:
        task = await request.app.state.orchestrator.cancel(task_run_id=task_run_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="task not found") from None
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return _build_task_response(task, context)
