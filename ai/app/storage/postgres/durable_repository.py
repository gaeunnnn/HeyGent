from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from app.contracts.event.task_events import TaskEventEnvelope
from app.core.time import utc_now
from app.core.utils.ids import new_id
from app.domain.orchestration.run_lifecycle import classify_task_run_liveness
from app.domain.tasks.models import StepRun, TaskRun


_ACTIVE_TASK_STATUSES = {"PENDING", "RUNNING", "WAITING", "BLOCKED"}
_TERMINAL_TASK_STATUSES = {"COMPLETED", "FAILED", "CANCELED"}
_ACTIVE_QUEUE_STATUSES = {"queued", "claimed", "running", "waiting", "failed_retry"}
_TERMINAL_QUEUE_STATUSES = {"terminal", "canceled"}


class PostgresDurableRepository:
    """Postgres durable anchor와 worker handoff를 다루는 최소 repository다."""

    storage_backend = "postgres"

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self.connection_factory = connection_factory

    def upsert_run_anchor(self, task_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _required(payload, "owner_key")
        connection = self.connection_factory()
        connection.execute(
            """
            INSERT INTO run_anchors (
                task_run_id, session_id, owner_key, owner_user_id, session_key,
                current_step_run_id, durable_status, queue_status, claim_owner,
                queued_at, claimed_at, lease_expires_at, heartbeat_at, next_attempt_at,
                attempts, last_claim_error, agent_profile_id, agent_profile_version,
                agent_config_snapshot, anchor_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            ON CONFLICT (task_run_id) DO UPDATE SET
                session_id = EXCLUDED.session_id,
                owner_key = EXCLUDED.owner_key,
                owner_user_id = EXCLUDED.owner_user_id,
                session_key = EXCLUDED.session_key,
                current_step_run_id = EXCLUDED.current_step_run_id,
                durable_status = EXCLUDED.durable_status,
                queue_status = EXCLUDED.queue_status,
                claim_owner = EXCLUDED.claim_owner,
                queued_at = COALESCE(run_anchors.queued_at, EXCLUDED.queued_at),
                claimed_at = EXCLUDED.claimed_at,
                lease_expires_at = EXCLUDED.lease_expires_at,
                heartbeat_at = EXCLUDED.heartbeat_at,
                next_attempt_at = EXCLUDED.next_attempt_at,
                attempts = EXCLUDED.attempts,
                last_claim_error = EXCLUDED.last_claim_error,
                agent_profile_id = EXCLUDED.agent_profile_id,
                agent_profile_version = EXCLUDED.agent_profile_version,
                agent_config_snapshot = EXCLUDED.agent_config_snapshot,
                anchor_payload = EXCLUDED.anchor_payload,
                revision = run_anchors.revision + 1,
                updated_at = now()
            """,
            (
                task_run_id,
                payload.get("session_id"),
                owner_key,
                payload.get("owner_user_id") or _owner_user_id(owner_key),
                payload.get("session_key"),
                payload.get("current_step_run_id"),
                payload.get("durable_status", "OPEN"),
                payload.get("queue_status", "queued"),
                payload.get("claim_owner"),
                payload.get("queued_at") or utc_now(),
                payload.get("claimed_at"),
                payload.get("lease_expires_at"),
                payload.get("heartbeat_at"),
                payload.get("next_attempt_at"),
                int(payload.get("attempts") or 0),
                payload.get("last_claim_error"),
                payload.get("agent_profile_id"),
                payload.get("agent_profile_version"),
                _json(payload.get("agent_config_snapshot", {})),
                _json(payload.get("anchor_payload", {})),
            ),
        )
        connection.commit()
        return self.get_run_anchor(task_run_id) or {}

    def get_run_anchor(self, task_run_id: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute("SELECT * FROM run_anchors WHERE task_run_id = %s", (task_run_id,)).fetchone()
        return _normalize_row(row)

    def upsert_step_anchor(self, step_run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        task_run_id = _required(payload, "task_run_id")
        connection = self.connection_factory()
        connection.execute(
            """
            INSERT INTO step_anchors (
                step_run_id, task_run_id, parent_step_run_id, worker_session_id,
                step_order, step_type, durable_status, anchor_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (step_run_id) DO UPDATE SET
                task_run_id = EXCLUDED.task_run_id,
                parent_step_run_id = EXCLUDED.parent_step_run_id,
                worker_session_id = EXCLUDED.worker_session_id,
                step_order = EXCLUDED.step_order,
                step_type = EXCLUDED.step_type,
                durable_status = EXCLUDED.durable_status,
                anchor_payload = EXCLUDED.anchor_payload,
                revision = step_anchors.revision + 1,
                updated_at = now()
            """,
            (
                step_run_id,
                task_run_id,
                payload.get("parent_step_run_id"),
                payload.get("worker_session_id"),
                payload.get("step_order", 0),
                payload.get("step_type", "agent.loop.execute"),
                payload.get("durable_status", "OPEN"),
                _json(payload.get("anchor_payload", {})),
            ),
        )
        connection.commit()
        return self.get_step_anchor(step_run_id) or {}

    def get_step_anchor(self, step_run_id: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute("SELECT * FROM step_anchors WHERE step_run_id = %s", (step_run_id,)).fetchone()
        return _normalize_row(row)

    def create_worker_handoff(self, payload: dict[str, Any]) -> dict[str, Any]:
        handoff_id = _required(payload, "handoff_id")
        connection = self.connection_factory()
        connection.execute(
            """
            INSERT INTO worker_handoffs (
                handoff_id, task_run_id, parent_step_run_id, parent_session_id,
                worker_session_id, worker_profile_id, worker_profile_version,
                status, input_payload, result_summary
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)
            """,
            (
                handoff_id,
                _required(payload, "task_run_id"),
                _required(payload, "parent_step_run_id"),
                payload.get("parent_session_id"),
                payload.get("worker_session_id"),
                payload.get("worker_profile_id"),
                payload.get("worker_profile_version"),
                payload.get("status", "PENDING"),
                _json(payload.get("input_payload", {})),
                _json(payload.get("result_summary", {})),
            ),
        )
        connection.commit()
        return self._get_worker_handoff(handoff_id) or {}

    def complete_worker_handoff(self, handoff_id: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        connection = self.connection_factory()
        connection.execute(
            """
            UPDATE worker_handoffs
            SET status = %s, result_summary = %s::jsonb, completed_at = now()
            WHERE handoff_id = %s
            """,
            (
                payload.get("status", "COMPLETED"),
                _json(payload.get("result_summary", {})),
                handoff_id,
            ),
        )
        connection.commit()
        return self._get_worker_handoff(handoff_id)

    def _get_worker_handoff(self, handoff_id: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute("SELECT * FROM worker_handoffs WHERE handoff_id = %s", (handoff_id,)).fetchone()
        return _normalize_row(row)


class PostgresTaskRepository(PostgresDurableRepository):
    """Postgres durable anchor를 기존 TaskRepository 호출부에 연결하는 adapter다.

    TaskRun/StepRun의 빠른 화면 조회는 Redis projection이 맡고, 이 adapter는 재시작/복구에 필요한
    최소 스냅샷을 run_anchors/step_anchors에 JSON anchor로 저장한다.
    """

    def create_task(self, task: TaskRun) -> TaskRun:
        now_dt = utc_now()
        task.created_at = task.created_at or now_dt
        task.updated_at = now_dt
        self._save_task_anchor(task)
        return task

    def create_direct_task(self, task: TaskRun) -> TaskRun:
        now_dt = utc_now()
        # direct 실행은 현재 coroutine이 실행권을 가진다.
        # DB supervisor가 집어갈 queue 항목이 아니므로 저장 순간부터 claim 대상에서 제외한다.
        task.queue_status = "running"
        task.claim_owner = None
        task.claimed_at = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        task.next_attempt_at = None
        task.queued_at = task.queued_at or now_dt
        task.attempts = int(task.attempts or 0)
        return self.create_task(task)

    def create_pending_task(self, task: TaskRun) -> TaskRun:
        now_dt = utc_now()
        task.status = "PENDING"
        task.queue_status = "queued"
        task.queued_at = task.queued_at or now_dt
        task.claim_owner = None
        task.claimed_at = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        task.next_attempt_at = task.next_attempt_at or now_dt
        task.attempts = int(task.attempts or 0)
        return self.create_task(task)

    def claim_next_task(self, *, claim_owner: str, lease_seconds: int = 300) -> TaskRun | None:
        now_dt = utc_now()
        lease_expires_at = now_dt + timedelta(seconds=max(1, int(lease_seconds)))
        connection = self.connection_factory()
        row = connection.execute(
            """
            WITH claimable AS (
                SELECT task_run_id
                FROM run_anchors
                WHERE queue_status IN ('queued', 'failed_retry')
                  AND (next_attempt_at IS NULL OR next_attempt_at <= now())
                ORDER BY queued_at ASC, created_at ASC
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            UPDATE run_anchors AS ra
            SET queue_status = 'claimed',
                claim_owner = %s,
                claimed_at = %s,
                heartbeat_at = %s,
                lease_expires_at = %s,
                attempts = ra.attempts + 1,
                last_claim_error = NULL,
                updated_at = now()
            FROM claimable
            WHERE ra.task_run_id = claimable.task_run_id
            RETURNING ra.*
            """,
            (claim_owner, now_dt, now_dt, lease_expires_at),
        ).fetchone()
        connection.commit()
        anchor = _normalize_row(row)
        if anchor is None:
            return None
        task = _task_from_payload((anchor.get("anchor_payload") or {}).get("task"))
        if task is None:
            return None
        task.status = "RUNNING"
        task.queue_status = "claimed"
        task.claim_owner = claim_owner
        task.claimed_at = now_dt
        task.heartbeat_at = now_dt
        task.lease_expires_at = lease_expires_at
        task.attempts = int(anchor.get("attempts") or task.attempts or 0)
        self.update_task(task)
        return task

    def heartbeat_task_claim(self, task_run_id: str, *, claim_owner: str, lease_seconds: int = 300) -> TaskRun | None:
        now_dt = utc_now()
        lease_expires_at = now_dt + timedelta(seconds=max(1, int(lease_seconds)))
        task = self.get_task(task_run_id)
        if task is None or task.claim_owner != claim_owner:
            return None
        task.queue_status = "running"
        task.heartbeat_at = now_dt
        task.lease_expires_at = lease_expires_at
        return self.update_task(task)

    def fail_task_claim(self, task_run_id: str, *, claim_owner: str, error_message: str, retry: bool = False) -> TaskRun | None:
        task = self.get_task(task_run_id)
        if task is None or task.claim_owner != claim_owner:
            return None
        task.status = "PENDING" if retry else "FAILED"
        task.queue_status = "failed_retry" if retry else "terminal"
        task.error_message = error_message
        task.last_claim_error = error_message
        task.next_attempt_at = utc_now() + timedelta(seconds=10) if retry else None
        task.claim_owner = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        if not retry:
            task.ended_at = task.ended_at or utc_now()
        return self.update_task(task)

    def recover_stale_task_run(self, task_run_id: str, *, reason: str) -> TaskRun | None:
        task = self.get_task(task_run_id)
        if task is None or task.status not in {"PENDING", "RUNNING"}:
            return None
        liveness = classify_task_run_liveness(task)
        if not liveness.should_recover:
            return None
        now_dt = utc_now()
        task.status = "FAILED"
        task.queue_status = "terminal"
        task.error_message = "실행 상태가 만료되어 자동 복구되었습니다."
        task.last_claim_error = reason or liveness.reason
        task.claim_owner = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        task.next_attempt_at = None
        task.ended_at = task.ended_at or now_dt
        return self.update_task(task)

    def recover_stale_task_runs(self, *, orphan_after_seconds: int = 300, limit: int = 100) -> list[TaskRun]:
        recovered: list[TaskRun] = []
        candidates = self._load_stale_recovery_candidates(orphan_after_seconds=orphan_after_seconds, limit=limit)
        for task in candidates:
            liveness = classify_task_run_liveness(task, orphan_after_seconds=orphan_after_seconds)
            if not liveness.should_recover:
                continue
            saved = self.recover_stale_task_run(task.task_run_id, reason=liveness.reason)
            if saved is not None:
                recovered.append(saved)
        return recovered

    def _load_stale_recovery_candidates(self, *, orphan_after_seconds: int, limit: int) -> list[TaskRun]:
        connection = self.connection_factory()
        rows = connection.execute(
            """
            SELECT *
            FROM run_anchors
            WHERE queue_status IN ('claimed', 'running')
              AND claim_owner IS NOT NULL
              AND (
                lease_expires_at < now()
                OR heartbeat_at < now() - (%s * interval '1 second')
                OR (
                  lease_expires_at IS NULL
                  AND heartbeat_at IS NULL
                  AND updated_at < now() - (%s * interval '1 second')
                )
              )
            ORDER BY updated_at ASC, created_at ASC
            LIMIT %s
            """,
            (max(1, int(orphan_after_seconds)), max(1, int(orphan_after_seconds)), max(1, int(limit))),
        ).fetchall()
        tasks: list[TaskRun] = []
        for row in rows:
            normalized = _normalize_row(row) or {}
            task = _task_from_payload((normalized.get("anchor_payload") or {}).get("task"))
            if task is None:
                continue
            _apply_anchor_queue_fields(task, normalized)
            tasks.append(task)
        return tasks

    def update_task(self, task: TaskRun) -> TaskRun:
        task.updated_at = utc_now()
        self._save_task_anchor(task)
        return task

    def get_task(self, task_run_id: str) -> TaskRun | None:
        anchor = self.get_run_anchor(task_run_id)
        if not anchor:
            return None
        task = _task_from_payload((anchor.get("anchor_payload") or {}).get("task"))
        if task is not None:
            _apply_anchor_queue_fields(task, anchor)
        return task

    def list_tasks(self, *, status: str | None = None, session_key: str | None = None, limit: int = 20, offset: int = 0) -> list[TaskRun]:
        tasks = self._load_all_tasks()
        if status is not None:
            tasks = [task for task in tasks if task.status == status]
        if session_key is not None:
            tasks = [task for task in tasks if task.session_key == session_key]
        return tasks[offset : offset + limit]

    def count_tasks(self, *, status: str | None = None, session_key: str | None = None) -> int:
        return len(self.list_tasks(status=status, session_key=session_key, limit=1_000_000, offset=0))

    def list_tasks_by_statuses(
        self,
        statuses: list[str],
        *,
        session_key: str | None = None,
        owner_key: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[TaskRun]:
        if not statuses:
            return []
        where_sql, params = _task_status_filter_sql(statuses, session_key=session_key, owner_key=owner_key)
        connection = self.connection_factory()
        rows = connection.execute(
            f"""
            SELECT
                task_run_id, owner_key, session_key, current_step_run_id,
                queue_status, claim_owner, queued_at, claimed_at,
                lease_expires_at, heartbeat_at, next_attempt_at,
                attempts, last_claim_error, revision, updated_at, anchor_payload
            FROM run_anchors
            WHERE {where_sql}
            ORDER BY updated_at DESC, created_at DESC
            LIMIT %s OFFSET %s
            """,
            (*params, max(1, int(limit)), max(0, int(offset))),
        ).fetchall()
        tasks: list[TaskRun] = []
        for row in rows:
            normalized = _normalize_row(row) or {}
            task = _task_from_payload((normalized.get("anchor_payload") or {}).get("task"))
            if task is None:
                continue
            _apply_anchor_queue_fields(task, normalized)
            tasks.append(task)
        return tasks

    def count_tasks_by_statuses(self, statuses: list[str], *, session_key: str | None = None, owner_key: str | None = None) -> int:
        if not statuses:
            return 0
        where_sql, params = _task_status_filter_sql(statuses, session_key=session_key, owner_key=owner_key)
        connection = self.connection_factory()
        row = connection.execute(
            f"""
            SELECT COUNT(*)
            FROM run_anchors
            WHERE {where_sql}
            """,
            tuple(params),
        ).fetchone()
        if row is None:
            return 0
        if isinstance(row, dict):
            return int(row.get("count") or row.get("count(*)") or 0)
        return int(row[0] or 0)

    def create_step(self, step: StepRun) -> StepRun:
        now_dt = utc_now()
        step.created_at = step.created_at or now_dt
        step.updated_at = now_dt
        self._save_step_anchor(step)
        return step

    def update_step(self, step: StepRun) -> StepRun:
        step.updated_at = utc_now()
        self._save_step_anchor(step)
        return step

    def get_step(self, step_run_id: str) -> StepRun | None:
        anchor = self.get_step_anchor(step_run_id)
        if not anchor:
            return None
        return _step_from_payload((anchor.get("anchor_payload") or {}).get("step"))

    def list_steps(self, task_run_id: str) -> list[StepRun]:
        connection = self.connection_factory()
        rows = connection.execute(
            "SELECT * FROM step_anchors WHERE task_run_id = %s ORDER BY step_order, created_at",
            (task_run_id,),
        ).fetchall()
        steps = [_step_from_payload((_normalize_row(row) or {}).get("anchor_payload", {}).get("step")) for row in rows]
        return [step for step in steps if step is not None]

    def append_event(self, event: TaskEventEnvelope) -> TaskEventEnvelope:
        anchor = self.get_run_anchor(event.task_run_id)
        if anchor is None:
            return event
        payload = dict(anchor.get("anchor_payload") or {})
        events = list(payload.get("events") or [])
        events.append(event.model_dump(by_alias=False))
        payload["events"] = events[-500:]
        self.upsert_run_anchor(
            event.task_run_id,
            {
                "owner_key": anchor["owner_key"],
                "session_id": anchor.get("session_id"),
                "session_key": anchor.get("session_key"),
                "current_step_run_id": anchor.get("current_step_run_id"),
                "durable_status": anchor.get("durable_status", "OPEN"),
                "queue_status": anchor.get("queue_status", "queued"),
                "claim_owner": anchor.get("claim_owner"),
                "queued_at": anchor.get("queued_at"),
                "claimed_at": anchor.get("claimed_at"),
                "lease_expires_at": anchor.get("lease_expires_at"),
                "heartbeat_at": anchor.get("heartbeat_at"),
                "next_attempt_at": anchor.get("next_attempt_at"),
                "attempts": anchor.get("attempts"),
                "last_claim_error": anchor.get("last_claim_error"),
                "agent_profile_id": anchor.get("agent_profile_id"),
                "agent_profile_version": anchor.get("agent_profile_version"),
                "agent_config_snapshot": anchor.get("agent_config_snapshot", {}),
                "anchor_payload": payload,
            },
        )
        return event

    def list_events(self, task_run_id: str) -> list[TaskEventEnvelope]:
        anchor = self.get_run_anchor(task_run_id)
        if anchor is None:
            return []
        return [TaskEventEnvelope(**event) for event in (anchor.get("anchor_payload") or {}).get("events", [])]

    def create_approval_request(self, task_run_id: str, step_run_id: str, payload: dict) -> dict[str, Any]:
        approval_id = new_id("approval")
        created_at = utc_now().isoformat()
        connection = self.connection_factory()
        connection.execute(
            """
            INSERT INTO approval_requests (
                approval_id, owner_user_id, task_run_id, step_run_id, tool_call_id, status,
                request_payload, response_payload, created_at, resolved_at
            )
            VALUES (%s, %s, %s, %s, %s, 'PENDING', %s::jsonb, '{}'::jsonb, %s, NULL)
            """,
            (
                approval_id,
                payload.get("owner_user_id") or _owner_user_id((self.get_run_anchor(task_run_id) or {}).get("owner_key")),
                task_run_id,
                step_run_id,
                payload.get("pending_tool_call_id") or payload.get("tool_call_id"),
                _json(payload),
                created_at,
            ),
        )
        connection.commit()
        return {
            "approval_id": approval_id,
            "task_run_id": task_run_id,
            "step_run_id": step_run_id,
            "status": "PENDING",
            "request_payload": payload,
            "response_payload": {},
            "created_at": created_at,
            "resolved_at": None,
        }

    def resolve_approval_request(self, approval_id: str, payload: dict) -> dict[str, Any] | None:
        return self._finish_approval(approval_id, status="RESOLVED", response_payload=payload)

    def cancel_approval_request(self, approval_id: str) -> dict[str, Any] | None:
        return self._finish_approval(approval_id, status="CANCELED", response_payload={"canceled": True})

    def get_open_approval(self, task_run_id: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute(
            """
            SELECT * FROM approval_requests
            WHERE task_run_id = %s AND status = 'PENDING'
            ORDER BY created_at
            LIMIT 1
            """,
            (task_run_id,),
        ).fetchone()
        return _approval_from_row(row)

    def create_provider_oauth_state(self, provider_name: str, state: str, redirect_uri: str, code_verifier: str | None = None) -> dict[str, Any]:
        created_at = utc_now()
        expires_at = created_at + timedelta(minutes=10)
        code_verifier_secret_ref = f"provider-oauth-state:{provider_name}:{state}"
        connection = self.connection_factory()
        connection.execute(
            """
            INSERT INTO provider_oauth_states (
                provider_name, state, redirect_uri, code_verifier_secret_ref,
                status, expires_at, created_at, consumed_at
            )
            VALUES (%s, %s, %s, %s, 'PENDING', %s, %s, NULL)
            ON CONFLICT (provider_name, state) DO UPDATE SET
                redirect_uri = EXCLUDED.redirect_uri,
                code_verifier_secret_ref = EXCLUDED.code_verifier_secret_ref,
                status = 'PENDING',
                expires_at = EXCLUDED.expires_at,
                created_at = EXCLUDED.created_at,
                consumed_at = NULL
            """,
            (provider_name, state, redirect_uri, code_verifier_secret_ref, expires_at.isoformat(), created_at.isoformat()),
        )
        connection.commit()
        return {
            "state": state,
            "provider_name": provider_name,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "status": "PENDING",
            "created_at": created_at.isoformat(),
            "consumed_at": None,
        }

    def get_provider_oauth_state(self, provider_name: str, state: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute(
            "SELECT * FROM provider_oauth_states WHERE provider_name = %s AND state = %s AND status = 'PENDING'",
            (provider_name, state),
        ).fetchone()
        if row is None:
            return None
        record = dict(row)
        return {
            "state": record["state"],
            "provider_name": record["provider_name"],
            "redirect_uri": record["redirect_uri"],
            "code_verifier": None,
            "status": record["status"],
            "created_at": _iso(record.get("created_at")),
            "consumed_at": _iso(record.get("consumed_at")),
        }

    def consume_provider_oauth_state(self, provider_name: str, state: str) -> dict[str, Any] | None:
        existing = self.get_provider_oauth_state(provider_name, state)
        if existing is None:
            return None
        consumed_at = utc_now().isoformat()
        connection = self.connection_factory()
        connection.execute(
            "UPDATE provider_oauth_states SET status = 'CONSUMED', consumed_at = %s WHERE provider_name = %s AND state = %s",
            (consumed_at, provider_name, state),
        )
        connection.commit()
        existing["status"] = "CONSUMED"
        existing["consumed_at"] = consumed_at
        return existing

    def delete_provider_oauth_states(self, provider_name: str) -> int:
        connection = self.connection_factory()
        result = connection.execute("DELETE FROM provider_oauth_states WHERE provider_name = %s", (provider_name,))
        connection.commit()
        return int(getattr(result, "rowcount", 0) or 0)

    def upsert_provider_token(self, provider_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        token_secret_ref = f"provider-token:{provider_name}:access"
        refresh_secret_ref = f"provider-token:{provider_name}:refresh" if payload.get("refresh_token") else None
        metadata = {
            "expires_at": payload.get("expires_at"),
            "raw_payload_keys": sorted((payload.get("raw_payload") or {}).keys()),
        }
        connection = self.connection_factory()
        connection.execute(
            """
            INSERT INTO provider_tokens (
                provider_name, token_secret_ref, refresh_secret_ref, token_type,
                scope_text, expires_at, token_metadata, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now(), now())
            ON CONFLICT (provider_name) DO UPDATE SET
                token_secret_ref = EXCLUDED.token_secret_ref,
                refresh_secret_ref = EXCLUDED.refresh_secret_ref,
                token_type = EXCLUDED.token_type,
                scope_text = EXCLUDED.scope_text,
                expires_at = EXCLUDED.expires_at,
                token_metadata = EXCLUDED.token_metadata,
                updated_at = now()
            """,
            (
                provider_name,
                token_secret_ref,
                refresh_secret_ref,
                payload.get("token_type"),
                payload.get("scope_text", ""),
                payload.get("expires_at"),
                _json(metadata),
            ),
        )
        connection.commit()
        # 실제 secret 원문은 DB에 남기지 않고, OAuth callback 요청 메모리 안에서만 돌려준다.
        return {**payload, "provider_name": provider_name, "token_secret_ref": token_secret_ref, "refresh_secret_ref": refresh_secret_ref}

    def get_provider_token(self, provider_name: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute("SELECT * FROM provider_tokens WHERE provider_name = %s", (provider_name,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        scope_text = record.get("scope_text") or ""
        metadata = _json_load(record.get("token_metadata"), {})
        return {
            "provider_name": record["provider_name"],
            "access_token": None,
            "refresh_token": None,
            "token_type": record.get("token_type"),
            "scope_text": scope_text,
            "scopes": [scope.strip() for scope in scope_text.split(",") if scope.strip()],
            "expires_at": _iso(record.get("expires_at") or metadata.get("expires_at")),
            "raw_payload": metadata,
            "created_at": _iso(record.get("created_at")),
            "updated_at": _iso(record.get("updated_at")),
            "token_secret_ref": record.get("token_secret_ref"),
            "refresh_secret_ref": record.get("refresh_secret_ref"),
        }

    def delete_provider_token(self, provider_name: str) -> bool:
        connection = self.connection_factory()
        result = connection.execute("DELETE FROM provider_tokens WHERE provider_name = %s", (provider_name,))
        connection.commit()
        return bool(getattr(result, "rowcount", 0) or 0)

    def get_agent_profile(self, profile_key: str, *, owner_key: str = "system", profile_version: int | None = None) -> dict[str, Any] | None:
        """실행 시점에 주입할 agent profile snapshot을 읽는다."""

        version = int(profile_version or 1)
        connection = self.connection_factory()
        row = connection.execute(
            """
            SELECT * FROM ai_agent_profiles
            WHERE owner_key = %s AND profile_key = %s AND profile_version = %s
            """,
            (owner_key, profile_key, version),
        ).fetchone()
        record = _normalize_row(row)
        if record is None:
            return None
        for key in ("config_snapshot", "delegation_policy"):
            record[key] = _json_load(record.get(key), {})
        return record

    def _save_task_anchor(self, task: TaskRun) -> None:
        existing = self.get_run_anchor(task.task_run_id) or {}
        payload = dict(existing.get("anchor_payload") or {})
        task.queue_status = _effective_queue_status(task)
        if task.queue_status in {"terminal", "canceled"}:
            task.claim_owner = None
            task.lease_expires_at = None
            task.heartbeat_at = None
        payload["task"] = _task_payload(task)
        agent_config_snapshot = _agent_config_snapshot_from_task(task)
        agent_profile_id, agent_profile_version = _agent_profile_ref_from_task(task)
        # anchor_payload의 events는 append_event가 관리하므로 TaskRun 저장 때 지우지 않는다.
        # agent_config_snapshot은 TaskRun input과 별도 컬럼에도 남겨 재시작 시
        # 설정 원본을 anchor JSON 파싱 없이 확인할 수 있게 한다.
        self.upsert_run_anchor(
            task.task_run_id,
            {
                "owner_key": task.owner_key,
                "owner_user_id": _owner_user_id(task.owner_key),
                "session_id": payload.get("transcript_session_id"),
                "session_key": task.session_key,
                "current_step_run_id": task.current_step_run_id,
                "durable_status": _durable_status(task.status),
                "queue_status": task.queue_status,
                "claim_owner": task.claim_owner,
                "queued_at": task.queued_at or task.created_at or utc_now(),
                "claimed_at": task.claimed_at,
                "lease_expires_at": task.lease_expires_at,
                "heartbeat_at": task.heartbeat_at,
                "next_attempt_at": task.next_attempt_at,
                "attempts": task.attempts,
                "last_claim_error": task.last_claim_error,
                "agent_profile_id": agent_profile_id,
                "agent_profile_version": agent_profile_version,
                "agent_config_snapshot": agent_config_snapshot,
                "anchor_payload": payload,
            },
        )

    def _save_step_anchor(self, step: StepRun) -> None:
        existing = self.get_step_anchor(step.step_run_id) or {}
        payload = dict(existing.get("anchor_payload") or {})
        payload["step"] = _step_payload(step)
        self.upsert_step_anchor(
            step.step_run_id,
            {
                "task_run_id": step.task_run_id,
                "worker_session_id": ((step.detail_json or {}).get("agentDetail") or {}).get("workerSessionId"),
                "step_order": step.step_order,
                "step_type": step.step_type,
                "durable_status": _durable_status(step.status),
                "anchor_payload": payload,
            },
        )

    def _load_all_tasks(self) -> list[TaskRun]:
        connection = self.connection_factory()
        rows = connection.execute("SELECT * FROM run_anchors ORDER BY updated_at DESC, created_at DESC").fetchall()
        tasks: list[TaskRun] = []
        for row in rows:
            normalized = _normalize_row(row) or {}
            task = _task_from_payload((normalized.get("anchor_payload") or {}).get("task"))
            if task is None:
                continue
            _apply_anchor_queue_fields(task, normalized)
            tasks.append(task)
        return tasks

    def _finish_approval(self, approval_id: str, *, status: str, response_payload: dict[str, Any]) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute(
            "SELECT * FROM approval_requests WHERE approval_id = %s AND status = 'PENDING'",
            (approval_id,),
        ).fetchone()
        if row is None:
            return None
        resolved_at = utc_now().isoformat()
        result = connection.execute(
            """
            UPDATE approval_requests
            SET status = %s, response_payload = %s::jsonb, resolved_at = %s
            WHERE approval_id = %s AND status = 'PENDING'
            """,
            (status, _json(response_payload), resolved_at, approval_id),
        )
        connection.commit()
        if getattr(result, "rowcount", 1) == 0:
            return None
        record = _approval_from_row(row)
        if record is None:
            return None
        record["status"] = status
        record["response_payload"] = response_payload
        record["resolved_at"] = resolved_at
        return record


def _required(payload: dict[str, Any], key: str) -> Any:
    value = payload.get(key)
    if value in {None, ""}:
        raise ValueError(f"{key} is required")
    return value


def _task_status_filter_sql(
    statuses: list[str],
    *,
    session_key: str | None = None,
    owner_key: str | None = None,
) -> tuple[str, tuple[Any, ...]]:
    normalized_statuses = sorted({str(status).upper() for status in statuses if str(status).strip()})
    if not normalized_statuses:
        return "FALSE", ()
    status_placeholders = ", ".join(["%s"] * len(normalized_statuses))
    clauses = [f"anchor_payload->'task'->>'status' IN ({status_placeholders})"]
    params: list[Any] = list(normalized_statuses)

    durable_statuses = _durable_statuses_for_task_statuses(normalized_statuses)
    if durable_statuses:
        durable_placeholders = ", ".join(["%s"] * len(durable_statuses))
        clauses.append(f"durable_status IN ({durable_placeholders})")
        params.extend(durable_statuses)

    queue_statuses = _queue_statuses_for_task_statuses(normalized_statuses)
    if queue_statuses:
        queue_placeholders = ", ".join(["%s"] * len(queue_statuses))
        clauses.append(f"queue_status IN ({queue_placeholders})")
        params.extend(queue_statuses)

    if owner_key is not None:
        clauses.append("owner_key = %s")
        params.append(owner_key)
    if session_key is not None:
        clauses.append("session_key = %s")
        params.append(session_key)
    return " AND ".join(clauses), tuple(params)


def _durable_statuses_for_task_statuses(statuses: list[str]) -> list[str]:
    durable_statuses: set[str] = set()
    for status in statuses:
        durable_statuses.add(_durable_status(status))
    return sorted(durable_statuses)


def _queue_statuses_for_task_statuses(statuses: list[str]) -> list[str]:
    status_set = set(statuses)
    queue_statuses: set[str] = set()
    if status_set & _ACTIVE_TASK_STATUSES:
        # active 목록은 기존 partial index 조건과 같은 queue_status 범위로 먼저 좁힌다.
        queue_statuses.update(_ACTIVE_QUEUE_STATUSES)
    if status_set & _TERMINAL_TASK_STATUSES:
        queue_statuses.update(_TERMINAL_QUEUE_STATUSES)
    return sorted(queue_statuses)


def _json(value: Any) -> str:
    return json.dumps(_sanitize_json_value(value or {}), ensure_ascii=False, sort_keys=True)


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_json_value(item) for key, item in value.items()}
    return value


def _json_load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _normalize_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if isinstance(row, dict):
        normalized = dict(row)
    else:
        normalized = dict(row)
    for key in ("anchor_payload", "agent_config_snapshot", "input_payload", "result_summary", "request_payload", "response_payload"):
        value = normalized.get(key)
        if isinstance(value, str):
            normalized[key] = json.loads(value)
    return normalized


def _apply_anchor_queue_fields(task: TaskRun, row: dict[str, Any]) -> None:
    task.queue_status = row.get("queue_status") or task.queue_status
    task.claim_owner = row.get("claim_owner") or task.claim_owner
    task.queued_at = _dt(row.get("queued_at")) or task.queued_at
    task.claimed_at = _dt(row.get("claimed_at")) or task.claimed_at
    task.lease_expires_at = _dt(row.get("lease_expires_at")) or task.lease_expires_at
    task.heartbeat_at = _dt(row.get("heartbeat_at")) or task.heartbeat_at
    task.next_attempt_at = _dt(row.get("next_attempt_at")) or task.next_attempt_at
    task.attempts = int(row.get("attempts") or task.attempts or 0)
    task.last_claim_error = row.get("last_claim_error") or task.last_claim_error
    task.revision = int(row.get("revision") or task.revision or 0)
    task.updated_at = _dt(row.get("updated_at")) or task.updated_at


def _task_payload(task: TaskRun) -> dict[str, Any]:
    return {
        "task_run_id": task.task_run_id,
        "task_type": task.task_type,
        "current_step_run_id": task.current_step_run_id,
        "owner_key": task.owner_key,
        "session_key": task.session_key,
        "status": task.status,
        "title": task.title,
        "input_payload": task.input_payload,
        "result_payload": task.result_payload,
        "todo_state": task.todo_state,
        "wait_payload": task.wait_payload,
        "error_message": task.error_message,
        "progress_summary": task.progress_summary,
        "queue_status": task.queue_status,
        "claim_owner": task.claim_owner,
        "queued_at": _iso(task.queued_at),
        "claimed_at": _iso(task.claimed_at),
        "lease_expires_at": _iso(task.lease_expires_at),
        "heartbeat_at": _iso(task.heartbeat_at),
        "next_attempt_at": _iso(task.next_attempt_at),
        "attempts": task.attempts,
        "last_claim_error": task.last_claim_error,
        "revision": task.revision,
        "created_at": _iso(task.created_at),
        "started_at": _iso(task.started_at),
        "updated_at": _iso(task.updated_at),
        "ended_at": _iso(task.ended_at),
    }


def _agent_config_snapshot_from_task(task: TaskRun) -> dict[str, Any]:
    """TaskRun input에서 재시작 가능한 실행 설정만 durable anchor 컬럼으로 분리한다."""

    input_payload = dict(task.input_payload or {})
    settings_snapshot = input_payload.get("settings_snapshot")
    snapshot = dict(settings_snapshot) if isinstance(settings_snapshot, dict) else {}
    for source_key, target_key in (
        ("model", "model"),
        ("system_prompt_snapshot", "systemPrompt"),
        ("enabled_toolsets", "toolsets"),
        ("delegation_policy", "delegationPolicy"),
    ):
        value = input_payload.get(source_key)
        if value is not None and target_key not in snapshot:
            snapshot[target_key] = value
    return snapshot


def _agent_profile_ref_from_task(task: TaskRun) -> tuple[str | None, int | None]:
    input_payload = dict(task.input_payload or {})
    profile = input_payload.get("targetAgentProfile")
    if not isinstance(profile, dict):
        profile = input_payload.get("target_agent_profile")
    if not isinstance(profile, dict):
        return None, None
    profile_id = str(profile.get("profileId") or profile.get("profile_id") or "").strip()
    if not profile_id:
        return None, None
    raw_version = profile.get("profileVersion") or profile.get("profile_version")
    try:
        profile_version = int(raw_version) if raw_version is not None else None
    except (TypeError, ValueError):
        profile_version = None
    return profile_id, profile_version


def _task_from_payload(payload: dict[str, Any] | None) -> TaskRun | None:
    if not payload:
        return None
    return TaskRun(
        task_run_id=payload["task_run_id"],
        task_type=payload["task_type"],
        current_step_run_id=payload.get("current_step_run_id"),
        owner_key=payload["owner_key"],
        session_key=payload.get("session_key"),
        status=payload["status"],
        title=payload.get("title"),
        input_payload=payload.get("input_payload") or {},
        result_payload=payload.get("result_payload") or {},
        todo_state=payload.get("todo_state") or {},
        wait_payload=payload.get("wait_payload") or {},
        error_message=payload.get("error_message"),
        progress_summary=payload.get("progress_summary"),
        queue_status=payload.get("queue_status"),
        claim_owner=payload.get("claim_owner"),
        queued_at=_dt(payload.get("queued_at")),
        claimed_at=_dt(payload.get("claimed_at")),
        lease_expires_at=_dt(payload.get("lease_expires_at")),
        heartbeat_at=_dt(payload.get("heartbeat_at")),
        next_attempt_at=_dt(payload.get("next_attempt_at")),
        attempts=int(payload.get("attempts") or 0),
        last_claim_error=payload.get("last_claim_error"),
        revision=int(payload.get("revision") or 0),
        created_at=_dt(payload.get("created_at")),
        started_at=_dt(payload.get("started_at")),
        updated_at=_dt(payload.get("updated_at")),
        ended_at=_dt(payload.get("ended_at")),
    )


def _step_payload(step: StepRun) -> dict[str, Any]:
    return {
        "step_run_id": step.step_run_id,
        "task_run_id": step.task_run_id,
        "step_order": step.step_order,
        "step_type": step.step_type,
        "status": step.status,
        "title": step.title,
        "input_payload": step.input_payload,
        "output_payload": step.output_payload,
        "wait_payload": step.wait_payload,
        "detail_json": step.detail_json,
        "summary_message": step.summary_message,
        "error_message": step.error_message,
        "created_at": _iso(step.created_at),
        "updated_at": _iso(step.updated_at),
        "started_at": _iso(step.started_at),
        "ended_at": _iso(step.ended_at),
    }


def _step_from_payload(payload: dict[str, Any] | None) -> StepRun | None:
    if not payload:
        return None
    return StepRun(
        step_run_id=payload["step_run_id"],
        task_run_id=payload["task_run_id"],
        step_order=int(payload["step_order"]),
        step_type=payload["step_type"],
        status=payload["status"],
        title=payload.get("title"),
        input_payload=payload.get("input_payload") or {},
        output_payload=payload.get("output_payload") or {},
        wait_payload=payload.get("wait_payload") or {},
        detail_json=payload.get("detail_json") or {},
        summary_message=payload.get("summary_message"),
        error_message=payload.get("error_message"),
        created_at=_dt(payload.get("created_at")),
        updated_at=_dt(payload.get("updated_at")),
        started_at=_dt(payload.get("started_at")),
        ended_at=_dt(payload.get("ended_at")),
    )


def _approval_from_row(row: Any) -> dict[str, Any] | None:
    record = _normalize_row(row)
    if record is None:
        return None
    return {
        "approval_id": record["approval_id"],
        "task_run_id": record["task_run_id"],
        "step_run_id": record["step_run_id"],
        "status": record["status"],
        "request_payload": record.get("request_payload") or {},
        "response_payload": record.get("response_payload") or {},
        "created_at": _iso(record.get("created_at")),
        "resolved_at": _iso(record.get("resolved_at")),
    }


def _durable_status(status: str) -> str:
    if status == "WAITING":
        return "WAITING"
    if status in {"COMPLETED", "FAILED", "CANCELED"}:
        return "TERMINAL"
    return "OPEN"


def _queue_status_from_task_status(status: str) -> str:
    if status == "PENDING":
        return "queued"
    if status == "RUNNING":
        return "running"
    if status == "WAITING":
        return "waiting"
    if status == "CANCELED":
        return "canceled"
    if status in {"COMPLETED", "FAILED"}:
        return "terminal"
    return "queued"


def _effective_queue_status(task: TaskRun) -> str:
    status = task.status
    current = task.queue_status
    if status in {"COMPLETED", "FAILED"}:
        return "terminal"
    if status == "CANCELED":
        return "canceled"
    if status == "WAITING":
        return "waiting"
    if status == "RUNNING":
        return "running"
    if status == "PENDING" and current == "running":
        return "running"
    if status == "PENDING" and current in {"queued", "failed_retry"}:
        return current
    return _queue_status_from_task_status(status)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _dt(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _owner_user_id(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
