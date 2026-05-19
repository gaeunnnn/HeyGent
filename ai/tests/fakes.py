from __future__ import annotations

from copy import deepcopy
from datetime import timedelta
from typing import Any

from app.contracts.event.task_events import TaskEventEnvelope
from app.core.time import utc_now
from app.core.utils.ids import new_id
from app.domain.orchestration.run_lifecycle import classify_task_run_liveness
from app.domain.agents import BUILTIN_AGENT_TEMPLATES, DEFAULT_SESSION_TEMPLATE_KEYS, MAIN_AGENT_TEMPLATE
from app.domain.tasks.models import StepRun, TaskRun


class InMemoryTaskRepository:
    storage_backend = "postgres"

    def __init__(self) -> None:
        self.tasks: dict[str, TaskRun] = {}
        self.steps: dict[str, StepRun] = {}
        self.events: dict[str, list[TaskEventEnvelope]] = {}
        self.approvals: dict[str, dict[str, Any]] = {}
        self.provider_states: dict[tuple[str, str], dict[str, Any]] = {}
        self.provider_tokens: dict[str, dict[str, Any]] = {}

    def create_task(self, task: TaskRun) -> TaskRun:
        saved = deepcopy(task)
        now = utc_now()
        saved.created_at = saved.created_at or now
        saved.updated_at = saved.updated_at or now
        task.created_at = task.created_at or saved.created_at
        task.updated_at = saved.updated_at
        self.tasks[saved.task_run_id] = saved
        return deepcopy(saved)

    def create_direct_task(self, task: TaskRun) -> TaskRun:
        task.queue_status = "running"
        task.claim_owner = None
        task.claimed_at = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        task.next_attempt_at = None
        task.attempts = int(task.attempts or 0)
        return self.create_task(task)

    def create_pending_task(self, task: TaskRun) -> TaskRun:
        now = utc_now()
        task.status = "PENDING"
        task.queue_status = "queued"
        task.queued_at = task.queued_at or now
        task.next_attempt_at = task.next_attempt_at or now
        task.claim_owner = None
        task.claimed_at = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        return self.create_task(task)

    def claim_next_task(self, *, claim_owner: str, lease_seconds: int = 300) -> TaskRun | None:
        now = utc_now()
        candidates = [
            task
            for task in self.tasks.values()
            if task.queue_status in {"queued", "failed_retry"} and (task.next_attempt_at is None or task.next_attempt_at <= now)
        ]
        candidates.sort(key=lambda task: task.queued_at or task.created_at or now)
        if not candidates:
            return None
        task = deepcopy(candidates[0])
        task.status = "RUNNING"
        task.queue_status = "claimed"
        task.claim_owner = claim_owner
        task.claimed_at = now
        task.heartbeat_at = now
        task.lease_expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
        task.attempts = int(task.attempts or 0) + 1
        self.tasks[task.task_run_id] = deepcopy(task)
        return deepcopy(task)

    def heartbeat_task_claim(self, task_run_id: str, *, claim_owner: str, lease_seconds: int = 300) -> TaskRun | None:
        task = self.tasks.get(task_run_id)
        if task is None or task.claim_owner != claim_owner:
            return None
        now = utc_now()
        task.queue_status = "running"
        task.heartbeat_at = now
        task.lease_expires_at = now + timedelta(seconds=max(1, int(lease_seconds)))
        task.updated_at = now
        return deepcopy(task)

    def fail_task_claim(self, task_run_id: str, *, claim_owner: str, error_message: str, retry: bool = False) -> TaskRun | None:
        task = self.tasks.get(task_run_id)
        if task is None or task.claim_owner != claim_owner:
            return None
        task.status = "PENDING" if retry else "FAILED"
        task.queue_status = "failed_retry" if retry else "terminal"
        task.error_message = error_message
        task.last_claim_error = error_message
        task.claim_owner = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        task.next_attempt_at = utc_now() + timedelta(seconds=10) if retry else None
        task.updated_at = utc_now()
        if not retry:
            task.ended_at = task.ended_at or task.updated_at
        return deepcopy(task)

    def recover_stale_task_run(self, task_run_id: str, *, reason: str) -> TaskRun | None:
        task = self.tasks.get(task_run_id)
        if task is None or task.status not in {"PENDING", "RUNNING"}:
            return None
        now = utc_now()
        task.status = "FAILED"
        task.queue_status = "terminal"
        task.error_message = "실행 상태가 만료되어 자동 복구되었습니다."
        task.last_claim_error = reason
        task.claim_owner = None
        task.lease_expires_at = None
        task.heartbeat_at = None
        task.next_attempt_at = None
        task.updated_at = now
        task.ended_at = task.ended_at or now
        return deepcopy(task)

    def recover_stale_task_runs(self, *, orphan_after_seconds: int = 300, limit: int = 100) -> list[TaskRun]:
        recovered: list[TaskRun] = []
        for task in list(self.tasks.values()):
            if len(recovered) >= max(1, int(limit)):
                break
            liveness = classify_task_run_liveness(task, orphan_after_seconds=orphan_after_seconds)
            if not liveness.should_recover:
                continue
            saved = self.recover_stale_task_run(task.task_run_id, reason=liveness.reason)
            if saved is not None:
                recovered.append(saved)
        return recovered

    def update_task(self, task: TaskRun) -> TaskRun:
        saved = deepcopy(task)
        saved.updated_at = utc_now()
        task.updated_at = saved.updated_at
        self.tasks[saved.task_run_id] = saved
        return deepcopy(saved)

    def get_task(self, task_run_id: str) -> TaskRun | None:
        task = self.tasks.get(task_run_id)
        return deepcopy(task) if task is not None else None

    def list_tasks(self, *, status: str | None = None, session_key: str | None = None, limit: int = 20, offset: int = 0) -> list[TaskRun]:
        tasks = self._filter_tasks(statuses=[status] if status else None, session_key=session_key)
        return deepcopy(tasks[offset : offset + limit])

    def count_tasks(self, *, status: str | None = None, session_key: str | None = None) -> int:
        return len(self._filter_tasks(statuses=[status] if status else None, session_key=session_key))

    def list_tasks_by_statuses(self, statuses: list[str], *, session_key: str | None = None, limit: int = 50, offset: int = 0) -> list[TaskRun]:
        tasks = self._filter_tasks(statuses=statuses, session_key=session_key)
        return deepcopy(tasks[offset : offset + limit])

    def count_tasks_by_statuses(self, statuses: list[str], *, session_key: str | None = None) -> int:
        return len(self._filter_tasks(statuses=statuses, session_key=session_key))

    def _filter_tasks(self, *, statuses: list[str] | None = None, session_key: str | None = None) -> list[TaskRun]:
        status_set = set(statuses or [])
        tasks = [
            task
            for task in self.tasks.values()
            if (not status_set or task.status in status_set) and (session_key is None or task.session_key == session_key)
        ]
        return sorted(tasks, key=lambda task: task.created_at or utc_now(), reverse=True)

    def create_step(self, step: StepRun) -> StepRun:
        saved = deepcopy(step)
        now = utc_now()
        saved.created_at = saved.created_at or now
        saved.updated_at = saved.updated_at or now
        step.created_at = step.created_at or saved.created_at
        step.updated_at = saved.updated_at
        self.steps[saved.step_run_id] = saved
        return deepcopy(saved)

    def update_step(self, step: StepRun) -> StepRun:
        saved = deepcopy(step)
        saved.updated_at = utc_now()
        step.updated_at = saved.updated_at
        self.steps[saved.step_run_id] = saved
        return deepcopy(saved)

    def get_step(self, step_run_id: str) -> StepRun | None:
        step = self.steps.get(step_run_id)
        return deepcopy(step) if step is not None else None

    def list_steps(self, task_run_id: str) -> list[StepRun]:
        steps = [step for step in self.steps.values() if step.task_run_id == task_run_id]
        steps.sort(key=lambda step: step.step_order)
        return deepcopy(steps)

    def append_event(self, event: TaskEventEnvelope) -> TaskEventEnvelope:
        sequence = len(self.events.get(event.task_run_id, [])) + 1
        saved = event.model_copy(update={"sequence": sequence, "event_id_alias": event.event_id})
        self.events.setdefault(event.task_run_id, []).append(saved)
        return saved

    def list_events(self, task_run_id: str) -> list[TaskEventEnvelope]:
        return [event.model_copy() for event in self.events.get(task_run_id, [])]

    def create_approval_request(self, task_run_id: str, step_run_id: str, payload: dict) -> dict[str, Any]:
        approval = {
            "approval_id": new_id("approval"),
            "task_run_id": task_run_id,
            "step_run_id": step_run_id,
            "status": "PENDING",
            "request_payload": deepcopy(payload),
            "response_payload": {},
            "payload": deepcopy(payload),
            "created_at": utc_now().isoformat(),
            "requested_at": utc_now().isoformat(),
            "can_approve": True,
            "can_reject": True,
        }
        approval.update(deepcopy(payload))
        self.approvals[approval["approval_id"]] = approval
        return deepcopy(approval)

    def resolve_approval_request(self, approval_id: str, payload: dict) -> dict[str, Any] | None:
        return self._close_approval(approval_id, "RESOLVED", payload)

    def cancel_approval_request(self, approval_id: str) -> dict[str, Any] | None:
        return self._close_approval(approval_id, "CANCELED", {})

    def _close_approval(self, approval_id: str, status: str, payload: dict) -> dict[str, Any] | None:
        approval = self.approvals.get(approval_id)
        if approval is None or approval["status"] != "PENDING":
            return None
        approval["status"] = status
        approval["response"] = deepcopy(payload)
        approval["response_payload"] = deepcopy(payload)
        approval["can_approve"] = False
        approval["can_reject"] = False
        return deepcopy(approval)

    def get_open_approval(self, task_run_id: str) -> dict[str, Any] | None:
        for approval in self.approvals.values():
            if approval["task_run_id"] == task_run_id and approval["status"] == "PENDING":
                return deepcopy(approval)
        return None

    def create_provider_oauth_state(self, provider_name: str, state: str, redirect_uri: str, code_verifier: str | None = None) -> dict[str, Any]:
        record = {
            "provider_name": provider_name,
            "state": state,
            "redirect_uri": redirect_uri,
            "code_verifier": code_verifier,
            "status": "PENDING",
        }
        self.provider_states[(provider_name, state)] = record
        return deepcopy(record)

    def get_provider_oauth_state(self, provider_name: str, state: str) -> dict[str, Any] | None:
        record = self.provider_states.get((provider_name, state))
        return deepcopy(record) if record is not None else None

    def consume_provider_oauth_state(self, provider_name: str, state: str) -> dict[str, Any] | None:
        record = self.provider_states.get((provider_name, state))
        if record is None:
            return None
        record["status"] = "CONSUMED"
        return deepcopy(record)

    def delete_provider_oauth_states(self, provider_name: str) -> int:
        keys = [key for key in self.provider_states if key[0] == provider_name]
        for key in keys:
            del self.provider_states[key]
        return len(keys)

    def upsert_provider_token(self, provider_name: str, payload: dict[str, Any]) -> dict[str, Any]:
        record = deepcopy(payload)
        scope_text = str(record.get("scope_text") or "")
        record["provider_name"] = provider_name
        record["scopes"] = [scope.strip() for scope in scope_text.replace(",", " ").split() if scope.strip()]
        record["updated_at"] = utc_now().isoformat()
        self.provider_tokens[provider_name] = record
        return deepcopy(record)

    def get_provider_token(self, provider_name: str) -> dict[str, Any] | None:
        record = self.provider_tokens.get(provider_name)
        return deepcopy(record) if record is not None else None

    def delete_provider_token(self, provider_name: str) -> bool:
        return self.provider_tokens.pop(provider_name, None) is not None


