from __future__ import annotations

import logging
from typing import Any

from app.contracts.event.task_events import TaskEventEnvelope
from app.domain.tasks.models import StepRun, TaskRun
from app.storage.redis.task_projection import RedisTaskProjectionStore


logger = logging.getLogger(__name__)


class ProjectingTaskRepository:
    """기존 durable repository 쓰기 뒤에 Redis 조회 projection을 갱신하는 decorator다."""

    def __init__(self, durable_repository: Any, projection_store: RedisTaskProjectionStore) -> None:
        self.durable_repository = durable_repository
        self.projection_store = projection_store

    def create_task(self, task: TaskRun) -> TaskRun:
        saved_task = self.durable_repository.create_task(task)
        self._save_task_snapshot(saved_task)
        return saved_task

    def create_direct_task(self, task: TaskRun) -> TaskRun:
        saved_task = self.durable_repository.create_direct_task(task)
        self._save_task_snapshot(saved_task)
        return saved_task

    def create_pending_task(self, task: TaskRun) -> TaskRun:
        saved_task = self.durable_repository.create_pending_task(task)
        self._save_task_snapshot(saved_task)
        return saved_task

    def claim_next_task(self, *, claim_owner: str, lease_seconds: int = 300) -> TaskRun | None:
        saved_task = self.durable_repository.claim_next_task(claim_owner=claim_owner, lease_seconds=lease_seconds)
        if saved_task is not None:
            self._save_task_snapshot(saved_task)
        return saved_task

    def heartbeat_task_claim(self, task_run_id: str, *, claim_owner: str, lease_seconds: int = 300) -> TaskRun | None:
        saved_task = self.durable_repository.heartbeat_task_claim(
            task_run_id,
            claim_owner=claim_owner,
            lease_seconds=lease_seconds,
        )
        if saved_task is not None:
            self._save_task_snapshot(saved_task)
        return saved_task

    def fail_task_claim(self, task_run_id: str, *, claim_owner: str, error_message: str, retry: bool = False) -> TaskRun | None:
        saved_task = self.durable_repository.fail_task_claim(
            task_run_id,
            claim_owner=claim_owner,
            error_message=error_message,
            retry=retry,
        )
        if saved_task is not None:
            self._save_task_snapshot(saved_task)
        return saved_task

    def recover_stale_task_run(self, task_run_id: str, *, reason: str) -> TaskRun | None:
        saved_task = self.durable_repository.recover_stale_task_run(task_run_id, reason=reason)
        if saved_task is not None:
            self._save_task_snapshot(saved_task)
        return saved_task

    def recover_stale_task_runs(self, *, orphan_after_seconds: int = 300, limit: int = 100) -> list[TaskRun]:
        saved_tasks = self.durable_repository.recover_stale_task_runs(
            orphan_after_seconds=orphan_after_seconds,
            limit=limit,
        )
        for task in saved_tasks:
            self._save_task_snapshot(task)
        return saved_tasks

    def update_task(self, task: TaskRun) -> TaskRun:
        saved_task = self.durable_repository.update_task(task)
        self._save_task_snapshot(saved_task)
        return saved_task

    def create_step(self, step: StepRun) -> StepRun:
        saved_step = self.durable_repository.create_step(step)
        self._save_step_snapshot(saved_step)
        return saved_step

    def update_step(self, step: StepRun) -> StepRun:
        saved_step = self.durable_repository.update_step(step)
        self._save_step_snapshot(saved_step)
        return saved_step

    def append_event(self, event: TaskEventEnvelope) -> TaskEventEnvelope:
        saved_event = self.durable_repository.append_event(event)
        try:
            projected_event = self.projection_store.append_event(saved_event)
            self.projection_store.trim_recent_events(saved_event.task_run_id)
            return saved_event.model_copy(
                update={
                    "sequence": projected_event.get("sequence"),
                    "event_id_alias": projected_event.get("eventId"),
                }
            )
        except Exception:
            # Redis projection은 조회/전파 최적화 계층이므로 durable write 성공을 되돌리지 않는다.
            logger.exception("Redis TaskRun event projection 갱신에 실패했습니다.")
        return saved_event

    def _save_task_snapshot(self, task: TaskRun) -> None:
        try:
            self.projection_store.save_task_snapshot(task)
        except Exception:
            # TaskRun 자체는 이미 durable repository에 저장됐으므로 projection 실패는 로그로만 남긴다.
            logger.exception("Redis TaskRun snapshot 갱신에 실패했습니다.")

    def _save_step_snapshot(self, step: StepRun) -> None:
        try:
            self.projection_store.save_step_snapshot(step)
        except Exception:
            # StepRun projection miss는 HTTP fallback과 다음 업데이트로 복구할 수 있다.
            logger.exception("Redis StepRun snapshot 갱신에 실패했습니다.")

    def __getattr__(self, name: str) -> Any:
        return getattr(self.durable_repository, name)
