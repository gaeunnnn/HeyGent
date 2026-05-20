from __future__ import annotations

import json
import logging
import re

from app.contracts.task.step_status import StepStatus
from app.contracts.task.task_status import TaskStatus
from app.core.time import utc_now
from app.core.utils.ids import new_id
from app.domain.orchestration.agent.step_handler import StepHandler
from app.domain.orchestration.approval import ApprovalRuntime, ApprovalService
from app.domain.orchestration.delegation import ChildSessionLauncher, DelegateRuntime
from app.domain.orchestration.policies import (
    ensure_step_transition,
    ensure_task_transition,
    normalize_handler_outcome,
    semantic_lifecycle_for_status,
    step_is_terminal,
    task_is_terminal,
)
from app.domain.orchestration.runtime_planning import (
    Planner,
)
from app.api.http.device_tokens import get_fcm_tokens
from app.domain.notifications.fcm_sender import send_chat_notification
from app.domain.orchestration.runtime_planning.todo_state import (
    build_task_todo_payload,
    cancel_incomplete_task_todo_items,
    parse_task_todo_payload,
)
from app.domain.orchestration.result_inspector import OutcomeInspector
from app.domain.session.sessions.transcript_store import TranscriptStore
from app.domain.work import WorkComment, WorkService
from app.domain.tasks.detail import (
    build_model_decision_detail,
    build_planning_detail,
    build_semantic_step_detail,
    infer_semantic_status,
    merge_step_detail,
    semantic_key_of,
)
from app.domain.tasks.display_context import build_task_display_context
from app.domain.tasks.events import build_task_event
from app.domain.tasks.repository import TaskRepository
from app.domain.tasks.models import StepRun, TaskRun


logger = logging.getLogger(__name__)
TRACKED_SKILL_TOOL_NAMES = {"skill.execute"}