class InMemoryTranscriptStore:
    def __init__(self) -> None:
        self.sessions: dict[str, dict[str, Any]] = {}
        self.messages: dict[str, list[dict[str, Any]]] = {}

    def create_session(
        self,
        *,
        session_id: str,
        session_key: str,
        source: str,
        user_id: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        parent_session_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> str:
        now = utc_now()
        owner_user_id = _owner_user_id(user_id)
        self.sessions[session_id] = {
            "id": session_id,
            "session_key": session_key,
            "source": source,
            "session_source": source,
            "user_id": user_id,
            "owner_user_id": owner_user_id,
            "owner_key": user_id,
            "model": model,
            "system_prompt": system_prompt,
            "parent_session_id": parent_session_id,
            "title": title,
            "metadata": {
                **({"system_prompt_snapshot": system_prompt} if system_prompt else {}),
                **deepcopy(metadata or {}),
            },
            "settings": deepcopy(settings or {}),
            "created_at": now,
            "started_at": now,
            "updated_at": now,
            "ended_at": None,
            "end_reason": None,
            "message_count": 0,
            "history_version": 0,
            "running_task_run_id": None,
            "workspace_key": (metadata or {}).get("workspace_key"),
            "archived_at": None,
            "deleted_at": None,
            "deleted_by": None,
            "purge_after": None,
        }
        self.messages.setdefault(session_id, [])
        return session_id

    def end_session(self, session_id: str, *, end_reason: str | None = None) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        session["ended_at"] = utc_now()
        session["end_reason"] = end_reason
        session["updated_at"] = utc_now()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        session = self.sessions.get(session_id)
        return deepcopy(session) if session is not None else None

    def list_sessions(
        self,
        owner: str | None = None,
        *,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
        include_deleted: bool = False,
    ) -> list[dict[str, Any]]:
        effective_owner = owner if owner is not None else user_id
        sessions = [
            session
            for session in self.sessions.values()
            if effective_owner is None or session.get("user_id") == effective_owner
        ]
        if not include_deleted:
            sessions = [session for session in sessions if session.get("deleted_at") is None]
        if not include_archived:
            sessions = [session for session in sessions if session.get("archived_at") is None]
        sessions.sort(key=lambda session: session["updated_at"], reverse=True)
        return deepcopy(sessions[offset : offset + limit])

    def get_latest_session_by_key(self, session_key: str, *, owner: str | None = None) -> dict[str, Any] | None:
        sessions = [
            session
            for session in self.sessions.values()
            if session["session_key"] == session_key and (owner is None or session.get("user_id") == owner)
        ]
        if not sessions:
            return None
        return deepcopy(max(sessions, key=lambda session: session["created_at"]))

    def append_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str | None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        finish_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        message_id = len(self.messages.setdefault(session_id, [])) + 1
        message = {
            "id": message_id,
            "session_id": session_id,
            "role": role,
            "content": content,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "tool_calls": deepcopy(tool_calls or []),
            "finish_reason": finish_reason,
            "metadata": deepcopy(metadata or {}),
            "timestamp": utc_now(),
        }
        self.messages[session_id].append(message)
        if session_id in self.sessions:
            self.sessions[session_id]["message_count"] = len(self.messages[session_id])
            self.sessions[session_id]["updated_at"] = utc_now()
        return message_id

    def update_title(self, *, owner_key: str, session_id: str, title: str) -> dict[str, Any]:
        session = self._require_product_session(owner_key=owner_key, session_id=session_id)
        if session.get("running_task_run_id"):
            raise ValueError("session has a running task")
        if session.get("title") == title:
            return deepcopy(session)
        session["title"] = title
        session["history_version"] = int(session.get("history_version") or 0) + 1
        session["updated_at"] = utc_now()
        return deepcopy(session)

    def archive_session(self, *, owner_key: str, session_id: str, archived: bool = True) -> dict[str, Any]:
        session = self._require_product_session(owner_key=owner_key, session_id=session_id)
        if session.get("running_task_run_id"):
            raise ValueError("session has a running task")
        if (session.get("archived_at") is not None) == archived:
            return deepcopy(session)
        session["archived_at"] = utc_now() if archived else None
        session["updated_at"] = utc_now()
        return deepcopy(session)

    def delete_session(self, *, owner_key: str, session_id: str, deleted_by: str | None = None, retention_days: int = 30) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        self._require_product_session(owner_key=owner_key, session_id=session_id, allow_deleted=True)
        if session.get("running_task_run_id"):
            raise ValueError("session has a running task")
        if session.get("deleted_at") is None:
            now = utc_now()
            # soft delete는 메시지 배열을 지우지 않고 목록/생성 경계에서만 제외한다.
            session["deleted_at"] = now
            session["deleted_by"] = _owner_user_id(deleted_by or owner_key)
            session["purge_after"] = now
            session["archived_at"] = session.get("archived_at") or now
            session["updated_at"] = now
        return deepcopy(session)

    def update_session_settings(self, *, owner_key: str, session_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        session = self._require_product_session(owner_key=owner_key, session_id=session_id)
        if session.get("running_task_run_id"):
            raise ValueError("session has a running task")
        # settings는 다음 TaskRun에 복사되는 영속 원본이라 허용된 key만 저장한 값을 받는다.
        next_settings = {**deepcopy(session.get("settings") or {}), **deepcopy(settings)}
        if next_settings == session.get("settings"):
            return deepcopy(session)
        session["settings"] = next_settings
        session["history_version"] = int(session.get("history_version") or 0) + 1
        session["updated_at"] = utc_now()
        return deepcopy(session)

    def append_user_message_and_start_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        content: str,
        client_message_id: str,
        task_run_id: str,
        base_history_version: int,
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        session = self._require_product_session(owner_key=owner_key, session_id=session_id)
        for message in self.messages.get(session_id, []):
            metadata = dict(message.get("metadata") or {})
            if message.get("role") == "user" and metadata.get("client_message_id") == client_message_id:
                return {
                    "duplicate": True,
                    "session_id": session_id,
                    "message_id": message["id"],
                    "task_run_id": metadata.get("task_run_id"),
                    "base_history_version": max(0, int(session.get("history_version") or 0) - 1),
                    "after_user_message_version": int(session.get("history_version") or 0),
                    "completion_expected_version": int(session.get("history_version") or 0),
                    "running_task_run_id": session.get("running_task_run_id"),
                }
        if session.get("running_task_run_id"):
            raise ValueError("session already has a running task")
        current_version = int(session.get("history_version") or 0)
        if current_version != int(base_history_version):
            raise ValueError("history version mismatch")
        metadata = {
            "source": "api.session",
            "client_message_id": client_message_id,
            "task_run_id": task_run_id,
        }
        if metadata_patch:
            metadata.update(metadata_patch)
        message_id = self.append_message(
            session_id=session_id,
            role="user",
            content=content,
            metadata=metadata,
        )
        after_version = current_version + 1
        session["history_version"] = after_version
        session["running_task_run_id"] = task_run_id
        return {
            "duplicate": False,
            "session_id": session_id,
            "message_id": message_id,
            "task_run_id": task_run_id,
            "base_history_version": current_version,
            "after_user_message_version": after_version,
            "completion_expected_version": after_version,
            "running_task_run_id": task_run_id,
        }

    def append_assistant_message_and_finish_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        task_run_id: str,
        content: str,
        completion_expected_version: int,
        status: str,
    ) -> dict[str, Any]:
        session = self._require_product_session(owner_key=owner_key, session_id=session_id)
        if session.get("running_task_run_id") != task_run_id:
            raise ValueError("task does not own session running guard")
        if int(session.get("history_version") or 0) != int(completion_expected_version):
            raise ValueError("history version mismatch")
        message_id = self.append_message(
            session_id=session_id,
            role="assistant",
            content=content,
            metadata={"source": "api.session", "task_run_id": task_run_id, "status": status},
            finish_reason="stop" if status == "COMPLETED" else None,
        )
        result_version = int(completion_expected_version) + 1
        session["history_version"] = result_version
        session["running_task_run_id"] = None
        return {
            "session_id": session_id,
            "message_id": message_id,
            "task_run_id": task_run_id,
            "completion_expected_version": completion_expected_version,
            "completion_result_version": result_version,
        }

    def clear_stale_running_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        task_run_id: str,
    ) -> bool:
        session = self._require_product_session(owner_key=owner_key, session_id=session_id)
        if session.get("running_task_run_id") != task_run_id:
            return False
        session["running_task_run_id"] = None
        session["updated_at"] = utc_now()
        return True

    def list_messages(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        messages = self.messages.get(session_id, [])
        selected = messages if limit is None else messages[:limit]
        return deepcopy(selected)

    def search_sessions(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        raise ValueError("owner_key is required")

    def search_public_sessions(self, query: str, *, owner_key: str, workspace_key: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        if not owner_key:
            raise ValueError("owner_key is required")
        return self._search_by_source(query, owner_key=owner_key, source="api.session", workspace_key=workspace_key, limit=limit)

    def search_transcript_sessions(self, query: str, *, owner_key: str, limit: int = 10) -> list[dict[str, Any]]:
        if not owner_key:
            raise ValueError("owner_key is required")
        return self._search_by_source(query, owner_key=owner_key, source="agent.loop", workspace_key=None, limit=limit)

    def close(self) -> None:
        return None

    def _require_product_session(self, *, owner_key: str, session_id: str, allow_deleted: bool = False) -> dict[str, Any]:
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(session_id)
        metadata = dict(session.get("metadata") or {})
        source = session.get("session_source") or session.get("source") or metadata.get("source")
        if source != "api.session":
            raise ValueError("session is not a public product session")
        if str(session.get("user_id") or session.get("owner_key") or "") != str(owner_key):
            raise PermissionError("forbidden")
        if session.get("deleted_at") is not None and not allow_deleted:
            raise KeyError(session_id)
        return session

    def _search_by_source(
        self,
        query: str,
        *,
        owner_key: str | None,
        source: str,
        workspace_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        results: list[dict[str, Any]] = []
        for session_id, messages in self.messages.items():
            session = self.sessions.get(session_id)
            if session is None:
                continue
            metadata = dict(session.get("metadata") or {})
            session_source = session.get("session_source") or session.get("source") or metadata.get("source")
            if session_source != source:
                continue
            if session.get("deleted_at") is not None or session.get("archived_at") is not None:
                continue
            if owner_key is not None and str(session.get("user_id") or session.get("owner_key") or "") != str(owner_key):
                continue
            if workspace_key is not None and str(session.get("workspace_key") or "") != str(workspace_key):
                continue
            if any(query in str(message.get("content") or "") for message in messages):
                results.append(deepcopy(session))
            if len(results) >= limit:
                break
        return results


class InMemorySkillRepository:
    storage_backend = "memory"

    def __init__(self) -> None:
        self.catalog: dict[str, dict[str, Any]] = {}
        self.user_settings: dict[tuple[str, str], bool] = {}
        self.agent_settings: dict[str, list[str]] = {}

    def sync_builtin_catalog(self, skills: list[dict[str, Any]]) -> None:
        for skill in skills:
            name = str(skill.get("name") or "").strip()
            if not name:
                continue
            self.catalog[name] = {
                "skill_id": name,
                "name": name,
                "display_name": name.replace("-", " ").strip().title() or name,
                "description": str(skill.get("description") or ""),
                "source_type": "builtin",
                "source_path": str(skill.get("path") or "") or None,
                "version": 1,
                "default_enabled": True,
                "enabled": True,
                "metadata": {"hasBody": bool(str(skill.get("body") or "").strip())},
                "config_snapshot": {},
                "body": str(skill.get("body") or ""),
                "files": [],
            }

    def list_user_skills(self, *, owner_key: str, owner_user_id: int | None) -> list[dict[str, Any]]:
        return [self._with_user_enabled(owner_key, item) for item in sorted(self.catalog.values(), key=lambda row: row["name"])]

    def set_user_skill_enabled(
        self,
        *,
        owner_key: str,
        owner_user_id: int | None,
        skill_id: str,
        enabled: bool,
    ) -> dict[str, Any] | None:
        if skill_id not in self.catalog:
            return None
        self.user_settings[(owner_key, skill_id)] = bool(enabled)
        return self.get_user_skill(owner_key=owner_key, skill_id=skill_id)

    def get_user_skill(self, *, owner_key: str, skill_id: str) -> dict[str, Any] | None:
        item = self.catalog.get(skill_id)
        if item is None:
            return None
        return self._with_user_enabled(owner_key, item)

    def get_user_skill_detail(self, *, owner_key: str, skill_id: str) -> dict[str, Any] | None:
        item = self.get_user_skill(owner_key=owner_key, skill_id=skill_id)
        return dict(item) if item is not None else None

    def set_agent_skill_settings(self, *, profile_id: str, skill_ids: list[str]) -> None:
        self.agent_settings[profile_id] = [skill_id for skill_id in dict.fromkeys(skill_ids) if skill_id in self.catalog]

    def effective_skill_names(
        self,
        *,
        owner_key: str,
        profile_id: str | None = None,
        requested_skill_names: list[str] | None = None,
        explicit_agent_selection: bool = False,
    ) -> list[str]:
        enabled = {
            name
            for name in self.catalog
            if self.user_settings.get((owner_key, name), self.catalog[name].get("default_enabled", True))
        }
        requested = {str(item).strip() for item in requested_skill_names or [] if str(item).strip()}
        if explicit_agent_selection:
            return sorted(enabled.intersection(requested))
        if requested:
            matched = enabled.intersection(requested)
            if matched:
                return sorted(matched)
        if profile_id and self.agent_settings.get(profile_id):
            return sorted(enabled.intersection(self.agent_settings[profile_id]))
        if profile_id:
            return []
        return sorted(enabled)

    def _with_user_enabled(self, owner_key: str, item: dict[str, Any]) -> dict[str, Any]:
        copied = deepcopy(item)
        copied["enabled"] = bool(self.user_settings.get((owner_key, copied["skill_id"]), copied.get("default_enabled", True)))
        return copied


class InMemoryAgentRepository:
    storage_backend = "memory"

    def __init__(self) -> None:
        self.profiles: dict[str, dict[str, Any]] = {}
        self.bundles: dict[str, dict[str, Any]] = {}

    def ensure_builtin_templates(self) -> None:
        return None

    def list_templates(self) -> list[dict[str, Any]]:
        order = {template_key: index for index, template_key in enumerate(DEFAULT_SESSION_TEMPLATE_KEYS)}
        templates = [self._template_payload(template) for template in BUILTIN_AGENT_TEMPLATES]
        visible_templates = [
            template
            for template in templates
            if str(template.get("template_key") or template.get("templateKey") or "") in order
        ]
        return sorted(
            visible_templates,
            key=lambda item: order.get(str(item.get("template_key") or item.get("templateKey") or ""), len(order)),
        )

    def get_template(self, template_key: str) -> dict[str, Any] | None:
        for template in [MAIN_AGENT_TEMPLATE, *BUILTIN_AGENT_TEMPLATES]:
            if template.template_key == template_key:
                return self._template_payload(template)
        return None

    def create_default_session_agents(
        self,
        *,
        session_id: str,
        owner_key: str,
        owner_user_id: int | None,
    ) -> list[dict[str, Any]]:
        self.ensure_session_main_agent(
            session_id=session_id,
            owner_key=owner_key,
            owner_user_id=owner_user_id,
        )
        agents: list[dict[str, Any]] = []
        for template_key in DEFAULT_SESSION_TEMPLATE_KEYS:
            existing = self.get_session_agent_by_template(
                session_id=session_id,
                owner_key=owner_key,
                template_key=template_key,
            )
            if existing is not None:
                agents.append(existing)
                continue
            agents.append(
                self.create_session_agent_from_template(
                    session_id=session_id,
                    owner_key=owner_key,
                    owner_user_id=owner_user_id,
                    template_key=template_key,
                )
            )
        return agents

    def create_session_agent_from_template(
        self,
        *,
        session_id: str,
        owner_key: str,
        owner_user_id: int | None,
        template_key: str,
    ) -> dict[str, Any]:
        template = self.get_template(template_key)
        if template is None:
            raise KeyError(template_key)
        return self.create_session_agent(
            session_id=session_id,
            owner_key=owner_key,
            owner_user_id=owner_user_id,
            config_snapshot=dict(template["default_config_snapshot"]),
            delegation_policy=template.get("default_policy") or {"canDelegate": False},
            template_key=template_key,
            agent_type="user_subagent",
        )

    def ensure_session_main_agent(
        self,
        *,
        session_id: str,
        owner_key: str,
        owner_user_id: int | None,
    ) -> dict[str, Any]:
        existing = self.get_session_main_agent(session_id=session_id, owner_key=owner_key)
        if existing is not None:
            return existing
        return self.create_session_agent(
            session_id=session_id,
            owner_key=owner_key,
            owner_user_id=owner_user_id,
            config_snapshot=self._config_snapshot(MAIN_AGENT_TEMPLATE),
            delegation_policy={"canDelegate": True},
            template_key=MAIN_AGENT_TEMPLATE.template_key,
            agent_type="main",
        )

    def create_session_agent(
        self,
        *,
        session_id: str,
        owner_key: str,
        owner_user_id: int | None,
        config_snapshot: dict[str, Any],
        delegation_policy: dict[str, Any] | None = None,
        template_key: str | None = None,
        agent_type: str = "user_subagent",
    ) -> dict[str, Any]:
        profile_id = new_id("agent_profile")
        bundle_id = new_id("instruction_bundle")
        profile = {
            "profile_id": profile_id,
            "owner_key": owner_key,
            "owner_user_id": owner_user_id,
            "session_id": session_id,
            "profile_key": f"session.{session_id}.{profile_id}",
            "profile_version": 1,
            "agent_type": agent_type,
            "provider_name": config_snapshot.get("adapterType"),
            "model_name": config_snapshot.get("model"),
            "config_snapshot": deepcopy(config_snapshot),
            "delegation_policy": deepcopy(delegation_policy or {"canDelegate": False}),
            "template_key": template_key,
            "bundle_id": bundle_id,
            "entry_document_key": config_snapshot.get("entryDocumentKey") or "AGENTS.md",
            "instruction_mode": "managed",
        }
        self.profiles[profile_id] = profile
        self.bundles[bundle_id] = {
            "bundle_id": bundle_id,
            "profile_id": profile_id,
            "mode": "managed",
            "entry_document_key": profile["entry_document_key"],
            "documents": deepcopy(config_snapshot.get("documents") or []),
        }
        return deepcopy(profile)

    def list_session_agents(self, *, session_id: str, owner_key: str) -> list[dict[str, Any]]:
        return [
            deepcopy(profile)
            for profile in self.profiles.values()
            if profile.get("session_id") == session_id
            and profile.get("owner_key") == owner_key
            and profile.get("agent_type") == "user_subagent"
        ]

    def get_session_main_agent(self, *, session_id: str, owner_key: str) -> dict[str, Any] | None:
        for profile in self.profiles.values():
            if (
                profile.get("session_id") == session_id
                and profile.get("owner_key") == owner_key
                and profile.get("agent_type") == "main"
            ):
                return deepcopy(profile)
        return None

    def get_session_agent(self, *, profile_id: str, owner_key: str) -> dict[str, Any] | None:
        profile = self.profiles.get(profile_id)
        if profile is None or profile.get("owner_key") != owner_key:
            return None
        return deepcopy(profile)

    def update_session_agent(
        self,
        *,
        session_id: str,
        owner_key: str,
        profile_id: str,
        config_snapshot: dict[str, Any],
        delegation_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        profile = self.profiles.get(profile_id)
        if profile is None or profile.get("owner_key") != owner_key or profile.get("session_id") != session_id:
            return None
        profile["profile_version"] = int(profile.get("profile_version") or 1) + 1
        profile["provider_name"] = config_snapshot.get("adapterType")
        profile["model_name"] = config_snapshot.get("model")
        profile["config_snapshot"] = deepcopy(config_snapshot)
        if delegation_policy is not None:
            profile["delegation_policy"] = deepcopy(delegation_policy)
        profile["entry_document_key"] = config_snapshot.get("entryDocumentKey") or "AGENTS.md"
        bundle = self.bundles.get(str(profile.get("bundle_id") or ""))
        if bundle is not None:
            bundle["entry_document_key"] = profile["entry_document_key"]
            bundle["documents"] = deepcopy(config_snapshot.get("documents") or [])
        return deepcopy(profile)

    def get_session_agent_by_template(self, *, session_id: str, owner_key: str, template_key: str) -> dict[str, Any] | None:
        for profile in self.profiles.values():
            if (
                profile.get("session_id") == session_id
                and profile.get("owner_key") == owner_key
                and profile.get("template_key") == template_key
                and profile.get("agent_type") == "user_subagent"
            ):
                return deepcopy(profile)
        return None

    def get_instruction_bundle(self, *, profile_id: str, owner_key: str) -> dict[str, Any] | None:
        profile = self.get_session_agent(profile_id=profile_id, owner_key=owner_key)
        if profile is None:
            return None
        bundle = self.bundles.get(str(profile.get("bundle_id") or ""))
        if bundle is None:
            return None
        return deepcopy(bundle)

    @classmethod
    def _template_payload(cls, template) -> dict[str, Any]:
        return {
            "template_id": f"system:agent-template:{template.template_key}:1",
            "templateKey": template.template_key,
            "template_key": template.template_key,
            "default_config_snapshot": cls._config_snapshot(template),
            "default_policy": {"canDelegate": False},
        }

    @staticmethod
    def _config_snapshot(template) -> dict[str, Any]:
        return {
            "templateKey": template.template_key,
            "displayName": template.display_name,
            "name": template.name,
            "role": template.role,
            "title": template.title,
            "description": template.description,
            "adapterType": template.adapter_type,
            "model": template.model,
            "profileImage": template.profile_image,
            "skills": list(template.skills),
            "entryDocumentKey": "AGENTS.md",
            "documents": [
                {"documentKey": key, "displayName": display_name, "content": content}
                for key, display_name, content in template.documents
            ],
        }


def _owner_user_id(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None
