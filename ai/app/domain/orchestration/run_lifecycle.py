from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal

from app.contracts.task.task_status import TaskStatus
from app.core.time import utc_now

RunLivenessState = Literal["missing", "terminal", "waiting", "queued", "live", "expired", "orphaned"]

_TERMINAL_STATUSES = {TaskStatus.COMPLETED.value, TaskStatus.FAILED.value, TaskStatus.CANCELED.value}
_WAITING_STATUSES = {TaskStatus.WAITING.value, TaskStatus.BLOCKED.value}
_ACTIVE_STATUSES = {TaskStatus.PENDING.value, TaskStatus.RUNNING.value, TaskStatus.WAITING.value, TaskStatus.BLOCKED.value}
_CLAIMED_QUEUE_STATUSES = {"claimed", "running"}
_TERMINAL_QUEUE_STATUSES = {"terminal", "canceled"}
_QUEUED_QUEUE_STATUSES = {"queued", "failed_retry"}


@dataclass(frozen=True, slots=True)
class RunLiveness:
    state: RunLivenessState
    blocks_session: bool
    should_recover: bool
    reason: str


def classify_task_run_liveness(
    task: Any | None,
    *,
    now: datetime | None = None,
    orphan_after_seconds: int = 300,
) -> RunLiveness:
    now_dt = now or utc_now()
    if task is None:
        return RunLiveness("missing", False, True, "task_missing")

    status = str(getattr(task, "status", "") or "")
    queue_status = str(getattr(task, "queue_status", "") or "")
    if status in _TERMINAL_STATUSES or queue_status in _TERMINAL_QUEUE_STATUSES:
        return RunLiveness("terminal", False, False, "terminal_status")
    if status in _WAITING_STATUSES:
        return RunLiveness("waiting", True, False, "waiting_for_input")
    if queue_status in _QUEUED_QUEUE_STATUSES:
        return RunLiveness("queued", True, False, "queued_for_worker")
    if status == TaskStatus.PENDING.value and queue_status not in _CLAIMED_QUEUE_STATUSES:
        return RunLiveness("queued", True, False, "queued_for_worker")
    if status not in _ACTIVE_STATUSES:
        return RunLiveness("terminal", False, False, "inactive_status")

    lease_expires_at = _as_datetime(getattr(task, "lease_expires_at", None))
    if lease_expires_at is not None:
        if lease_expires_at < now_dt:
            return RunLiveness("expired", False, True, "lease_expired")
        return RunLiveness("live", True, False, "lease_active")

    heartbeat_at = _as_datetime(getattr(task, "heartbeat_at", None))
    if heartbeat_at is not None:
        age_seconds = (now_dt - heartbeat_at).total_seconds()
        if age_seconds > max(1, int(orphan_after_seconds)):
            return RunLiveness("orphaned", False, True, "heartbeat_stale")
        return RunLiveness("live", True, False, "heartbeat_recent")

    updated_at = _as_datetime(getattr(task, "updated_at", None))
    claim_owner = str(getattr(task, "claim_owner", "") or "")
    if queue_status in _CLAIMED_QUEUE_STATUSES and not claim_owner:
        return RunLiveness("live", True, False, "direct_run_without_supervisor_claim")
    if queue_status in _CLAIMED_QUEUE_STATUSES or status == TaskStatus.RUNNING.value:
        if updated_at is None:
            return RunLiveness("orphaned", False, True, "claim_signal_missing")
        age_seconds = (now_dt - updated_at).total_seconds()
        if age_seconds > max(1, int(orphan_after_seconds)):
            return RunLiveness("orphaned", False, True, "claim_signal_stale")

    return RunLiveness("live", True, False, "recent_active_state")


def _as_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    return None

