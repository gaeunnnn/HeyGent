from __future__ import annotations

from typing import Any

from app.core.utils.ids import new_id
from app.contracts.task.task_status import TaskStatus
from app.domain.work.models import WorkComment, WorkItem
from app.domain.work.policies import (
    initial_status_for_work_mode,
    normalize_disposition_status,
    restore_status_for_resume,
    status_after_run_start_failure,
)
from app.domain.work.repository import WorkRepository
from app.domain.work.wake import WorkWakeService
from app.domain.tasks.models import TaskRun


class WorkRunClaimConflict(RuntimeError):
    def __init__(self, work_id: str) -> None:
        super().__init__(f"work already has an active run: {work_id}")
        self.work_id = work_id


class WorkService:
    def __init__(self, repository: WorkRepository) -> None:
        self.repository = repository

    def create_from_payload(
        self,
        *,
        session_id: str,
        owner_key: str,
        owner_user_id: int | None,
        payload: dict[str, Any],
        client_request_id: str | None,
    ) -> WorkItem:
        if client_request_id:
            existing = self.repository.get_work_by_client_request_id(session_id, client_request_id)
            if existing is not None:
                return existing

        raw_user_input = str(payload.get("rawUserInput") or payload.get("raw_user_input") or "").strip()
        title = _fallback_title(str(payload.get("title") or "").strip(), raw_user_input)
        description = str(payload.get("description") or raw_user_input or title).strip()
        parent_id = _empty_to_none(payload.get("parentId") or payload.get("parent_id"))
        flow_order = _flow_order_or_none(payload.get("flowOrder") or payload.get("flow_order"))
        if parent_id and flow_order is None:
            next_child_flow_order = getattr(self.repository, "next_child_flow_order", None)
            if callable(next_child_flow_order):
                flow_order = next_child_flow_order(parent_id)
        if parent_id is None and flow_order is None:
            next_root_flow_order = getattr(self.repository, "next_root_flow_order", None)
            if callable(next_root_flow_order):
                flow_order = next_root_flow_order(session_id=session_id, owner_key=owner_key)
        work = WorkItem(
            work_id=new_id("work"),
            identifier=self.repository.next_identifier(session_id),
            session_id=session_id,
            owner_key=owner_key,
            owner_user_id=owner_user_id,
            title=title,
            description=description,
            status=initial_status_for_work_mode(),
            assignee_agent_id=_empty_to_none(payload.get("assigneeAgentId") or payload.get("assignee_agent_id")) or "CEO",
            parent_id=parent_id,
            flow_order=flow_order,
            source=str(payload.get("source") or "work_mode").strip() or "work_mode",
            raw_user_input=raw_user_input,
            execution_instruction=str(payload.get("executionInstruction") or payload.get("execution_instruction") or description).strip(),
            expected_deliverable=_empty_to_none(payload.get("expectedDeliverable") or payload.get("expected_deliverable")),
            acceptance_criteria=_string_list(payload.get("acceptanceCriteria") or payload.get("acceptance_criteria")),
            constraints=_string_list(payload.get("constraints")),
            metadata=dict(payload.get("metadata") or {}),
        )
        saved = self.repository.create_work(work, client_request_id=client_request_id)
        self.repository.set_label_links_by_names(
            saved.work_id,
            session_id=session_id,
            owner_key=owner_key,
            label_names=_string_list(payload.get("labelNames") or payload.get("label_names")),
        )
        if parent_id:
            self.repository.inherit_parent_labels(saved.work_id, parent_id)
        return saved

    def mark_run_started(self, *, work_id: str, task_run_id: str) -> None:
        claim_run = getattr(self.repository, "claim_run", None)
        if callable(claim_run):
            link = claim_run(
                work_id,
                task_run_id,
                run_kind="initial",
                status="RUNNING",
            )
        else:
            link = self.repository.link_run(work_id, task_run_id, run_kind="initial", status="RUNNING")
        if link is None:
            raise WorkRunClaimConflict(work_id)

    def mark_run_start_failed(self, *, work_id: str, reason: str) -> WorkItem:
        updated = self.repository.update_status(work_id, status_after_run_start_failure())
        self.repository.add_comment(
            WorkComment(
                comment_id=new_id("comment"),
                work_id=work_id,
                author_type="system",
                body=f"실행 시작 실패: {reason}",
            )
        )
        return updated

    def apply_task_result(self, *, work_id: str, task: TaskRun) -> WorkItem | None:
        work_before_result = self.repository.get_work(work_id)
        self.repository.update_run_status(work_id, task.task_run_id, task.status)
        if (
            work_before_result is not None
            and work_before_result.active_run_id is not None
            and work_before_result.active_run_id != task.task_run_id
        ):
            return self.repository.get_work(work_id)
        disposition = _extract_work_disposition(task.result_payload)
        status = normalize_disposition_status(disposition.get("status") if disposition else None)
        if status is not None:
            updated = self.repository.update_status(work_id, status)
            self.repository.add_comment(
                WorkComment(
                    comment_id=new_id("comment"),
                    work_id=work_id,
                    author_type="system",
                    task_run_id=task.task_run_id,
                    body=_work_disposition_comment_body(status=status, disposition=disposition or {}),
                    metadata={
                        "reason": "work_disposition_metadata",
                        "status": status,
                        "summary": str((disposition or {}).get("summary") or "").strip(),
                        "nextAction": str(
                            (disposition or {}).get("nextAction")
                            or (disposition or {}).get("next_action")
                            or ""
                        ).strip(),
                    },
                )
            )
            if status in {"done", "cancelled"}:
                wake_service = WorkWakeService(self.repository)
                wake_service.enqueue_after_blocker_update(
                    blocker_work_id=work_id,
                    requested_by_task_run_id=task.task_run_id,
                )
                wake_service.enqueue_after_child_terminal_update(
                    child_work_id=work_id,
                    requested_by_task_run_id=task.task_run_id,
                )
            return updated
        task_status = getattr(task.status, "value", str(task.status))
        if task_status == TaskStatus.FAILED.value:
            return self._block_work_after_run_failure(work_id=work_id, task_run_id=task.task_run_id)
        if task_status == TaskStatus.COMPLETED.value and _has_blocking_tool_error(task.result_payload):
            return self._block_work_after_run_failure(work_id=work_id, task_run_id=task.task_run_id)
        if task_status == TaskStatus.COMPLETED.value:
            updated = self.repository.get_work(work_id)
            self.repository.add_comment(
                WorkComment(
                    comment_id=new_id("comment"),
                    work_id=work_id,
                    author_type="system",
                    task_run_id=task.task_run_id,
                    body="실행은 완료됐지만 작업 종료 상태가 명시되지 않았습니다. 결과를 확인한 뒤 상태를 정리하세요.",
                    metadata={"reason": "missing_work_disposition"},
                )
            )
            self.repository.create_interaction(
                work_id=work_id,
                kind="request_confirmation",
                title="작업 종료 상태 확인 필요",
                body=(
                    "실행은 완료됐지만 작업 종료 상태가 명시되지 않았습니다. "
                    "done, cancelled, in_review, blocked, todo 중 하나로 workDisposition을 남겨야 합니다."
                ),
                payload={
                    "reason": "missing_work_disposition",
                    "taskRunId": task.task_run_id,
                    "allowedStatuses": ["done", "cancelled", "in_review", "blocked", "todo"],
                },
                continuation_policy="wake_assignee",
            )
            return updated
        return self.repository.get_work(work_id)

    def apply_linked_task_result(self, *, task: TaskRun) -> WorkItem | None:
        work_id = _work_id_from_task(task)
        if not work_id:
            return None
        work = self.repository.get_work(work_id)
        if work is None:
            return None
        if not _has_run_link(self.repository, work_id=work_id, task_run_id=task.task_run_id):
            try:
                self.mark_run_started(work_id=work_id, task_run_id=task.task_run_id)
            except WorkRunClaimConflict:
                return self.repository.get_work(work_id)
        return self.apply_task_result(work_id=work_id, task=task)

    def _block_work_after_run_failure(self, *, work_id: str, task_run_id: str) -> WorkItem:
        updated = self.repository.update_status(work_id, "blocked")
        self.repository.add_comment(
            WorkComment(
                comment_id=new_id("comment"),
                work_id=work_id,
                author_type="system",
                task_run_id=task_run_id,
                body="실행이 완료되지 않았습니다. 진행 내용을 확인한 뒤 다시 실행하세요.",
            )
        )
        return updated

    def add_comment(
        self,
        *,
        work: WorkItem,
        body: str,
        author_type: str,
        author_id: str | None,
        task_run_id: str | None = None,
        resume_requested: bool = False,
    ) -> WorkComment:
        if resume_requested:
            self.repository.update_status(work.work_id, restore_status_for_resume(work.status))
        return self.repository.add_comment(
            WorkComment(
                comment_id=new_id("comment"),
                work_id=work.work_id,
                author_type=author_type,
                author_id=author_id,
                body=body,
                task_run_id=task_run_id,
                resume_requested=resume_requested,
            )
        )