class TaskEngine:
    """Coordinate task execution, approval waiting, and exact-step resume."""

    def __init__(
        self,
        repository: TaskRepository,
        broadcaster,
        approval_service: ApprovalService,
        child_session_launcher: ChildSessionLauncher,
        planner: Planner,
        tool_registry,
        session_store: TranscriptStore | None = None,
        work_repository=None,
        agent_repository=None,
        skill_repository=None,
        settings=None,
        iot_display_adapter=None,
    ) -> None:
        self.repository = repository
        self.broadcaster = broadcaster
        self.approval_service = approval_service
        self.child_session_launcher = child_session_launcher
        self.planner = planner
        self.tool_registry = tool_registry
        self.session_store = session_store
        self.work_repository = work_repository
        self.agent_repository = agent_repository
        self.skill_repository = skill_repository
        self.settings = settings
        self.iot_display_adapter = iot_display_adapter
        self.approval_runtime = ApprovalRuntime()
        self.delegate_runtime = DelegateRuntime(child_session_launcher, session_store=session_store)
        self.outcome_inspector = OutcomeInspector()
        self.step_handler = StepHandler()

    async def run(self, *, task: TaskRun, handler) -> TaskRun:
        saved = self.repository.create_direct_task(task)
        await self._emit("task.created", saved)
        return await self._execute_initial(task=saved, handler=handler, resume_payload=None)

    async def enqueue_pending(self, *, task: TaskRun) -> TaskRun:
        saved = self.repository.create_pending_task(task)
        await self._emit("task.created", saved)
        return saved

    async def run_claimed(self, *, task: TaskRun, handler) -> TaskRun:
        latest = self.repository.get_task(task.task_run_id) or task
        queue_status = str(getattr(latest, "queue_status", "") or "")
        claim_owner = str(getattr(latest, "claim_owner", "") or "")
        # run_claimed는 supervisor가 durable queue에서 claim한 작업만 실행한다.
        # direct 실행이 이 경로로 들어오면 같은 TaskRun을 두 실행자가 동시에 돌릴 수 있다.
        if queue_status not in {"claimed", "running"} or not claim_owner:
            raise RuntimeError(f"TaskRun is not claimed by a supervisor worker: {task.task_run_id}")
        return await self._execute_initial(task=task, handler=handler, resume_payload=None)

    async def _execute_initial(self, *, task: TaskRun, handler, resume_payload: dict | None) -> TaskRun:
        ensure_task_transition(task.status, TaskStatus.RUNNING)
        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or utc_now()
        task.wait_payload = {}
        step = self.planner.materialize_runtime_step(
            task=task,
            handler=handler,
            input_payload=task.input_payload,
            step_order=1,
        )
        ensure_step_transition(step.status, StepStatus.RUNNING)
        step.status = StepStatus.RUNNING
        step.started_at = step.started_at or task.started_at
        task.current_step_run_id = step.step_run_id
        self.repository.create_step(step)
        self.repository.update_task(task)
        self._touch_linked_work_run(task)
        await self._emit("task.started", task)
        await self._emit("step.created", task, step)
        await self._emit("step.started", task, step)

        try:
            progress_sink = self._build_progress_sink(task=task, step=step)
            outcome = normalize_handler_outcome(
                await self.step_handler.execute(
                    handler=handler,
                    task=task,
                    step=step,
                    resume_payload=resume_payload,
                    progress_sink=progress_sink,
                    delegate_executor=self._build_delegate_executor(task=task, handler=handler, progress_sink=progress_sink),
                    session_agent_executor=self._build_session_agent_work_executor(task=task, handler=handler, progress_sink=progress_sink),
                )
            )
        except Exception as error:
            outcome = self._build_handler_failure_outcome(error)
        live_step = self.repository.get_step(task.current_step_run_id) if task.current_step_run_id else None
        return await self._apply_outcome(task=task, step=live_step or step, handler=handler, outcome=outcome)

    async def resume(self, *, task: TaskRun, handler, approval_id: str, payload: dict) -> TaskRun:
        approval = self.approval_service.resolve(approval_id, payload)
        if approval is None:
            raise KeyError(approval_id)

        step = self.repository.get_step(approval["step_run_id"])
        if step is None:
            raise KeyError(approval["step_run_id"])
        task.current_step_run_id = step.step_run_id
        self.approval_runtime.mark_resolved_step(step=step, approval_id=approval_id, response_payload=payload)
        step.detail_json = merge_step_detail(
            step.detail_json,
            build_semantic_step_detail(
                step_run_id=step.step_run_id,
                semantic_key=semantic_key_of(step.detail_json) or step.step_type,
                semantic_step=(step.detail_json.get("semanticDetail") or {}).get("semanticStep") or step.title or step.step_type,
                semantic_goal=(step.detail_json.get("semanticDetail") or {}).get("goal") or step.title or step.step_type,
                lifecycle="resuming",
                status=infer_semantic_status(lifecycle="resuming", operation_detail=step.detail_json.get("operationDetail")),
            ),
        )
        self.repository.update_step(step)
        await self._emit("approval.resolved", task, step, payload={"approval_id": approval_id, **payload})
        return await self._execute(task=task, step=step, handler=handler, resume_payload=payload)

    async def cancel_waiting(self, *, task: TaskRun) -> TaskRun:
        if task.status != TaskStatus.WAITING:
            raise ValueError("task is not waiting")
        if not task.current_step_run_id:
            raise ValueError("task waiting step is missing")

        step = self.repository.get_step(task.current_step_run_id)
        if step is None:
            raise KeyError(task.current_step_run_id)
        if step.status != StepStatus.WAITING:
            raise ValueError("current step is not waiting")

        wait_payload = dict(step.wait_payload or {})
        handler = self.tool_registry.resolve()

        approval = self.repository.get_open_approval(task.task_run_id)
        if approval is None:
            raise ValueError("no open approval")
        canceled_approval = self.approval_service.cancel(approval["approval_id"])
        if canceled_approval is None:
            raise ValueError("no open approval")

        canceled_at = utc_now()
        self.approval_runtime.mark_canceled_step(
            step=step,
            approval_id=canceled_approval["approval_id"],
            request_payload=canceled_approval.get("request_payload"),
        )
        self._record_pending_tool_cancellation(step=step, wait_payload=wait_payload, handler=handler)

        task.status = TaskStatus.CANCELED
        task.wait_payload = {}
        task.progress_summary = "작업이 취소되었습니다."
        task.current_step_run_id = step.step_run_id
        task.todo_state = build_task_todo_payload(cancel_incomplete_task_todo_items(task.todo_state))
        task.revision += 1
        task.ended_at = canceled_at

        step.status = StepStatus.CANCELED
        step.wait_payload = {}
        step.summary_message = "사용자 요청으로 취소됨"
        step.ended_at = canceled_at
        step.detail_json = merge_step_detail(
            step.detail_json,
            build_semantic_step_detail(
                step_run_id=step.step_run_id,
                semantic_key=semantic_key_of(step.detail_json) or step.step_type,
                semantic_step=(step.detail_json.get("semanticDetail") or {}).get("semanticStep") or step.title or step.step_type,
                semantic_goal=(step.detail_json.get("semanticDetail") or {}).get("goal") or step.title or step.step_type,
                lifecycle="canceled",
                status=infer_semantic_status(lifecycle="canceled", operation_detail=step.detail_json.get("operationDetail")),
            ),
        )

        self.repository.update_task(task)
        self.repository.update_step(step)

        if handler is not None:
            await self._sync_todo_steps(task=task, handler=handler)

        await self._emit(
            "approval.canceled",
            task,
            step,
            payload={"approval_id": canceled_approval["approval_id"]},
        )
        await self._emit("step.canceled", task, step)
        await self._emit("task.canceled", task, step)
        return task

    def _record_pending_tool_cancellation(self, *, step: StepRun, wait_payload: dict, handler) -> None:
        tool_result = self._build_canceled_pending_tool_result(wait_payload)
        if tool_result is None:
            return

        output_payload = dict(step.output_payload or {})
        tool_results = list(output_payload.get("tool_results") or [])
        if not any(str(item.get("tool_call_id") or "") == tool_result["tool_call_id"] for item in tool_results if isinstance(item, dict)):
            tool_results.append(tool_result)
        output_payload["tool_results"] = tool_results
        step.output_payload = output_payload

        session_store = self._session_store_from_handler(handler)
        transcript_session_id = str(wait_payload.get("transcript_session_id") or "").strip()
        if session_store is None or not transcript_session_id or session_store.get_session(transcript_session_id) is None:
            return

        result = tool_result["result"]
        content = result.get("content") if isinstance(result, dict) else None
        session_store.append_message(
            session_id=transcript_session_id,
            role="tool",
            content=str(content or json.dumps(result, ensure_ascii=False)),
            tool_name=tool_result["name"],
            tool_call_id=tool_result["tool_call_id"],
        )

    @staticmethod
    def _build_canceled_pending_tool_result(wait_payload: dict) -> dict | None:
        call_id = str(wait_payload.get("pending_tool_call_id") or "").strip()
        tool_name = str(wait_payload.get("pending_tool_name") or "").strip()
        args = wait_payload.get("pending_tool_arguments")
        if not call_id or not tool_name or not isinstance(args, dict):
            return None

        message = "task canceled before pending tool execution"
        return {
            "tool_call_id": call_id,
            "name": tool_name,
            "args": args,
            "result": {
                "ok": False,
                "content": f"Tool call canceled: {message}",
                "error": {
                    "code": "tool_canceled",
                    "message": message,
                    "tool_name": tool_name,
                },
                "canceled": True,
            },
        }

    @staticmethod
    def _session_store_from_handler(handler) -> TranscriptStore | None:
        loop_handler = getattr(handler, "loop_handler", None)
        return getattr(loop_handler, "session_store", None)

    async def _execute(self, *, task: TaskRun, step: StepRun, handler, resume_payload: dict | None) -> TaskRun:
        ensure_task_transition(task.status, TaskStatus.RUNNING)
        ensure_step_transition(step.status, StepStatus.RUNNING)

        task.status = TaskStatus.RUNNING
        task.started_at = task.started_at or utc_now()
        task.wait_payload = {}
        task.current_step_run_id = step.step_run_id
        step.status = StepStatus.RUNNING
        step.started_at = step.started_at or utc_now()
        step.detail_json = merge_step_detail(
            step.detail_json,
            build_semantic_step_detail(
                step_run_id=step.step_run_id,
                semantic_key=semantic_key_of(step.detail_json) or handler.spec.semantic_key or step.step_type,
                semantic_step=(step.detail_json.get("semanticDetail") or {}).get("semanticStep") or step.title or handler.spec.step_title,
                semantic_goal=(step.detail_json.get("semanticDetail") or {}).get("goal") or handler.spec.semantic_goal or step.title or handler.spec.step_title,
                lifecycle="running",
                status=infer_semantic_status(lifecycle="running", operation_detail=step.detail_json.get("operationDetail")),
            ),
        )
        self.repository.update_task(task)
        self.repository.update_step(step)
        self._touch_linked_work_run(task)
        await self._emit("task.started", task)
        await self._emit("step.started", task, step)

        try:
            progress_sink = self._build_progress_sink(task=task, step=step)
            outcome = normalize_handler_outcome(
                await self.step_handler.execute(
                    handler=handler,
                    task=task,
                    step=step,
                    resume_payload=resume_payload,
                    progress_sink=progress_sink,
                    delegate_executor=self._build_delegate_executor(task=task, handler=handler, progress_sink=progress_sink),
                    session_agent_executor=self._build_session_agent_work_executor(task=task, handler=handler, progress_sink=progress_sink),
                )
            )
        except Exception as error:
            # 이미 materialized 된 StepRun이 있으면 같은 anchor를 FAILED로 닫아
            # approval/resume과 이벤트 기준점이 바뀌지 않게 한다.
            outcome = self._build_handler_failure_outcome(error)
        return await self._apply_outcome(task=task, step=step, handler=handler, outcome=outcome)

    def _build_handler_failure_outcome(self, error: Exception) -> dict:
        error_message = self._safe_error_message(error)
        summary_message = "작업 처리 중 오류가 발생했습니다."
        retryable = self._handler_error_retryable(error)
        return {
            "task_status": TaskStatus.FAILED,
            "step_status": StepStatus.FAILED,
            "result_payload": {},
            "output_payload": {
                "error": {
                    "type": type(error).__name__,
                    "message": error_message,
                    "recovery": {
                        "diagnose": True,
                        "retryable": retryable,
                        "retry_attempted": False,
                        "retry_policy": "manual_or_next_loop",
                    },
                }
            },
            "wait_payload": {},
            "detail_json": build_model_decision_detail(
                action="diagnose_then_fail",
                action_summary="오류 원인을 기록하고 재시도 가능성을 남긴 뒤 종료했습니다.",
            ),
            "todo_state": {},
            "summary_message": summary_message,
            "error_message": error_message,
            "operations": [
                {
                    "key": "handler.diagnose",
                    "title": "오류 원인 기록",
                    "kind": "execute",
                    "status": "completed",
                    "summary": error_message,
                },
                {
                    "key": "handler.retry.unavailable",
                    "title": "재시도 후보 기록",
                    "kind": "execute",
                    "status": "waiting" if retryable else "completed",
                    "summary": "자동 재시도 없이 다음 판단 또는 수동 재개 대상으로 남겼습니다.",
                },
                {
                    "key": "handler.failure",
                    "title": "실행 실패",
                    "kind": "execute",
                    "status": "failed",
                    "summary": error_message,
                }
            ],
        }

    @staticmethod
    def _handler_error_retryable(error: Exception) -> bool:
        retryable_names = {
            "TimeoutError",
            "ConnectionError",
            "RuntimeError",
        }
        return type(error).__name__ in retryable_names

    @staticmethod
    def _safe_error_message(error: Exception) -> str:
        error_type = type(error).__name__
        raw_message = str(error).strip() or "상세 메시지가 없습니다."
        first_line = raw_message.splitlines()[0] if raw_message.splitlines() else raw_message
        compact_message = " ".join(first_line.split())
        redacted_message = TaskEngine._redact_sensitive_error_text(compact_message)
        if len(redacted_message) > 180:
            redacted_message = redacted_message[:177].rstrip() + "..."
        return f"{error_type}: {redacted_message}"

    @staticmethod
    def _redact_sensitive_error_text(message: str) -> str:
        redacted = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "[redacted]", message)
        redacted = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", redacted)
        redacted = re.sub(
            r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^,\s]+",
            r"\1=[redacted]",
            redacted,
        )
        return redacted

    async def _apply_task_outcome_without_step(self, *, task: TaskRun, outcome: dict) -> TaskRun:
        await self._ensure_skill_work_link_from_outcome(task=task, outcome=outcome)
        task_status = outcome["task_status"]
        if task_status == TaskStatus.WAITING:
            task_status = TaskStatus.FAILED
            outcome = {
                **outcome,
                "task_status": TaskStatus.FAILED,
                "error_message": "StepRun declaration is required before approval-gated tool execution.",
                "summary_message": "승인 필요 도구 실행 전에 현재 단계를 먼저 선언해야 합니다.",
            }

        ensure_task_transition(task.status, task_status)
        task.status = task_status
        task.current_step_run_id = None
        task.result_payload = outcome.get("result_payload", task.result_payload)
        task.todo_state = dict(outcome.get("todo_state") or task.todo_state)
        task.wait_payload = outcome.get("wait_payload", {})
        task.error_message = outcome.get("error_message")
        task.progress_summary = outcome.get("summary_message")
        task.revision += 1
        if task_is_terminal(task_status):
            task.ended_at = utc_now()
            task.todo_state = build_task_todo_payload(cancel_incomplete_task_todo_items(task.todo_state))
        self.repository.update_task(task)

        if task_status == TaskStatus.COMPLETED:
            await self._emit("task.completed", task, payload=task.result_payload)
            # FCM 푸시: 웹/다른 기기에서 보낸 메시지도 모바일에 동기화
            try:
                if task.session_key:
                    for fcm_token in get_fcm_tokens(str(task.owner_key)):
                        send_chat_notification(fcm_token, session_id=task.session_key, content="")
                    logger.info(f"FCM 발송 완료: owner={task.owner_key} session={task.session_key}")
                else:
                    logger.debug(f"FCM 스킵: token={bool(fcm_token)} session={task.session_key}")
            except Exception as e:
                logger.warning(f"FCM 발송 실패 (무시): {e}")
            return task

        if task_status == TaskStatus.FAILED:
            await self._emit("task.failed", task, payload={"error_message": task.error_message})
            return task

        if task_status == TaskStatus.CANCELED:
            await self._emit("task.canceled", task)
            return task

        await self._emit("task.updated", task)
        return task

    async def _apply_outcome(self, *, task: TaskRun, step: StepRun, handler, outcome: dict) -> TaskRun:
        outcome = await self.delegate_runtime.apply(task=task, step=step, outcome=outcome, repository=self.repository)
        # operation-only outcome 은 새 StepRun 생성 사유가 아니다. semanticKey 가 유지되는 한
        # result_inspector 가 기존 step.detail_json.operationDetail 에 operation 을 누적한다.
        outcome = self.outcome_inspector.inspect(step=step, outcome=outcome)
        await self._ensure_skill_work_link_from_outcome(task=task, outcome=outcome)
        task_status = outcome["task_status"]
        step_status = outcome["step_status"]
        was_step_completed = step.status == StepStatus.COMPLETED
        ensure_task_transition(task.status, task_status)
        step_already_terminal = step_is_terminal(step.status)
        preserve_terminal_step = (
            task_status == TaskStatus.COMPLETED
            and step_status == StepStatus.COMPLETED
            and step_already_terminal
            and step.status != step_status
        )
        if not preserve_terminal_step:
            ensure_step_transition(step.status, step_status)

        # 완료 응답 직전에 중복 semantic step 중 하나가 이미 CANCELED 된 경우가 있다.
        # TaskRun 성공은 유지하되 terminal StepRun 을 다시 열어 상태 전이 예외를 만들지 않는다.
        if not preserve_terminal_step:
            step.status = step_status
        task.current_step_run_id = step.step_run_id
        task.result_payload = outcome.get("result_payload", task.result_payload)
        task.todo_state = dict(outcome.get("todo_state") or task.todo_state)
        task.wait_payload = outcome.get("wait_payload", {})
        task.error_message = outcome.get("error_message")
        task.progress_summary = outcome.get("summary_message")
        task.revision += 1
        step.output_payload = outcome.get("output_payload", step.output_payload)
        step.wait_payload = outcome.get("wait_payload", {})
        step.error_message = outcome.get("error_message")
        step.detail_json = merge_step_detail(step.detail_json, outcome.get("detail_json"))
        semantic_lifecycle = semantic_lifecycle_for_status(task_status)
        step.detail_json = merge_step_detail(
            step.detail_json,
            build_semantic_step_detail(
                step_run_id=step.step_run_id,
                semantic_key=semantic_key_of(step.detail_json) or step.step_type,
                semantic_step=(step.detail_json.get("semanticDetail") or {}).get("semanticStep")
                or step.title
                or step.step_type,
                semantic_goal=(step.detail_json.get("semanticDetail") or {}).get("goal")
                or step.title
                or step.step_type,
                lifecycle=semantic_lifecycle,
                status=infer_semantic_status(lifecycle=semantic_lifecycle, operation_detail=step.detail_json.get("operationDetail")),
            ),
        )
        step.summary_message = outcome.get("summary_message")
        task.status = task_status
        if task_is_terminal(task_status) and not preserve_terminal_step:
            step.ended_at = utc_now()
            task.ended_at = utc_now()
        elif task_is_terminal(task_status):
            task.ended_at = utc_now()
        self.repository.update_task(task)
        self.repository.update_step(step)
        await self._sync_todo_steps(task=task, handler=handler)

        if task_status == TaskStatus.COMPLETED and not was_step_completed and not preserve_terminal_step:
            # 다음 plan step으로 넘어가더라도 현재 StepRun은 먼저 닫아야
            # realtime UI가 이전 단계를 계속 "진행 중"으로 보지 않는다.
            await self._emit("step.completed", task, step)

        if task_is_terminal(task_status):
            # todo_state(agent 내부 계획 상태)는 StepRun 경계가 아니므로 종료 시 남은 항목만 닫는다.
            task.todo_state = build_task_todo_payload(cancel_incomplete_task_todo_items(task.todo_state))
            self.repository.update_task(task)
            await self._sync_todo_steps(task=task, handler=handler)
            await self._cancel_incomplete_noncurrent_steps(task=task, current_step=step)

        if task_status == TaskStatus.WAITING:
            approval = self.approval_service.request(
                task_run_id=task.task_run_id,
                step_run_id=step.step_run_id,
                payload=outcome.get("approval_payload", {}),
            )
            self.approval_runtime.attach_waiting_approval(task=task, step=step, approval=approval)
            self.repository.update_task(task)
            self.repository.update_step(step)
            await self._emit("approval.requested", task, step, payload=approval)
            await self._emit("task.waiting", task, step)
            await self._emit("step.waiting", task, step)
            return task

        if task_status == TaskStatus.COMPLETED:
            await self._emit("task.completed", task, step, payload=task.result_payload)
            # FCM 푸시: 웹/다른 기기에서 보낸 메시지도 모바일에 동기화
            try:
                if task.session_key:
                    for fcm_token in get_fcm_tokens(str(task.owner_key)):
                        send_chat_notification(fcm_token, session_id=task.session_key, content="")
            except Exception:
                pass
            return task

        if task_status == TaskStatus.FAILED:
            await self._emit("step.failed", task, step, payload={"error_message": step.error_message})
            await self._emit("task.failed", task, step, payload={"error_message": task.error_message})
            return task

        if task_status == TaskStatus.CANCELED:
            await self._emit("step.canceled", task, step)
            await self._emit("task.canceled", task, step)
            return task

        await self._emit("task.updated", task, step)
        return task

    async def _cancel_incomplete_noncurrent_steps(self, *, task: TaskRun, current_step: StepRun) -> None:
        now = utc_now()
        for candidate in self.repository.list_steps(task.task_run_id):
            if candidate.step_run_id == current_step.step_run_id or step_is_terminal(candidate.status):
                continue
            ensure_step_transition(candidate.status, StepStatus.CANCELED)
            candidate.status = StepStatus.CANCELED
            candidate.ended_at = candidate.ended_at or now
            candidate.summary_message = candidate.summary_message or "작업 종료로 실행되지 않음"
            candidate.detail_json = merge_step_detail(
                candidate.detail_json,
                build_semantic_step_detail(
                    step_run_id=candidate.step_run_id,
                    semantic_key=semantic_key_of(candidate.detail_json) or candidate.step_type,
                    semantic_step=(candidate.detail_json.get("semanticDetail") or {}).get("semanticStep")
                    or candidate.title
                    or candidate.step_type,
                    semantic_goal=(candidate.detail_json.get("semanticDetail") or {}).get("goal")
                    or candidate.title
                    or candidate.step_type,
                    lifecycle="canceled",
                    status=infer_semantic_status(lifecycle="canceled", operation_detail=candidate.detail_json.get("operationDetail")),
                ),
            )
            self.repository.update_step(candidate)
            await self._emit("step.canceled", task, candidate)

    def _build_progress_sink(self, *, task: TaskRun, step: StepRun | None):
        current_step = step
        handler = self.tool_registry.resolve()

        async def sink(*, event_type: str, summary_message: str | None = None, payload: dict | None = None) -> None:
            nonlocal current_step
            payload = payload or {}
            if event_type == "model.progress.updated":
                updated_step = self._apply_model_progress_update(
                    task=task,
                    step=current_step,
                    payload=payload,
                    summary_message=summary_message,
                )
                if updated_step is not None:
                    current_step = updated_step
                    sink.current_step = current_step
                    self._touch_linked_work_run(task)
                    await self._emit(
                        "step.updated",
                        task,
                        current_step,
                        payload={"reason": "model.progress", **payload},
                        summary_message=current_step.summary_message,
                    )
                return
            observed_step = await self._materialize_progress_step(
                task=task,
                handler=handler,
                event_type=event_type,
                payload=payload,
            )
            if observed_step is not None:
                current_step = observed_step
                sink.current_step = current_step
            linked_work_payload = await self._ensure_skill_work_link(task=task, event_type=event_type, payload=payload)
            if linked_work_payload is not None:
                await self._emit("work.linked", task, current_step, payload=linked_work_payload)
            self._touch_linked_work_run(task)
            await self._emit(event_type, task, current_step, payload=payload, summary_message=summary_message)

        sink.current_step = current_step
        return sink

    def _apply_model_progress_update(
        self,
        *,
        task: TaskRun,
        step: StepRun | None,
        payload: dict,
        summary_message: str | None,
    ) -> StepRun | None:
        """LLM 응답 envelope의 진행 상태를 현재 StepRun에 반영한다.

        StepRun 생성과 상태 전이는 서버가 소유하고, 모델은 사용자에게 보여 줄 제목/요약 같은
        진행 설명만 제안한다. 따라서 여기서는 새 StepRun을 만들지 않고 현재 실행 anchor의
        표시 정보만 갱신한다.
        """

        if step is None and task.current_step_run_id:
            step = self.repository.get_step(task.current_step_run_id)
        if step is None:
            return None
        update = payload.get("progressUpdate") if isinstance(payload.get("progressUpdate"), dict) else payload
        if not isinstance(update, dict):
            return None
        title = self._compact_progress_text(update.get("title") or update.get("step") or update.get("label"), max_length=80)
        summary = self._compact_progress_text(
            summary_message or update.get("summary") or update.get("message") or update.get("statusMessage"),
            max_length=160,
        )
        if title:
            step.title = title
        if summary:
            step.summary_message = summary
        detail_patch = {
            "progressUpdate": {
                **dict(update),
                "turn": payload.get("turn"),
                "source": "assistant_response",
            }
        }
        step.detail_json = merge_step_detail(step.detail_json, detail_patch)
        self.repository.update_step(step)
        return step

    @staticmethod
    def _compact_progress_text(value, *, max_length: int) -> str | None:
        if not isinstance(value, str):
            return None
        text = " ".join(value.split())
        if not text:
            return None
        return text[:max_length].rstrip()

    def _touch_linked_work_run(self, task: TaskRun) -> None:
        if self.work_repository is None:
            return
        work_id = self._work_id_from_input(dict(task.input_payload or {}))
        if not work_id:
            return
        touch_run = getattr(self.work_repository, "touch_run", None)
        if callable(touch_run):
            touch_run(work_id, task.task_run_id)

    async def _ensure_skill_work_link(self, *, task: TaskRun, event_type: str, payload: dict) -> dict | None:
        if event_type != "tool.completed":
            return None
        if self.work_repository is None:
            return None
        task_input = dict(task.input_payload or {})
        if self._work_id_from_input(task_input):
            return None
        tool_name = str(payload.get("tool_name") or payload.get("toolName") or "").strip()
        if tool_name not in TRACKED_SKILL_TOOL_NAMES:
            return None
        result = payload.get("result")
        if isinstance(result, dict) and result.get("ok") is False:
            return None
        session_id = str(task.session_key or "").strip()
        if not session_id:
            return None

        skill_name = self._skill_name_from_tool_payload(payload)
        prompt = str(task_input.get("prompt") or "").strip()
        title = self._skill_work_title(skill_name=skill_name, prompt=prompt)
        service = WorkService(self.work_repository)
        work = service.create_from_payload(
            session_id=session_id,
            owner_key=str(task.owner_key),
            owner_user_id=self._int_or_none(task.owner_key),
            client_request_id=f"skill-work:{task.task_run_id}",
            payload={
                "source": "skill_use",
                "title": title,
                "description": prompt or title,
                "rawUserInput": prompt or title,
                "executionInstruction": prompt or title,
                "expectedDeliverable": "스킬 실행 결과를 반영한 답변",
                "acceptanceCriteria": ["스킬 실행 결과가 최종 답변에 반영됨"],
                "constraints": [],
                "labelNames": ["execution"],
                "metadata": {
                    "createdFrom": "skill_use",
                    "triggerTool": tool_name,
                    "skillName": skill_name,
                    "taskRunId": task.task_run_id,
                },
            },
        )
        service.mark_run_started(work_id=work.work_id, task_run_id=task.task_run_id)
        next_input = {
            **task_input,
            "workId": work.work_id,
            "workIdentifier": work.identifier,
            "workTitle": work.title,
            "workAssigneeAgentId": work.assignee_agent_id or "CEO",
            "workContext": self.work_repository.context_preview(work.work_id),
            "workLinkReason": "skill_use",
        }
        task.input_payload = next_input
        self.repository.update_task(task)
        return {
            "reason": "skill_use",
            "workId": work.work_id,
            "workIdentifier": work.identifier,
            "workTitle": work.title,
            "workStatus": work.status,
            "workAssigneeAgentId": work.assignee_agent_id,
            "taskRunId": task.task_run_id,
            "triggerTool": tool_name,
            "skillName": skill_name,
            "linkedWork": {
                "workId": work.work_id,
                "identifier": work.identifier,
                "title": work.title,
                "status": work.status,
                "assigneeAgentId": work.assignee_agent_id,
                "latestRunId": task.task_run_id,
            },
        }

    async def _ensure_skill_work_link_from_outcome(self, *, task: TaskRun, outcome: dict) -> dict | None:
        if self._work_id_from_input(dict(task.input_payload or {})):
            return None
        for tool_result in self._tool_results_from_outcome(outcome):
            tool_name = str(tool_result.get("name") or "").strip()
            if tool_name not in TRACKED_SKILL_TOOL_NAMES:
                continue
            result = tool_result.get("result")
            if isinstance(result, dict) and result.get("ok") is False:
                continue
            payload = {
                "tool_name": tool_name,
                "input": dict(tool_result.get("args") or {}),
                "result": result if isinstance(result, dict) else {},
            }
            return await self._ensure_skill_work_link(task=task, event_type="tool.completed", payload=payload)
        return None

    @staticmethod
    def _tool_results_from_outcome(outcome: dict) -> list[dict]:
        results: list[dict] = []
        for container_key in ("result_payload", "output_payload"):
            container = outcome.get(container_key)
            if not isinstance(container, dict):
                continue
            for item in container.get("tool_results") or []:
                if isinstance(item, dict):
                    results.append(item)
        deduped: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for item in results:
            key = (str(item.get("tool_call_id") or ""), str(item.get("name") or ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(item)
        return deduped

    @staticmethod
    def _work_id_from_input(task_input: dict) -> str | None:
        candidate = task_input.get("workId") or task_input.get("work_id")
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
        return None

    @staticmethod
    def _skill_name_from_tool_payload(payload: dict) -> str | None:
        for container in (payload.get("input"), payload.get("result")):
            if not isinstance(container, dict):
                continue
            value = container.get("skill_name") or container.get("skillName") or container.get("name")
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _skill_work_title(*, skill_name: str | None, prompt: str) -> str:
        if skill_name:
            return f"{skill_name} 스킬 실행"
        first_line = " ".join((prompt.splitlines()[0] if prompt.splitlines() else prompt).split())
        return (first_line[:40].rstrip() + " 스킬 실행") if first_line else "스킬 실행"

    @staticmethod
    def _int_or_none(value) -> int | None:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    def _build_delegate_executor(self, *, task: TaskRun, handler, progress_sink):
        async def execute_delegate(*, child_session: dict, tool_call_id: str, args: dict, accepted_result: dict) -> dict:
            step = getattr(progress_sink, "current_step", None)
            if step is None and task.current_step_run_id:
                step = self.repository.get_step(task.current_step_run_id)
            if step is None:
                return {
                    "ok": False,
                    "content": "delegate_task 실행에 필요한 현재 StepRun 실행 anchor가 없습니다.",
                    "error": {
                        "code": "runtime_step_required_before_delegate",
                        "message": "delegate_task requires an active runtime-owned StepRun.",
                    },
                    "child_session": child_session,
                }
            elif step.status == StepStatus.PENDING:
                step.status = StepStatus.RUNNING
                step.started_at = step.started_at or task.started_at or utc_now()
                task.current_step_run_id = step.step_run_id
                self.repository.update_task(task)
                self.repository.update_step(step)
                progress_sink.current_step = step
                await self._emit("step.started", task, step)

            async def emit_step_update(*, step, event_type: str, payload: dict, summary_message: str | None = None) -> None:
                progress_sink.current_step = step
                await self._emit(event_type, task, step, payload=payload, summary_message=summary_message)

            return await self.delegate_runtime.run_child_as_tool(
                task=task,
                step=step,
                child_session=child_session,
                repository=self.repository,
                on_step_updated=emit_step_update,
            )

        return execute_delegate

    def _build_session_agent_work_executor(self, *, task: TaskRun, handler, progress_sink):
        async def execute_session_agent_work(*, child_work: dict, tool_call_id: str, args: dict, accepted_result: dict) -> dict:
            if self.work_repository is None or self.agent_repository is None:
                return {
                    **accepted_result,
                    "ok": False,
                    "error": {"code": "work_runtime_unavailable", "message": "work runtime is not configured"},
                }

            step = getattr(progress_sink, "current_step", None)
            if step is None and task.current_step_run_id:
                step = self.repository.get_step(task.current_step_run_id)
            if step is None:
                return {
                    **accepted_result,
                    "ok": False,
                    "content": "session_agent_task 실행에 필요한 현재 StepRun 실행 anchor가 없습니다.",
                    "error": {
                        "code": "runtime_step_required_before_session_agent_task",
                        "message": "session_agent_task requires an active runtime-owned StepRun.",
                    },
                }
            if step.status == StepStatus.PENDING:
                step.status = StepStatus.RUNNING
                step.started_at = step.started_at or task.started_at or utc_now()
                task.current_step_run_id = step.step_run_id
                self.repository.update_task(task)
                self.repository.update_step(step)
                progress_sink.current_step = step
                await self._emit("step.started", task, step)

            work_id = str(child_work.get("workId") or child_work.get("work_id") or "").strip()
            work = self.work_repository.get_work(work_id) if work_id else None
            if work is None:
                return {
                    **accepted_result,
                    "ok": False,
                    "error": {"code": "child_work_not_found", "message": "child work was not found"},
                }
            parent_input = dict(task.input_payload or {})
            workflow_execution = parent_input.get("workflowExecution") or parent_input.get("workflow_execution")
            workflow_event_payload = {}
            if isinstance(workflow_execution, dict):
                workflow_event_payload = {
                    "workflowExecutionMode": workflow_execution.get("mode"),
                    "workflowRole": "child",
                    "rootWorkId": workflow_execution.get("rootWorkId") or workflow_execution.get("root_work_id") or work.parent_id,
                    "parentWorkId": work.parent_id,
                }

            task_run_id = new_id("task")
            service = WorkService(self.work_repository)
            try:
                child_input = self._build_session_agent_work_input(parent_task=task, work=work)
                child_task = self.planner.materialize_task(
                    owner_key=work.owner_key,
                    session_key=work.session_id,
                    input_payload=child_input,
                    handler=handler,
                    task_run_id=task_run_id,
                )
                self.repository.create_direct_task(child_task)
                await self._emit("task.created", child_task)
                service.mark_run_started(work_id=work.work_id, task_run_id=task_run_id)
                await self._notify_step_updated(
                    self._step_update_notifier(progress_sink=progress_sink, task=task),
                    step=step,
                    event_type="step.updated",
                    payload={
                        "reason": "session_agent_work.started",
                        "workId": work.work_id,
                        "childWorkId": work.work_id,
                        "identifier": work.identifier,
                        "assigneeAgentId": work.assignee_agent_id,
                        "profileId": work.assignee_agent_id,
                        "taskRunId": task_run_id,
                        "childTaskRunId": task_run_id,
                        "taskRunStatus": child_task.status,
                        "workStatus": "in_progress",
                        "status": child_task.status,
                        **workflow_event_payload,
                    },
                    summary_message=f"{work.identifier} 세션 에이전트 실행 중",
                )
                child_task = await self._execute_initial(task=child_task, handler=handler, resume_payload=None)
                updated_work = service.apply_task_result(work_id=work.work_id, task=child_task)
                if updated_work is not None:
                    self._record_session_agent_parent_result_comment(work=updated_work, task=child_task)
            except Exception as error:
                self.work_repository.update_run_status(work.work_id, task_run_id, "FAILED")
                failed_work = service.mark_run_start_failed(work_id=work.work_id, reason=str(error))
                await self._notify_step_updated(
                    self._step_update_notifier(progress_sink=progress_sink, task=task),
                    step=step,
                    event_type="step.updated",
                    payload={
                        "reason": "session_agent_work.failed",
                        "workId": failed_work.work_id,
                        "childWorkId": failed_work.work_id,
                        "identifier": failed_work.identifier,
                        "assigneeAgentId": failed_work.assignee_agent_id,
                        "profileId": failed_work.assignee_agent_id,
                        "taskRunId": task_run_id,
                        "childTaskRunId": task_run_id,
                        "taskRunStatus": "FAILED",
                        "workStatus": failed_work.status,
                        "status": "FAILED",
                        **workflow_event_payload,
                    },
                    summary_message=f"{work.identifier} 세션 에이전트 실행 실패",
                )
                return {
                    **accepted_result,
                    "ok": False,
                    "content": f"{work.identifier} 세션 에이전트 실행 실패: {error}",
                    "taskRunId": task_run_id,
                    "childTaskRunId": task_run_id,
                    "childStatus": "FAILED",
                    "error": {"message": str(error)},
                }

            child_status = self._task_status_value(child_task.status)
            ok = child_status == TaskStatus.COMPLETED.value
            final_work = updated_work or self.work_repository.get_work(work.work_id) or work
            parent_disposition = self._parent_disposition_from_session_agent_work(work=final_work, task=child_task)
            await self._notify_step_updated(
                self._step_update_notifier(progress_sink=progress_sink, task=task),
                step=step,
                event_type="step.updated",
                payload={
                    "reason": "session_agent_work.completed",
                    "workId": work.work_id,
                    "childWorkId": work.work_id,
                    "identifier": work.identifier,
                    "assigneeAgentId": work.assignee_agent_id,
                    "profileId": work.assignee_agent_id,
                    "taskRunId": child_task.task_run_id,
                    "childTaskRunId": child_task.task_run_id,
                    "taskRunStatus": child_status,
                    "workStatus": final_work.status,
                    "status": child_status,
                    **workflow_event_payload,
                },
                summary_message=f"{work.identifier} 세션 에이전트 실행 완료",
            )
            return {
                **accepted_result,
                "ok": ok,
                "content": self._session_agent_work_tool_content(work=final_work, task=child_task),
                "taskRunId": child_task.task_run_id,
                "childTaskRunId": child_task.task_run_id,
                "childStatus": child_status,
                "childWorkStatus": final_work.status,
                "parentWorkDisposition": parent_disposition,
            }

        return execute_session_agent_work

    def _build_session_agent_work_input(self, *, parent_task: TaskRun, work) -> dict:
        parent_input = dict(parent_task.input_payload or {})
        payload = {
            "prompt": work.execution_instruction or work.description or work.title,
            "workId": work.work_id,
            "workIdentifier": work.identifier,
            "workAssigneeAgentId": work.assignee_agent_id,
            "workContext": self.work_repository.context_preview(work.work_id) if self.work_repository is not None else {},
            "conversation_history": [],
            "system_prompt_snapshot": parent_input.get("system_prompt_snapshot") or "",
            "model": parent_input.get("model"),
            "sessionId": parent_input.get("sessionId") or parent_task.session_key or work.session_id,
            "promptMessageId": parent_input.get("promptMessageId") or parent_input.get("prompt_message_id"),
            "enabled_toolsets": ["skills", "session", "planning", "terminal", "file", "web", "work"],
            "toolsets": ["skills", "session", "planning", "terminal", "file", "web", "work"],
            "max_iterations": self._work_execution_max_iterations(),
            "parentWorkId": work.parent_id,
        }
        workflow_execution = parent_input.get("workflowExecution") or parent_input.get("workflow_execution")
        if isinstance(workflow_execution, dict):
            payload["workflowExecution"] = {
                **workflow_execution,
                "role": "child",
                "childWorkId": work.work_id,
                "parentWorkId": work.parent_id,
                "rootWorkId": workflow_execution.get("rootWorkId") or workflow_execution.get("root_work_id") or work.parent_id,
            }
            payload["workflowRole"] = "child"
            payload["rootWorkId"] = payload["workflowExecution"]["rootWorkId"]
            predecessor_results = self._workflow_predecessor_results(work)
            if predecessor_results:
                payload["workflowPredecessorResults"] = predecessor_results
                payload["prompt"] = self._append_workflow_predecessor_results(
                    prompt=str(payload.get("prompt") or ""),
                    predecessor_results=predecessor_results,
                )
        self._attach_session_agent_profile(payload, work=work)
        transcript_session_id = self._create_work_transcript_session(parent_task=parent_task, work=work, model=payload.get("model"))
        if transcript_session_id:
            payload["transcript_session_id"] = transcript_session_id
        return payload

    def _workflow_predecessor_results(self, work) -> list[dict]:
        if self.work_repository is None:
            return []
        list_relations = getattr(self.work_repository, "list_relations", None)
        if not callable(list_relations):
            return []
        results: list[dict] = []
        seen_work_ids: set[str] = set()
        for relation in list_relations(work.work_id):
            if relation.relation_type != "blocks" or relation.target_work_id != work.work_id:
                continue
            predecessor_work_id = str(relation.source_work_id or "").strip()
            if not predecessor_work_id or predecessor_work_id in seen_work_ids:
                continue
            predecessor = self.work_repository.get_work(predecessor_work_id)
            if predecessor is None:
                continue
            latest_run_id = str(getattr(predecessor, "latest_run_id", "") or "").strip()
            if not latest_run_id:
                continue
            predecessor_task = self.repository.get_task(latest_run_id)
            if predecessor_task is None:
                continue
            summary = self._session_agent_work_tool_content(work=predecessor, task=predecessor_task).strip()
            if not summary:
                continue
            seen_work_ids.add(predecessor_work_id)
            results.append(
                {
                    "workId": predecessor.work_id,
                    "identifier": predecessor.identifier,
                    "title": predecessor.title,
                    "status": predecessor.status,
                    "taskRunId": predecessor_task.task_run_id,
                    "taskStatus": self._task_status_value(predecessor_task.status),
                    "summary": summary[:6000],
                }
            )
        return results

    @staticmethod
    def _append_workflow_predecessor_results(*, prompt: str, predecessor_results: list[dict]) -> str:
        lines = [prompt.strip(), "", "## 선행 하위 작업 결과"]
        for index, result in enumerate(predecessor_results, start=1):
            title = str(result.get("title") or "").strip()
            identifier = str(result.get("identifier") or "").strip()
            summary = str(result.get("summary") or "").strip()
            heading = f"{index}. {identifier} {title}".strip()
            lines.append(heading)
            lines.append(summary)
        lines.append("")
        lines.append("위 선행 하위 작업 결과를 입력 자료로 사용해 현재 하위 작업을 완료하세요.")
        return "\n".join(line for line in lines if line is not None).strip()

    def _attach_session_agent_profile(self, payload: dict, *, work) -> None:
        if self.agent_repository is None:
            return
        profile_id = str(work.assignee_agent_id or "").strip()
        if not profile_id:
            return
        profile = self.agent_repository.get_session_agent(profile_id=profile_id, owner_key=str(work.owner_key))
        if profile is None:
            return
        profile_model = self._profile_model(profile)
        if profile_model:
            payload["model"] = profile_model
        profile_provider = self._profile_provider_name(profile)
        if profile_provider:
            payload["provider_name"] = profile_provider
        payload["targetAgentProfile"] = {
            "profileId": profile.get("profile_id"),
            "profileKey": profile.get("profile_key"),
            "profileVersion": profile.get("profile_version"),
            "agentType": profile.get("agent_type"),
            "templateKey": profile.get("template_key"),
            "configSnapshot": profile.get("config_snapshot") or {},
        }
        self._attach_session_agent_skill_names(payload, profile=profile, profile_id=profile_id, owner_key=str(work.owner_key))
        bundle = self.agent_repository.get_instruction_bundle(profile_id=profile_id, owner_key=str(work.owner_key))
        if bundle is not None:
            payload["targetAgentInstructions"] = {
                "bundleId": bundle.get("bundle_id"),
                "entryDocumentKey": bundle.get("entry_document_key") or "AGENTS.md",
                "documents": [
                    {
                        "documentKey": document.get("document_key"),
                        "displayName": document.get("display_name"),
                        "content": document.get("content") or "",
                    }
                    for document in list(bundle.get("documents") or [])
                    if isinstance(document, dict)
                ],
            }

    def _attach_session_agent_skill_names(
        self,
        payload: dict,
        *,
        profile: dict,
        profile_id: str,
        owner_key: str,
    ) -> None:
        config = profile.get("config_snapshot") if isinstance(profile.get("config_snapshot"), dict) else {}
        requested_skill_names = [str(skill) for skill in list(config.get("skills") or [])]
        if self.skill_repository is not None:
            payload["enabledSkillNames"] = self.skill_repository.effective_skill_names(
                owner_key=owner_key,
                profile_id=profile_id or None,
                requested_skill_names=requested_skill_names,
                explicit_agent_selection=config.get("skillSelectionMode") == "explicit",
            )
            return
        payload["enabledSkillNames"] = [skill.strip() for skill in requested_skill_names if skill.strip()]

    @staticmethod
    def _profile_model(profile: dict) -> str | None:
        config = profile.get("config_snapshot") if isinstance(profile.get("config_snapshot"), dict) else {}
        value = config.get("model") or profile.get("model_name")
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _profile_provider_name(profile: dict) -> str | None:
        config = profile.get("config_snapshot") if isinstance(profile.get("config_snapshot"), dict) else {}
        model = str(config.get("model") or profile.get("model_name") or "").strip()
        if model.lower().startswith("gemini-"):
            return "gemini_api_key"
        value = config.get("providerName") or config.get("provider_name") or config.get("adapterType") or profile.get("provider_name")
        text = str(value or "").strip()
        if text == "openai":
            return "openai_api_key"
        if text == "gemini":
            return "gemini_api_key"
        return text or None

    def _create_work_transcript_session(self, *, parent_task: TaskRun, work, model: str | None) -> str | None:
        if self.session_store is None:
            return None
        session_id = new_id("agent_session")
        parent_input = dict(parent_task.input_payload or {})
        parent_session_id = str(parent_input.get("transcript_session_id") or "").strip() or None
        agent_metadata = self._agent_profile_metadata_for_work(work)
        self.session_store.create_session(
            session_id=session_id,
            session_key=work.session_id,
            source="agent.loop",
            user_id=work.owner_key,
            model=model,
            parent_session_id=parent_session_id,
            title=str(work.title or work.identifier)[:120],
            metadata={
                "source": "agent.loop",
                "work_id": work.work_id,
                "work_identifier": work.identifier,
                "parent_work_id": work.parent_id,
                "assignee_agent_id": work.assignee_agent_id,
                **agent_metadata,
            },
        )
        return session_id

    def _agent_profile_metadata_for_work(self, work) -> dict[str, object]:
        if self.agent_repository is None:
            return {}
        profile_id = str(work.assignee_agent_id or "").strip()
        if not profile_id:
            return {}
        profile = self.agent_repository.get_session_agent(profile_id=profile_id, owner_key=str(work.owner_key))
        if profile is None:
            return {}
        return {
            "agent_profile_id": profile_id,
            "agent_profile_version": int(profile.get("profile_version") or 1),
            "agent_config_snapshot": dict(profile.get("config_snapshot") or {}),
        }

    def _record_session_agent_parent_result_comment(self, *, work, task: TaskRun) -> None:
        if self.work_repository is None or not work.parent_id:
            return
        disposition = task.result_payload.get("workDisposition") if isinstance(task.result_payload, dict) else None
        summary = str(disposition.get("summary") or "").strip() if isinstance(disposition, dict) else ""
        body = f"{work.identifier} 세션 에이전트 실행이 {_work_status_label(work.status)} 상태로 끝났습니다."
        if summary:
            body = f"{body}\n요약: {summary}"
        self.work_repository.add_comment(
            WorkComment(
                comment_id=new_id("comment"),
                work_id=work.parent_id,
                author_type="system",
                task_run_id=task.task_run_id,
                body=body,
                metadata={
                    "reason": "session_agent_work_result",
                    "childWorkId": work.work_id,
                    "childStatus": work.status,
                    "taskRunId": task.task_run_id,
                },
            )
        )

    def _work_execution_max_iterations(self) -> int:
        raw_value = getattr(self.settings, "work_execution_max_iterations", 24) if self.settings is not None else 24
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = 24
        return max(1, value)

    @staticmethod
    def _task_status_value(status) -> str:
        return str(getattr(status, "value", status))

    @staticmethod
    def _session_agent_work_tool_content(*, work, task: TaskRun) -> str:
        status = TaskEngine._task_status_value(task.status)
        summary = ""
        if isinstance(task.result_payload, dict):
            text = task.result_payload.get("text") or task.result_payload.get("summary")
            if isinstance(text, str):
                summary = text.strip()
        if summary:
            return f"{work.identifier} 세션 에이전트 실행 결과({status}): {summary}"
        return f"{work.identifier} 세션 에이전트 실행이 {status} 상태로 종료되었습니다."

    @staticmethod
    def _parent_disposition_from_session_agent_work(*, work, task: TaskRun) -> dict | None:
        if not work.parent_id:
            return None
        child_status = str(work.status or "").strip()
        # 한 자식이 blocked 됐다고 부모를 같이 blocked 로 잠그면, A → (B, C) 같은 DAG 에서
        # B 실패가 C 실행까지 차단해 버린다. 부모 status 는 모든 sibling 의 종합 결과로만
        # 결정되어야 하므로 child blocked 는 in_review 로 올려 다른 형제 작업이 계속 흐르게 한다.
        if child_status == "done":
            parent_status = "done"
        else:
            parent_status = "in_review"
        disposition = task.result_payload.get("workDisposition") if isinstance(task.result_payload, dict) else None
        summary = str(disposition.get("summary") or "").strip() if isinstance(disposition, dict) else ""
        next_action = str(disposition.get("nextAction") or disposition.get("next_action") or "").strip() if isinstance(disposition, dict) else ""
        return {
            "workId": work.parent_id,
            "status": parent_status,
            "summary": summary or f"{work.identifier} 세션 에이전트 실행 결과를 반영했습니다.",
            "nextAction": next_action,
        }

    @staticmethod
    def _step_update_notifier(*, progress_sink, task: TaskRun):
        async def emit_step_update(*, step, event_type: str, payload: dict, summary_message: str | None = None) -> None:
            if progress_sink is None:
                return
            progress_sink.current_step = step
            await progress_sink(event_type=event_type, summary_message=summary_message, payload=payload)

        return emit_step_update

    @staticmethod
    async def _notify_step_updated(callback, *, step, event_type: str, payload: dict, summary_message: str | None = None) -> None:
        if callback is None:
            return
        await callback(step=step, event_type=event_type, payload=payload, summary_message=summary_message)

    async def _materialize_progress_step(self, *, task: TaskRun, handler, event_type: str, payload: dict) -> StepRun | None:
        """새 실행에서는 tool event가 StepRun을 만들지 않는다.

        StepRun은 TaskRun 시작 시 서버가 선생성한 실행 anchor이고, tool event는 그 안의 operation으로만
        누적된다. 이 메서드는 과거 호출 지점을 유지하되 새 StepRun 생성 책임은 갖지 않는다.
        """

        _ = (task, handler, event_type, payload)
        return None

    async def _emit(
        self,
        event_type: str,
        task: TaskRun,
        step: StepRun | None = None,
        payload: dict | None = None,
        summary_message: str | None = None,
    ) -> None:
        event_status = self._event_status(event_type=event_type, task=task, step=step)
        event_summary = summary_message if summary_message is not None else self._event_summary(event_type=event_type, task=task, step=step)
        event_payload = self._event_payload(event_type=event_type, step=step, payload=payload)
        event_payload["displayContext"] = build_task_display_context(task, step)
        event = build_task_event(
            event_type=event_type,
            task_run_id=task.task_run_id,
            step_run_id=step.step_run_id if step else None,
            producer="task_engine",
            status=event_status,
            summary_message=event_summary,
            payload=event_payload,
        )
        saved_event = self.repository.append_event(event)
        await self.broadcaster.publish(saved_event)
        if self.iot_display_adapter is not None:
            try:
                await self.iot_display_adapter.publish(
                    event_type=event_type,
                    task=task,
                    step=step,
                    status=event_status,
                    summary_message=event_summary,
                    payload=event_payload,
                )
            except Exception:
                logger.exception("failed to publish iot display event")

    @staticmethod
    def _event_status(*, event_type: str, task: TaskRun, step: StepRun | None = None) -> str:
        if step is not None and event_type.startswith("step."):
            return step.status
        if event_type.endswith(".completed"):
            return "COMPLETED"
        if event_type.endswith(".started"):
            return "RUNNING"
        if event_type.endswith(".failed"):
            return "FAILED"
        return task.status

    @staticmethod
    def _event_summary(*, event_type: str, task: TaskRun, step: StepRun | None = None) -> str | None:
        if event_type.startswith("step.") and step is not None:
            return step.summary_message or step.title or step.step_type
        return task.progress_summary

    @staticmethod
    def _event_payload(*, event_type: str, step: StepRun | None = None, payload: dict | None = None) -> dict:
        event_payload = dict(payload or {})
        if step is not None and event_type.startswith("step."):
            event_payload.setdefault("step_run_id", step.step_run_id)
            event_payload.setdefault("stepRunId", step.step_run_id)
            event_payload.setdefault("step_title", step.title)
            event_payload.setdefault("stepTitle", step.title)
            event_payload.setdefault("step_order", step.step_order)
            event_payload.setdefault("stepOrder", step.step_order)
            semantic_detail = (step.detail_json or {}).get("semanticDetail") or {}
            semantic_step = semantic_detail.get("semanticStep")
            if isinstance(semantic_step, str) and semantic_step.strip():
                event_payload.setdefault("semantic_step", semantic_step)
                event_payload.setdefault("semanticStep", semantic_step)
        return event_payload

    async def _sync_todo_steps(self, *, task: TaskRun, handler) -> None:
        todo_state = parse_task_todo_payload(task.todo_state)
        if not todo_state.items:
            return
        if not task.current_step_run_id:
            return

        current_step = self.repository.get_step(task.current_step_run_id)
        if current_step is None:
            return

        # todo는 사용자에게 보이는 새 의미 단계가 아니라 현재 StepRun 내부 체크리스트다.
        # 따라서 task.todo_state와 현재 StepRun.detail_json.planningDetail만 같은 상태로 맞추고,
        # todo 항목마다 StepRun을 생성하거나 재사용하는 projection 경로는 열지 않는다.
        current_step.detail_json = merge_step_detail(
            current_step.detail_json,
            build_planning_detail(
                todo_items=[
                    {
                        "key": item.key,
                        "title": item.title,
                        "kind": item.kind,
                        "status": item.status,
                    }
                    for item in todo_state.items
                ],
                current_key=todo_state.current_key,
            ),
        )
        self.repository.update_step(current_step)


def _work_status_label(status: str) -> str:
    return {
        "todo": "대기",
        "in_progress": "진행 중",
        "in_review": "검토 중",
        "blocked": "차단됨",
        "done": "완료",
        "cancelled": "취소됨",
    }.get(str(status or ""), str(status or ""))