def _extract_work_disposition(payload: dict[str, Any]) -> dict[str, Any] | None:
    candidate = payload.get("workDisposition") or payload.get("work_disposition")
    return candidate if isinstance(candidate, dict) else None


def _work_id_from_task(task: TaskRun) -> str | None:
    input_payload = task.input_payload or {}
    input_work_id = _text_value(input_payload.get("workId") or input_payload.get("work_id"))
    if input_work_id:
        return input_work_id
    disposition = _extract_work_disposition(task.result_payload or {})
    if disposition is None:
        return None
    return _text_value(disposition.get("workId") or disposition.get("work_id"))


def _text_value(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _has_run_link(repository: WorkRepository, *, work_id: str, task_run_id: str) -> bool:
    try:
        runs = repository.list_runs(work_id, limit=100, offset=0)
    except Exception:
        return False
    return any(run.task_run_id == task_run_id for run in runs)


def _work_disposition_comment_body(*, status: str, disposition: dict[str, Any]) -> str:
    summary = str(disposition.get("summary") or "").strip()
    next_action = str(disposition.get("nextAction") or disposition.get("next_action") or "").strip()
    parts = [f"작업 상태를 {_work_status_label(status)} 상태로 정리했습니다."]
    if summary:
        parts.append(f"사유: {summary}")
    if next_action:
        parts.append(f"다음 조치: {next_action}")
    return "\n".join(parts)


def _work_status_label(status: str) -> str:
    return {
        "todo": "대기",
        "in_progress": "진행 중",
        "in_review": "검토 중",
        "blocked": "차단됨",
        "done": "완료",
        "cancelled": "취소됨",
    }.get(status, status)


def _has_blocking_tool_error(payload: dict[str, Any]) -> bool:
    last_blocking_outcome: bool | None = None
    for item in _walk_values(payload):
        if not isinstance(item, dict):
            continue
        outcome = _blocking_tool_outcome(item)
        if outcome is not None:
            last_blocking_outcome = outcome
    return last_blocking_outcome is False


def _blocking_tool_outcome(item: dict[str, Any]) -> bool | None:
    result = item.get("result")
    error = item.get("error")
    error_code = str(error.get("code") or "").strip() if isinstance(error, dict) else ""
    tool_name = _tool_name_from_item(item, result=result, error=error)
    is_io_tool = "file" in tool_name or "terminal" in tool_name

    if error_code in {"bridge_not_connected", "tool_runtime_unavailable", "tool_not_found"}:
        return False
    if not is_io_tool:
        return None

    if item.get("ok") is False:
        return False
    if isinstance(result, dict):
        if result.get("ok") is False:
            return False
        result = item.get("result")
        try:
            returncode = int(result.get("returncode"))
        except (TypeError, ValueError):
            returncode = None
        if returncode is not None:
            return returncode == 0
        if result.get("ok") is True:
            return True
        if "file" in tool_name and not result.get("error"):
            return True
    if item.get("ok") is True:
        return True
    return None


def _tool_name_from_item(item: dict[str, Any], *, result: Any, error: Any) -> str:
    candidates = [item.get("name")]
    if isinstance(result, dict):
        candidates.append(result.get("tool_name"))
    if isinstance(error, dict):
        candidates.append(error.get("tool_name"))
    return str(next((value for value in candidates if value), "")).strip()


def _walk_values(value: Any):
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk_values(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_values(child)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _empty_to_none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _flow_order_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _fallback_title(title: str, raw_user_input: str) -> str:
    if title:
        return title[:80].rstrip()
    text = str(raw_user_input or "").strip().replace("\r\n", "\n")
    text = text.splitlines()[0] if text else ""
    text = text.replace("\\", " ")
    for marker in (" 조사해서", " 정리해서", " 만들어", " 작성해", " 저장"):
        if marker in text:
            text = text.split(marker, 1)[0] + marker
            break
    compact = " ".join(text.split())
    return compact[:48].rstrip() or "새 작업"
