from __future__ import annotations

import asyncio
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
import json
import logging
from typing import Any

from pydantic import BaseModel

from app.api.session_agent_profiles import (
    agent_profile_prompt_payload as _agent_profile_prompt_payload,
    instruction_bundle_prompt_payload as _instruction_bundle_prompt_payload,
    profile_model as _profile_model,
    profile_provider_name as _profile_provider_name,
)
from app.api.ws.command_types import (
    WebSocketAuthContext,
    WebSocketBackgroundContext,
    WebSocketCommandContext,
    WebSocketCommandError,
)
from app.api.memory_context import attach_persistent_memory_context
from app.api.memory_mark_used import mark_used_recalled_memories
from app.api.memory_observation import attach_memory_observation_to_task
from app.api.memory_writeback import writeback_persistent_memory_candidates
from app.contracts.task.task_status import TaskStatus
from app.core.time import utc_now
from app.core.utils.ids import new_id
from app.domain.orchestration.capabilities import apply_task_capabilities
from app.domain.orchestration.contracts import OrchestrationRequest
from app.domain.orchestration.run_lifecycle import classify_task_run_liveness
from app.domain.session.conversation_history import build_conversation_history
from app.domain.session.history_compaction import compact_conversation_history
from app.domain.session.session_runtime_state import get_system_prompt_snapshot
from app.domain.tasks.activity_transcript import build_activity_transcript
from app.domain.tasks.display_context import build_task_display_context
from app.domain.work import WorkService
logger = logging.getLogger(__name__)

_PUBLIC_SESSION_SOURCE = "api.session"
_TASK_TRANSCRIPT_SOURCE = "agent.loop"
_ACTIVE_TASK_STATUSES = [status.value for status in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.WAITING, TaskStatus.BLOCKED)]
_TERMINAL_TASK_STATUSES = {status.value for status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELED)}
_ACTIVE_DIRECT_RUN_TTL_SECONDS = 300
_SESSION_MESSAGES_LIST_RESULT_TYPE = "session.messages.list.result"
_TASK_RUNS_ACTIVE_LIST_RESULT_TYPE = "taskRuns.active.list.result"
_PROTECTED_SESSION_METADATA_KEYS = {
    "owner_key",
    "ownerUserId",
    "owner_user_id",
    "userId",
    "user_id",
    "source",
    "session_source",
    "messageCount",
    "message_count",
    "runningTaskRunId",
    "running_task_run_id",
    "historyVersion",
    "history_version",
    "archivedAt",
    "archived_at",
    "deletedAt",
    "deleted_at",
    "deletedBy",
    "deleted_by",
    "purgeAfter",
    "purge_after",
    "settings",
}
_SESSION_METADATA_PATCH_ALLOWLIST = {"pinned", "color", "tags", "description", "lastViewedAt", "last_viewed_at", "ui"}
_SESSION_SETTINGS_ALLOWLIST = {"model", "systemPrompt", "system_prompt", "toolsets", "delegationPolicy", "delegation_policy"}
_PUBLIC_SESSION_TOOLSETS = {"skills", "session", "planning", "web", "work", "messaging", "safe"}
_OPENAI_MODEL_FALLBACKS = (
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.4-nano",
    "gpt-5.2",
    "gpt-5.1",
    "gpt-5",
    "gpt-5-mini",
    "gpt-5-nano",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4o",
    "gpt-4o-mini",
)


class WebSocketCommandRouter:
    """인증 이후 WebSocket command/query를 처리한다.

    기존 gateway는 auth.start/auth.ok/subscribe.task/ping을 담당하고,
    이 라우터는 requestId가 있는 command/query 응답을 같은 연결로 되돌린다.
    """

    def __init__(self) -> None:
        self._accepted_messages: dict[tuple[str, str, str], dict[str, Any]] = {}
        self._accepted_resumes: dict[tuple[str, str], dict[str, Any]] = {}
        self._accepted_cancels: dict[tuple[str, str], dict[str, Any]] = {}
        self._accepted_session_commands: dict[tuple[str, str, str], tuple[str, str, dict[str, Any]]] = {}

    async def handle(self, message: dict[str, Any], context: WebSocketCommandContext) -> bool:
        message_type = message.get("type")
        if not isinstance(message_type, str):
            return False

        handlers = {
            "session.list": self._session_list,
            "session.messages.list": self._session_messages_list,
            "session.message.create": self._session_message_create,
            "session.message.retry": self._session_message_retry,
            "session.message.undo": self._session_message_undo,
            "session.history.compact": self._session_history_compact,
            "session.update": self._session_update,
            "session.archive": self._session_archive,
            "session.delete": self._session_delete,
            "session.settings.update": self._session_settings_update,
            "model.options": self._model_options,
            "taskRuns.active.list": self._task_runs_active_list,
            "taskRun.snapshot.get": self._task_run_snapshot_get,
            "taskRun.events.replay": self._task_run_events_replay,
            "taskRun.resume": self._task_run_resume,
            "taskRun.cancel": self._task_run_cancel,
        }
        handler = handlers.get(message_type)
        if handler is None:
            return False

        request_id = message.get("requestId")
        payload = message.get("payload") or {}
        if not isinstance(payload, dict):
            await self._send_error(context, request_id, "invalid_payload", "payload must be an object")
            return True

        callback_start_index = len(context.after_response_callbacks)
        try:
            response_type, response_payload = await handler(payload, context)
        except WebSocketCommandError as error:
            await self._send_error(context, request_id, error.code, error.message, retryable=error.retryable)
            return True
        except Exception:
            logger.exception("WebSocket command 처리 중 예외가 발생했습니다: %s", message_type)
            await self._send_error(context, request_id, "internal_error", "command failed", retryable=True)
            return True

        await self._send_result(context, response_type, request_id, response_payload)
        callbacks = context.after_response_callbacks[callback_start_index:]
        del context.after_response_callbacks[callback_start_index:]
        for callback in callbacks:
            callback()
        return True

    async def send_unknown_command_error(self, message: dict[str, Any], context: WebSocketCommandContext) -> None:
        message_type = message.get("type")
        request_id = message.get("requestId")
        await self._send_error(
            context,
            request_id,
            "unknown_command",
            f"unsupported command type: {message_type}",
        )

    def _replay_session_command(
        self,
        context: WebSocketCommandContext,
        *,
        session_id: str,
        command_id: str,
        signature: str,
    ) -> tuple[str, dict[str, Any]] | None:
        key = (context.auth.user_id, session_id, command_id)
        session_store = context.websocket.app.state.session_store
        if hasattr(session_store, "get_session_command_receipt"):
            receipt = session_store.get_session_command_receipt(
                owner_key=context.auth.user_id,
                session_id=session_id,
                client_command_id=command_id,
            )
            if receipt is not None:
                if receipt.get("command_signature") != signature:
                    raise WebSocketCommandError("conflict", "clientCommandId was already used with a different payload")
                response_payload = dict(receipt.get("response_payload") or {})
                response_type = str(response_payload.pop("_response_type"))
                return response_type, response_payload
        existing = self._accepted_session_commands.get(key)
        if existing is None:
            return None
        existing_signature, response_type, response_payload = existing
        if existing_signature != signature:
            raise WebSocketCommandError("conflict", "clientCommandId was already used with a different payload")
        return response_type, dict(response_payload)

    def _remember_session_command(
        self,
        context: WebSocketCommandContext,
        *,
        session_id: str,
        command_id: str,
        signature: str,
        response: tuple[str, dict[str, Any]],
    ) -> None:
        response_type, response_payload = response
        session_store = context.websocket.app.state.session_store
        durable_payload = {"_response_type": response_type, **_jsonable(response_payload)}
        if hasattr(session_store, "remember_session_command_receipt"):
            session_store.remember_session_command_receipt(
                owner_key=context.auth.user_id,
                session_id=session_id,
                client_command_id=command_id,
                command_signature=signature,
                response_payload=durable_payload,
            )
        self._accepted_session_commands[(context.auth.user_id, session_id, command_id)] = (
            signature,
            response_type,
            _jsonable(response_payload),
        )

    async def _session_list(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        page = _positive_int(payload.get("page"), default=1, maximum=10_000)
        page_size = _positive_int(payload.get("pageSize", payload.get("page_size")), default=20, maximum=50)
        include_archived = bool(payload.get("includeArchived", payload.get("include_archived", False)))
        offset = (page - 1) * page_size
        session_store = context.websocket.app.state.session_store
        # 사용자별 세션은 최대 10개 보장 (제품 정책) — limit 을 작게 잡아 DB·메모리·정렬 비용 모두 절감.
        sessions = [
            session
            for session in session_store.list_sessions(
                user_id=context.auth.user_id,
                limit=10,
                offset=0,
                include_archived=include_archived,
            )
            if _is_public_session(session)
        ]
        sessions.sort(
            key=lambda session: (
                session.get("updated_at") or session.get("started_at"),
                session.get("archived_at") is not None,
            ),
            reverse=True,
        )
        selected = sessions[offset : offset + page_size]
        return (
            "session.list.result",
            {
                "items": [_public_session_payload(session, context=context) for session in selected],
                "page": page,
                "page_size": page_size,
                "total_count": len(sessions),
                "has_previous": page > 1,
                "has_next": offset + len(selected) < len(sessions),
            },
        )

    async def _session_messages_list(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        after_message_id = _optional_int(payload.get("afterMessageId", payload.get("after_message_id")))
        limit = _positive_int(payload.get("limit"), default=100, maximum=500)
        session = _get_public_session(context, session_id)
        _ensure_owner(context, session.get("user_id"))
        messages = context.websocket.app.state.session_store.list_messages(session_id)
        if after_message_id is not None:
            messages = [message for message in messages if int(message.get("id") or 0) > after_message_id]
        items = [_message_payload(message) for message in messages[:limit]]
        return (
            _SESSION_MESSAGES_LIST_RESULT_TYPE,
            {
                "session_id": session_id,
                "after_message_id": after_message_id,
                "limit": limit,
                "total_count": len(items),
                "next_after_message_id": items[-1]["id"] if items else None,
                "items": items,
                "messages": items,
            },
        )

    async def _session_message_create(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        content = _required_str(payload, "content")
        client_message_id = _required_str(payload, "clientMessageId", "client_message_id")
        session_id = _optional_str(payload.get("sessionId", payload.get("session_id")))
        model = _optional_str(payload.get("model"))
        input_payload = payload.get("inputPayload", payload.get("input_payload")) or {}
        if not isinstance(input_payload, dict):
            raise WebSocketCommandError("invalid_payload", "inputPayload must be an object")
        initial_settings_payload = payload.get("settings")
        if initial_settings_payload is not None and not isinstance(initial_settings_payload, dict):
            raise WebSocketCommandError("invalid_payload", "settings must be an object")
        initial_settings = _normalize_session_settings(initial_settings_payload) if isinstance(initial_settings_payload, dict) else {}

        idempotency_key = (context.auth.user_id, session_id or "", client_message_id)
        existing = self._accepted_messages.get(idempotency_key)
        if existing is not None:
            return "session.message.accepted", dict(existing)
        # 프로세스 메모리가 비어도 같은 clientMessageId로 이미 저장된 메시지가 있으면
        # 새 TaskRun을 만들지 않고 기존 accepted 응답을 재구성한다.
        durable_existing = _find_accepted_message_by_client_id(
            context,
            session_id=session_id,
            client_message_id=client_message_id,
        )
        if durable_existing is not None:
            self._accepted_messages[idempotency_key] = durable_existing
            return "session.message.accepted", dict(durable_existing)

        if session_id:
            if initial_settings:
                raise WebSocketCommandError("invalid_payload", "settings can only be used when creating a new session")
            session = _get_public_session(context, session_id)
            _ensure_owner(context, session.get("user_id"))
            session = _refresh_stale_running_guard(context, session)
            _ensure_session_idle(session)
        else:
            session = _create_public_session(context, content=content, model=model, settings=initial_settings)
            session_id = str(session["id"])

        session_store = context.websocket.app.state.session_store
        base_history_version = int(session.get("history_version") or 0)
        conversation_history = compact_conversation_history(
            build_conversation_history(session_store.list_messages(session_id))
        )
        task_input = dict(input_payload)
        task_input["sessionId"] = session_id
        task_input["ownerKey"] = context.auth.user_id
        task_input["ownerUserId"] = _owner_user_id(context.auth.user_id)
        settings_snapshot = _session_settings_snapshot(session)
        _seed_default_session_agents_if_requested(
            context.websocket.app.state,
            task_input=task_input,
            session_id=session_id,
            owner_key=context.auth.user_id,
        )
        main_profile = _attach_main_agent_context(
            context.websocket.app.state,
            task_input=task_input,
            session_id=session_id,
            owner_key=context.auth.user_id,
        )
        session_agent_profiles = _attach_session_agent_candidates(
            context.websocket.app.state,
            task_input=task_input,
            session_id=session_id,
            owner_key=context.auth.user_id,
        )
        if session_agent_profiles:
            task_input["allowSessionAgentRootWork"] = True
        profile_model = _profile_model(main_profile) if main_profile is not None else None
        effective_model = str(profile_model or settings_snapshot.get("model") or model or "").strip() or None
        if effective_model:
            task_input["model"] = effective_model
        profile_provider = _profile_provider_name(main_profile) if main_profile is not None else None
        if profile_provider:
            task_input["provider_name"] = profile_provider
        transcript_session_id = _create_task_transcript_session(
            session_store,
            session_id=session_id,
            owner_key=context.auth.user_id,
            title=session.get("title") or content[:120],
            model=effective_model,
        )
        task_input["prompt"] = content
        task_input["transcript_session_id"] = transcript_session_id
        task_input["conversation_history"] = conversation_history
        task_input["system_prompt_snapshot"] = get_system_prompt_snapshot(session)
        task_input["base_history_version"] = base_history_version
        _apply_session_settings_snapshot(task_input, settings_snapshot, session=session)
        work_id = _work_id_from_task_input(task_input)
        work_metadata: dict[str, Any] = {}
        if work_id is not None:
            work = _attach_work_context_or_ws_error(
                context,
                task_input=task_input,
                work_id=work_id,
                session_id=session_id,
                owner_key=context.auth.user_id,
            )
            work_metadata = {
                "work_id": work.work_id,
                "work_identifier": work.identifier,
                "work_title": work.title,
                "work_assignee_agent_id": work.assignee_agent_id,
            }
        apply_task_capabilities(
            task_input,
            skill_registry=getattr(context.websocket.app.state, "skill_registry", None),
            default_toolsets=_default_agent_loop_toolsets(context.websocket.app.state),
        )
        # token memory context는 durable payload에 넣지 않는다. backend 호출이 필요해지면
        # context.auth.access_token에서만 꺼내 쓰도록 경계를 고정한다.
        await attach_persistent_memory_context(
            app_state=context.websocket.app.state,
            task_input=task_input,
            user_id=str(context.auth.user_id),
            query=content,
            workspace_key=context.auth.workspace_key or session.get("workspace_key"),
        )

        handler = context.websocket.app.state.tool_registry.resolve()
        task = context.websocket.app.state.task_engine.planner.materialize_task(
            owner_key=context.auth.user_id,
            session_key=session_id,
            input_payload=task_input,
            handler=handler,
        )
        user_append = session_store.append_user_message_and_start_task(
            owner_key=context.auth.user_id,
            session_id=session_id,
            content=content,
            client_message_id=client_message_id,
            task_run_id=task.task_run_id,
            base_history_version=base_history_version,
            metadata_patch=work_metadata,
        )
        if user_append.get("duplicate"):
            accepted = {
                "session_id": session_id,
                "user_message_id": _stored_message_id(session_store, session_id=session_id, stored_ref=user_append["message_id"]),
                "assistant_message_id": _find_assistant_message_id_for_task(session_store, session_id, str(user_append["task_run_id"])),
                "task_run_id": str(user_append["task_run_id"]),
                "status": _task_status_for_payload(context, str(user_append["task_run_id"])),
                "client_message_id": client_message_id,
                "history_version": user_append["after_user_message_version"],
            }
            self._accepted_messages[idempotency_key] = accepted
            return "session.message.accepted", dict(accepted)
        task.input_payload = {
            **dict(task.input_payload or {}),
            "after_user_message_version": user_append["after_user_message_version"],
            "completion_expected_version": user_append["completion_expected_version"],
            "prompt_message_id": str(user_append["message_id"]),
            "promptMessageId": str(user_append["message_id"]),
        }
        task_execution_supervisor = getattr(context.websocket.app.state, "task_execution_supervisor", None)
        try:
            if task_execution_supervisor is not None:
                background_context = WebSocketBackgroundContext(websocket=context.websocket, send_json=context.send_json)

                async def finish_supervised_task(completed_task: Any) -> None:
                    await self._finish_created_message_task(
                        context=background_context,
                        session_id=session_id,
                        user_message_id=int(user_append["message_id"]),
                        task=task,
                        completed_task=completed_task,
                    )

                task = await task_execution_supervisor.submit(
                    OrchestrationRequest(
                        task_run_id=task.task_run_id,
                        owner_key=context.auth.user_id,
                        session_key=session_id,
                        input_payload=dict(task.input_payload or {}),
                    ),
                    on_complete=finish_supervised_task,
                )
            else:
                context.websocket.app.state.repository.create_direct_task(task)
            if work_id is not None:
                WorkService(context.websocket.app.state.work_repository).mark_run_started(
                    work_id=work_id,
                    task_run_id=task.task_run_id,
                )
        except Exception:
            session_store.clear_stale_running_task(
                owner_key=context.auth.user_id,
                session_id=session_id,
                task_run_id=task.task_run_id,
            )
            raise
        context.session_service.subscribe_task(
            session_id=context.gateway_session_id,
            websocket=context.websocket,
            task_run_id=task.task_run_id,
        )

        accepted = {
            "session_id": session_id,
            "user_message_id": _stored_message_id(session_store, session_id=session_id, stored_ref=user_append["message_id"]),
            "assistant_message_id": None,
            "task_run_id": task.task_run_id,
            "status": task.status,
            "client_message_id": client_message_id,
            "history_version": user_append["after_user_message_version"],
        }
        self._accepted_messages[idempotency_key] = accepted

        if task_execution_supervisor is None:
            def start_background_task() -> None:
                background_context = WebSocketBackgroundContext(websocket=context.websocket, send_json=context.send_json)
                background_task = asyncio.create_task(
                    self._run_created_message_task(
                        context=background_context,
                        session_id=session_id,
                        user_message_id=int(user_append["message_id"]),
                        task=task,
                        handler=handler,
                    )
                )
                context.background_tasks.add(background_task)
                background_task.add_done_callback(context.background_tasks.discard)

            # accepted frame을 먼저 보낸 뒤 agent.loop/task.event fan-out을 시작한다.
            context.after_response_callbacks.append(start_background_task)
        return "session.message.accepted", dict(accepted)

    async def _session_message_retry(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        target_message_id = _optional_str(payload.get("targetMessageId", payload.get("target_message_id")))
        model = _optional_str(payload.get("model"))
        session = _get_public_session(context, session_id)
        _ensure_owner(context, session.get("user_id"))
        session = _refresh_stale_running_guard(context, session)
        _ensure_session_idle(session)

        session_store = context.websocket.app.state.session_store
        retry_state = _prepare_retry_turn(
            session_store,
            owner_key=context.auth.user_id,
            session_id=session_id,
            target_message_id=target_message_id,
        )
        content = retry_state["content"]
        conversation_history = compact_conversation_history(build_conversation_history(retry_state["history_rows"]))
        try:
            settings_snapshot = _session_settings_snapshot(session)
            effective_model = str(settings_snapshot.get("model") or model or "").strip() or None
            transcript_session_id = _create_task_transcript_session(
                session_store,
                session_id=session_id,
                owner_key=context.auth.user_id,
                title=session.get("title") or str(content)[:120],
                model=effective_model,
            )
            task_input = {
                "prompt": content,
                "transcript_session_id": transcript_session_id,
                "conversation_history": conversation_history,
                "system_prompt_snapshot": get_system_prompt_snapshot(session),
                "base_history_version": retry_state["base_history_version"],
                "after_user_message_version": retry_state["completion_expected_version"],
                "completion_expected_version": retry_state["completion_expected_version"],
                "retry_source_message_id": retry_state["user_message_id"],
                "prompt_message_id": str(retry_state["user_message_id"]),
                "promptMessageId": str(retry_state["user_message_id"]),
                "client_command_id": command_id,
            }
            if effective_model:
                task_input["model"] = effective_model
            _apply_session_settings_snapshot(task_input, settings_snapshot, session=session)
            await attach_persistent_memory_context(
                app_state=context.websocket.app.state,
                task_input=task_input,
                user_id=str(context.auth.user_id),
                query=str(content),
                workspace_key=context.auth.workspace_key or session.get("workspace_key"),
            )
            handler = context.websocket.app.state.tool_registry.resolve()
            task = context.websocket.app.state.task_engine.planner.materialize_task(
                owner_key=context.auth.user_id,
                session_key=session_id,
                input_payload=task_input,
                handler=handler,
                task_run_id=retry_state["task_run_id"],
            )
            task_execution_supervisor = getattr(context.websocket.app.state, "task_execution_supervisor", None)
            if task_execution_supervisor is not None:
                background_context = WebSocketBackgroundContext(websocket=context.websocket, send_json=context.send_json)

                async def finish_supervised_retry(completed_task: Any) -> None:
                    await self._finish_created_message_task(
                        context=background_context,
                        session_id=session_id,
                        user_message_id=int(retry_state["user_message_id"]),
                        task=task,
                        completed_task=completed_task,
                    )

                task = await task_execution_supervisor.submit(
                    OrchestrationRequest(
                        task_run_id=task.task_run_id,
                        owner_key=context.auth.user_id,
                        session_key=session_id,
                        input_payload=dict(task.input_payload or {}),
                    ),
                    on_complete=finish_supervised_retry,
                )
            else:
                context.websocket.app.state.repository.create_direct_task(task)
            context.session_service.subscribe_task(
                session_id=context.gateway_session_id,
                websocket=context.websocket,
                task_run_id=task.task_run_id,
            )
        except Exception:
            session_store.clear_stale_running_task(
                owner_key=context.auth.user_id,
                session_id=session_id,
                task_run_id=str(retry_state["task_run_id"]),
            )
            raise
        accepted = {
            "session_id": session_id,
            "user_message_id": str(retry_state["user_message_id"]),
            "assistant_message_id": None,
            "task_run_id": task.task_run_id,
            "status": task.status,
            "client_command_id": command_id,
            "history_version": retry_state["completion_expected_version"],
        }

        if task_execution_supervisor is None:
            def start_background_task() -> None:
                background_context = WebSocketBackgroundContext(websocket=context.websocket, send_json=context.send_json)
                background_task = asyncio.create_task(
                    self._run_created_message_task(
                        context=background_context,
                        session_id=session_id,
                        user_message_id=int(retry_state["user_message_id"]),
                        task=task,
                        handler=handler,
                    )
                )
                context.background_tasks.add(background_task)
                background_task.add_done_callback(context.background_tasks.discard)

            context.after_response_callbacks.append(start_background_task)
        return "session.message.accepted", accepted

    async def _session_message_undo(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        until_message_id = _optional_str(payload.get("untilMessageId", payload.get("until_message_id")))
        session = _get_public_session(context, session_id)
        _ensure_owner(context, session.get("user_id"))
        session = _refresh_stale_running_guard(context, session)
        _ensure_session_idle(session)
        result = _truncate_public_session_tail(
            context.websocket.app.state.session_store,
            owner_key=context.auth.user_id,
            session_id=session_id,
            keep_through_message_id=until_message_id,
            default_remove_last=True,
        )
        return (
            "session.updated",
            {
                "session_id": session_id,
                "client_command_id": command_id,
                "history_version": result["history_version"],
                "messages": [_message_payload(message) for message in context.websocket.app.state.session_store.list_messages(session_id)],
            },
        )

    async def _session_history_compact(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        session = _get_public_session(context, session_id)
        _ensure_owner(context, session.get("user_id"))
        session = _refresh_stale_running_guard(context, session)
        _ensure_session_idle(session)
        history = compact_conversation_history(build_conversation_history(context.websocket.app.state.session_store.list_messages(session_id)))
        updated = _patch_public_session_metadata(
            context.websocket.app.state.session_store,
            owner_key=context.auth.user_id,
            session_id=session_id,
            metadata_patch={
                "compaction_count": int((session.get("metadata") or {}).get("compaction_count") or 0) + 1,
                "last_compacted_at": utc_now().isoformat(),
            },
            bump_history_version=True,
        )
        return (
            "session.updated",
            {
                "session_id": session_id,
                "client_command_id": command_id,
                "history_version": updated.get("history_version"),
                "history_preview": history,
                "messages": [_message_payload(message) for message in context.websocket.app.state.session_store.list_messages(session_id)],
            },
        )

    async def _session_update(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        title = _optional_str(payload.get("title"))
        metadata_patch = payload.get("metadataPatch", payload.get("metadata_patch"))
        if metadata_patch is not None and not isinstance(metadata_patch, dict):
            raise WebSocketCommandError("invalid_payload", "metadataPatch must be an object")
        if metadata_patch:
            _validate_metadata_patch(metadata_patch)
        signature = _session_command_signature("session.update", {"title": title, "metadataPatch": metadata_patch})
        replay = self._replay_session_command(context, session_id=session_id, command_id=command_id, signature=signature)
        if replay is not None:
            return replay
        session = _get_public_session(context, session_id)
        _ensure_owner(context, session.get("user_id"))
        session = _refresh_stale_running_guard(context, session)
        _ensure_session_idle(session)
        if title:
            try:
                _update_public_session_title(context.websocket.app.state.session_store, owner_key=context.auth.user_id, session_id=session_id, title=title)
            except ValueError as error:
                raise WebSocketCommandError("conflict", str(error), retryable=True) from error
            except PermissionError as error:
                raise WebSocketCommandError("forbidden", "forbidden") from error
            except KeyError as error:
                raise WebSocketCommandError("not_found", "session not found") from error
        if metadata_patch:
            _patch_public_session_metadata(
                context.websocket.app.state.session_store,
                owner_key=context.auth.user_id,
                session_id=session_id,
                metadata_patch=dict(metadata_patch),
                bump_history_version=True,
            )
        session = _get_public_session(context, session_id)
        response = (
            "session.updated",
            {
                "session_id": session_id,
                "client_command_id": command_id,
                "history_version": session.get("history_version"),
                "session": _public_session_payload(session, context=context),
                "messages": [_message_payload(message) for message in context.websocket.app.state.session_store.list_messages(session_id)],
            },
        )
        self._remember_session_command(context, session_id=session_id, command_id=command_id, signature=signature, response=response)
        return response

    async def _session_archive(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        archived = bool(payload.get("archived", True))
        signature = _session_command_signature("session.archive", {"archived": archived})
        replay = self._replay_session_command(context, session_id=session_id, command_id=command_id, signature=signature)
        if replay is not None:
            return replay
        session = _get_public_session(context, session_id)
        _ensure_owner(context, session.get("user_id"))
        session = _refresh_stale_running_guard(context, session)
        _ensure_session_idle(session)
        try:
            updated = context.websocket.app.state.session_store.archive_session(
                owner_key=context.auth.user_id,
                session_id=session_id,
                archived=archived,
            )
        except ValueError as error:
            raise WebSocketCommandError("conflict", str(error), retryable=True) from error
        except PermissionError as error:
            raise WebSocketCommandError("forbidden", "forbidden") from error
        except KeyError as error:
            raise WebSocketCommandError("not_found", "session not found") from error
        response = (
            "session.archived",
            {
                "session_id": session_id,
                "client_command_id": command_id,
                "archived": bool(updated.get("archived_at")),
                "session": _public_session_payload(updated, context=context),
            },
        )
        self._remember_session_command(context, session_id=session_id, command_id=command_id, signature=signature, response=response)
        return response

    async def _session_delete(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        signature = _session_command_signature("session.delete", {})
        replay = self._replay_session_command(context, session_id=session_id, command_id=command_id, signature=signature)
        if replay is not None:
            return replay
        session = _get_public_session(context, session_id, allow_deleted=True)
        _ensure_owner(context, session.get("user_id"))
        session = _refresh_stale_running_guard(context, session)
        _ensure_session_idle(session)
        try:
            deleted = context.websocket.app.state.session_store.delete_session(
                owner_key=context.auth.user_id,
                session_id=session_id,
                deleted_by=context.auth.user_id,
            )
        except ValueError as error:
            raise WebSocketCommandError("conflict", str(error), retryable=True) from error
        except PermissionError as error:
            raise WebSocketCommandError("forbidden", "forbidden") from error
        except KeyError as error:
            raise WebSocketCommandError("not_found", "session not found") from error
        response = (
            "session.deleted",
            {
                "session_id": session_id,
                "client_command_id": command_id,
                "deleted_at": deleted.get("deleted_at"),
                "purge_after": deleted.get("purge_after"),
            },
        )
        self._remember_session_command(context, session_id=session_id, command_id=command_id, signature=signature, response=response)
        return response

    async def _session_settings_update(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _required_str(payload, "sessionId", "session_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        settings_payload = payload.get("settings")
        if not isinstance(settings_payload, dict):
            raise WebSocketCommandError("invalid_payload", "settings must be an object")
        settings = _normalize_session_settings(settings_payload)
        signature = _session_command_signature("session.settings.update", settings)
        replay = self._replay_session_command(context, session_id=session_id, command_id=command_id, signature=signature)
        if replay is not None:
            return replay
        session = _get_public_session(context, session_id)
        _ensure_owner(context, session.get("user_id"))
        session = _refresh_stale_running_guard(context, session)
        _ensure_session_idle(session)
        try:
            updated = context.websocket.app.state.session_store.update_session_settings(
                owner_key=context.auth.user_id,
                session_id=session_id,
                settings=settings,
            )
        except ValueError as error:
            raise WebSocketCommandError("conflict", str(error), retryable=True) from error
        except PermissionError as error:
            raise WebSocketCommandError("forbidden", "forbidden") from error
        except KeyError as error:
            raise WebSocketCommandError("not_found", "session not found") from error
        response = (
            "session.settings.updated",
            {
                "session_id": session_id,
                "client_command_id": command_id,
                "settings": dict(updated.get("settings") or settings),
                "session": _public_session_payload(updated, context=context),
            },
        )
        self._remember_session_command(context, session_id=session_id, command_id=command_id, signature=signature, response=response)
        return response

    async def _model_options(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _optional_str(payload.get("sessionId", payload.get("session_id")))
        current_model = None
        if session_id:
            session = _get_public_session(context, session_id)
            _ensure_owner(context, session.get("user_id"))
            current_model = (_session_settings_snapshot(session).get("model") or session.get("model"))
        settings = context.websocket.app.state.settings
        default_model = str(current_model or getattr(settings, "openai_response_model", "") or "gpt-5.4")
        model_ids = await _list_openai_models_for_user(
            context.websocket.app.state,
            user_id=context.auth.user_id,
            fallback_model=default_model,
        )
        provider_models = [
            {
                "id": model_id,
                "label": model_id,
                "provider": "openai_api_key",
                "is_current": model_id == current_model or (current_model is None and model_id == default_model),
            }
            for model_id in model_ids
        ]
        providers = [
            {
                "slug": "openai_api_key",
                "provider_name": "openai_api_key",
                "models": provider_models,
                "is_current": any(model["is_current"] for model in provider_models),
                "total_models": len(provider_models),
                "warning": None,
                "health": {"provider_name": "openai_api_key", "configured": True, "connected": True},
            }
        ]
        gemini_models = [
            {
                "id": model_id,
                "label": model_id,
                "provider": "gemini_api_key",
                "is_current": model_id == current_model,
            }
            for model_id in ("gemini-2.5-pro", "gemini-2.5-flash")
        ]
        providers.append(
            {
                "slug": "gemini_api_key",
                "provider_name": "gemini_api_key",
                "models": gemini_models,
                "is_current": any(model["is_current"] for model in gemini_models),
                "total_models": len(gemini_models),
                "warning": None,
                "health": {"provider_name": "gemini_api_key", "configured": True, "connected": True},
            }
        )
        return ("model.options.result", {"model": default_model, "providers": providers, "models": provider_models})

    async def _task_runs_active_list(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        session_id = _optional_str(payload.get("sessionId", payload.get("session_id")))
        repository = context.websocket.app.state.repository
        projection = getattr(context.websocket.app.state, "task_projection_store", None)
        items_by_task_run_id: dict[str, dict[str, Any]] = {}

        if projection is not None and session_id:
            for task_run_id in projection.list_active_task_ids(session_key=session_id):
                task = projection.get_task_snapshot(task_run_id)
                canonical_task = repository.get_task(task_run_id)
                if canonical_task is None or str(canonical_task.owner_key) != str(context.auth.user_id):
                    continue
                if not _is_live_active_task(repository, canonical_task):
                    continue
                steps = _projection_steps(projection, canonical_task.task_run_id)
                items_by_task_run_id[canonical_task.task_run_id] = _active_task_payload(
                    canonical_task,
                    steps,
                    source="active",
                    repository=repository,
                )

        total = repository.count_tasks_by_statuses(
            _ACTIVE_TASK_STATUSES,
            session_key=session_id,
            owner_key=context.auth.user_id,
        )
        for task in repository.list_tasks_by_statuses(
            _ACTIVE_TASK_STATUSES,
            session_key=session_id,
            owner_key=context.auth.user_id,
            limit=max(total, 1),
            offset=0,
        ):
            if task.task_run_id in items_by_task_run_id or str(task.owner_key) != str(context.auth.user_id):
                continue
            if not _is_live_active_task(repository, task):
                continue
            items_by_task_run_id[task.task_run_id] = _active_task_payload(
                task,
                repository.list_steps(task.task_run_id),
                source="active",
                repository=repository,
            )
        items = list(items_by_task_run_id.values())
        return (
            _TASK_RUNS_ACTIVE_LIST_RESULT_TYPE,
            {
                "session_id": session_id,
                "items": items,
                "task_runs": items,
                "total_count": len(items),
            },
        )

    async def _task_run_snapshot_get(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        task_run_id = _required_str(payload, "taskRunId", "task_run_id")
        include_steps = bool(payload.get("includeSteps", payload.get("include_steps", True)))
        include_flow = bool(payload.get("includeFlow", payload.get("include_flow", False)))
        include_events = bool(payload.get("includeEvents", payload.get("include_events", True)))
        repository = context.websocket.app.state.repository
        task = repository.get_task(task_run_id)
        if task is None:
            raise WebSocketCommandError("not_found", "task not found")
        _ensure_owner(context, task.owner_key)
        steps = repository.list_steps(task_run_id) if include_steps or include_flow else []
        pending_approval = _pending_approval_payload(repository.get_open_approval(task_run_id))
        events = (
            _task_events_payload(
                repository=repository,
                projection=getattr(context.websocket.app.state, "task_projection_store", None),
                task_run_id=task_run_id,
            )
            if include_events
            else []
        )
        task_payload = _jsonable(task)
        task_payload["displayContext"] = build_task_display_context(task)
        snapshot = {
            "task": task_payload,
            "task_run": task_payload,
            "pending_approval": pending_approval,
            "approvals": [pending_approval] if pending_approval is not None else [],
            "events": events,
            "activity_items": build_activity_transcript(events),
            "activityItems": build_activity_transcript(events),
        }
        if include_steps:
            step_payloads = [_step_payload_with_display_context(task, step) for step in steps]
            snapshot["steps"] = step_payloads
            snapshot["step_runs"] = step_payloads
        if include_flow:
            snapshot["flow"] = {
                "task_run_id": task.task_run_id,
                "current_step_run_id": task.current_step_run_id,
                "nodes": [_step_payload_with_display_context(task, step) for step in steps],
                "edges": [
                    {"from_step_run_id": previous.step_run_id, "to_step_run_id": current.step_run_id, "relation": "next"}
                    for previous, current in zip(steps, steps[1:])
                ],
            }
        return "taskRun.snapshot.result", snapshot

    async def _task_run_events_replay(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        task_run_id = _required_str(payload, "taskRunId", "task_run_id")
        after_sequence = _optional_int(payload.get("afterSequence", payload.get("after_sequence")))
        limit = _positive_int(payload.get("limit"), default=200, maximum=500)
        repository = context.websocket.app.state.repository
        task = repository.get_task(task_run_id)
        if task is None:
            raise WebSocketCommandError("not_found", "task not found")
        _ensure_owner(context, task.owner_key)

        projection = getattr(context.websocket.app.state, "task_projection_store", None)
        retention_exceeded = False
        events: list[dict[str, Any]] = []
        if projection is not None:
            # Redis projection은 빠르지만 최근 구간만 보관한다.
            # afterSequence보다 앞 구간이 잘렸으면 durable event 저장소로 fallback해야 한다.
            events = projection.list_recent_events(task_run_id)
            if after_sequence is not None:
                events = [event for event in events if int(event.get("sequence") or 0) > after_sequence]
            events = events[:limit]
            if after_sequence is not None:
                latest_sequence = projection.get_latest_sequence(task_run_id)
                min_returned_sequence = min((int(event.get("sequence") or 0) for event in events), default=None)
                retention_exceeded = bool(
                    latest_sequence is not None
                    and latest_sequence > after_sequence
                    and (not events or (min_returned_sequence is not None and min_returned_sequence > after_sequence + 1))
                )

        if not events or retention_exceeded:
            # projection에서 못 찾은 구간은 DB에 저장된 canonical event로 복구한다.
            stored_events = repository.list_events(task_run_id)
            if after_sequence is not None:
                stored_events = [event for event in stored_events if int(event.sequence or 0) > after_sequence]
            durable_events = [_jsonable(event) for event in stored_events[:limit]]
            if durable_events:
                events = durable_events

        latest_sequence = max((int(event.get("sequence") or 0) for event in events), default=None)
        activity_items = build_activity_transcript(events)
        return (
            "taskRun.events.replay.result",
            {
                "task_run_id": task_run_id,
                "events": events,
                "activity_items": activity_items,
                "activityItems": activity_items,
                "latest_sequence": latest_sequence,
                "retention_exceeded": retention_exceeded,
            },
        )

    async def _task_run_resume(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        task_run_id = _required_str(payload, "taskRunId", "task_run_id")
        approval_id = _required_str(payload, "approvalId", "approval_id")
        command_id = _required_str(payload, "approvalResponseId", "approval_response_id", "clientCommandId", "client_command_id")
        resume_payload = payload.get("payload") or {}
        if not isinstance(resume_payload, dict):
            raise WebSocketCommandError("invalid_payload", "payload.payload must be an object")
        resume_payload = _normalize_resume_payload(resume_payload)
        accepted_key = (task_run_id, command_id)
        existing = self._accepted_resumes.get(accepted_key)
        if existing is not None:
            return "taskRun.resume.accepted", dict(existing)

        task = context.websocket.app.state.repository.get_task(task_run_id)
        if task is None:
            raise WebSocketCommandError("not_found", "task not found")
        _ensure_owner(context, task.owner_key)
        if task.status != TaskStatus.WAITING:
            raise WebSocketCommandError("conflict", "task is not waiting")
        approval = context.websocket.app.state.repository.get_open_approval(task_run_id)
        if approval is None or str(approval.get("approval_id") or "") != approval_id:
            raise WebSocketCommandError("conflict", "approval is not pending for this task")

        accepted = {
            "task_run_id": task_run_id,
            "approval_id": approval_id,
            "client_command_id": command_id,
        }
        self._accepted_resumes[accepted_key] = accepted
        background_task = asyncio.create_task(
            self._run_resume_task(
                context=WebSocketBackgroundContext(websocket=context.websocket, send_json=context.send_json),
                task_run_id=task_run_id,
                approval_id=approval_id,
                payload=resume_payload,
            )
        )
        context.background_tasks.add(background_task)
        background_task.add_done_callback(context.background_tasks.discard)
        return "taskRun.resume.accepted", dict(accepted)

    async def _task_run_cancel(self, payload: dict[str, Any], context: WebSocketCommandContext) -> tuple[str, dict[str, Any]]:
        task_run_id = _required_str(payload, "taskRunId", "task_run_id")
        command_id = _required_str(payload, "clientCommandId", "client_command_id")
        accepted_key = (task_run_id, command_id)
        existing = self._accepted_cancels.get(accepted_key)
        if existing is not None:
            return "taskRun.cancel.accepted", dict(existing)

        task = context.websocket.app.state.repository.get_task(task_run_id)
        if task is None:
            raise WebSocketCommandError("not_found", "task not found")
        _ensure_owner(context, task.owner_key)
        if task.status != TaskStatus.WAITING:
            raise WebSocketCommandError("conflict", "task is not waiting")

        accepted = {"task_run_id": task_run_id, "client_command_id": command_id}
        self._accepted_cancels[accepted_key] = accepted
        background_task = asyncio.create_task(
            self._run_cancel_task(
                context=WebSocketBackgroundContext(websocket=context.websocket, send_json=context.send_json),
                task_run_id=task_run_id,
            )
        )
        context.background_tasks.add(background_task)
        background_task.add_done_callback(context.background_tasks.discard)
        return "taskRun.cancel.accepted", dict(accepted)

    async def _run_created_message_task(self, *, context: WebSocketBackgroundContext, session_id: str, user_message_id: int, task: Any, handler: Any) -> None:
        try:
            # accepted는 "최종 답변 완료"가 아니라 durable 접수다.
            # task.created 이후부터는 기존 Task Engine 이벤트가 같은 구독 topic으로 흘러간다.
            await context.websocket.app.state.task_engine._emit("task.created", task)
            completed_task = await context.websocket.app.state.task_engine._execute_initial(
                task=task,
                handler=handler,
                resume_payload=None,
            )
            await self._finish_created_message_task(
                context=context,
                session_id=session_id,
                user_message_id=user_message_id,
                task=task,
                completed_task=completed_task,
            )
        except Exception:
            logger.exception("session.message.create background 실행에 실패했습니다.")
            _mark_ws_linked_work_run_failed(context, task=task)
            try:
                context.websocket.app.state.session_store.clear_stale_running_task(
                    owner_key=task.owner_key,
                    session_id=session_id,
                    task_run_id=task.task_run_id,
                )
            except Exception:
                logger.exception("session.message.create 실패 후 running guard 정리에 실패했습니다.")
            # accepted 이후 background 실행이 실패해도 client가 placeholder를 무기한 기다리면 안 된다.
            # 실패 frame은 durable TaskRun event와 별개로 현재 대화 UI의 pending assistant 상태를 닫는 역할을 한다.
            try:
                await context.send_json(
                    _event_frame(
                        "session.message.failed",
                        {
                            "session_id": session_id,
                            "message_id": f"failed:{task.task_run_id}",
                            "user_message_id": str(user_message_id),
                            "task_run_id": task.task_run_id,
                            "status": "FAILED",
                            "error": {
                                "code": "background_task_failed",
                                "message": "AI 응답 생성 중 오류가 발생했습니다.",
                                "retryable": True,
                            },
                        },
                    )
                )
            except Exception:
                logger.exception("session.message.failed frame 전송에 실패했습니다.")

    async def _finish_created_message_task(
        self,
        *,
        context: WebSocketBackgroundContext,
        session_id: str,
        user_message_id: int,
        task: Any,
        completed_task: Any,
    ) -> None:
            completed_status = str(completed_task.status)
            completion_expected_version = int((task.input_payload or {}).get("completion_expected_version") or 0)
            if completed_status == TaskStatus.WAITING.value:
                # WAITING은 사용자가 볼 최종 assistant 응답이 아니라 approval 대기 상태다.
                # running guard를 유지해야 resume이 같은 task ownership으로 이어진다.
                await context.send_json(
                    _event_frame(
                        "session.message.waiting",
                        {
                            "session_id": session_id,
                            "message_id": f"waiting:{completed_task.task_run_id}",
                            "user_message_id": str(user_message_id),
                            "task_run_id": completed_task.task_run_id,
                            "status": completed_status,
                            "pending_approval": _pending_approval_payload(
                                context.websocket.app.state.repository.get_open_approval(completed_task.task_run_id)
                            ),
                        },
                    )
                )
                return
            if completed_status != TaskStatus.COMPLETED.value:
                _apply_ws_linked_work_result(context, task=completed_task)
                context.websocket.app.state.session_store.clear_stale_running_task(
                    owner_key=completed_task.owner_key,
                    session_id=session_id,
                    task_run_id=completed_task.task_run_id,
                )
                await context.send_json(
                    _event_frame(
                        "session.message.failed",
                        {
                            "session_id": session_id,
                            "message_id": f"failed:{completed_task.task_run_id}",
                            "user_message_id": str(user_message_id),
                            "task_run_id": completed_task.task_run_id,
                            "status": completed_status,
                            "error": {
                                "code": "task_not_completed",
                                "message": _assistant_content_from_task(completed_task),
                                "retryable": completed_status in {TaskStatus.FAILED.value, TaskStatus.CANCELED.value},
                            },
                        },
                    )
                )
                return
            _apply_ws_linked_work_result(context, task=completed_task)
            content = _assistant_content_from_task(completed_task)
            assistant_append = context.websocket.app.state.session_store.append_assistant_message_and_finish_task(
                owner_key=completed_task.owner_key,
                session_id=session_id,
                task_run_id=completed_task.task_run_id,
                content=content,
                completion_expected_version=completion_expected_version,
                status=completed_status,
            )
            await context.send_json(
                _event_frame(
                    "taskRun.snapshot.result",
                    _task_snapshot_payload(completed_task),
                )
            )
            # 현재 Task Engine에는 토큰 단위 streaming hook이 없으므로 delta를 합성하지 않는다.
            # 프론트에는 durable assistant 메시지가 저장된 뒤 completed frame만 보낸다.
            await context.send_json(
                _event_frame(
                    "session.message.completed",
                    {
                        "session_id": session_id,
                        "message_id": _stored_message_id(
                            context.websocket.app.state.session_store,
                            session_id=session_id,
                            stored_ref=assistant_append["message_id"],
                        ),
                        "content": content,
                        "task_run_id": completed_task.task_run_id,
                        "status": completed_status,
                        "finish_reason": "stop",
                        "history_version": assistant_append["completion_result_version"],
                    },
                )
            )
            session = context.websocket.app.state.session_store.get_session(session_id) or {}
            writeback_observation = await writeback_persistent_memory_candidates(
                app_state=context.websocket.app.state,
                user_id=str(completed_task.owner_key),
                user_message=str((completed_task.input_payload or {}).get("prompt") or ""),
                assistant_message=content,
                session_id=session_id,
                workspace_key=str(session.get("workspace_key") or "") or None,
                task_run_id=completed_task.task_run_id,
                user_message_id=str(user_message_id),
                assistant_message_id=str(assistant_append["message_id"]),
                model=str((completed_task.input_payload or {}).get("model") or "") or None,
                provider_name=str(
                    (completed_task.input_payload or {}).get("provider_name")
                    or (completed_task.input_payload or {}).get("providerName")
                    or ""
                ) or None,
            )
            mark_used_observation = await mark_used_recalled_memories(
                app_state=context.websocket.app.state,
                task_input=dict(completed_task.input_payload or {}),
                user_id=str(completed_task.owner_key),
                assistant_message=content,
                task_run_id=completed_task.task_run_id,
            )
            attach_memory_observation_to_task(
                task=completed_task,
                repository=context.websocket.app.state.repository,
                writeback=writeback_observation,
                mark_used=mark_used_observation,
            )
            await context.send_json(
                _event_frame(
                    "taskRun.snapshot.result",
                    _task_snapshot_payload(completed_task),
                )
            )

    async def _run_resume_task(self, *, context: WebSocketBackgroundContext, task_run_id: str, approval_id: str, payload: dict[str, Any]) -> None:
        try:
            completed_task = await context.websocket.app.state.orchestrator.resume(task_run_id=task_run_id, approval_id=approval_id, payload=payload)
            await self._finalize_resumed_or_canceled_task(context=context, task=completed_task)
        except Exception:
            logger.exception("taskRun.resume background 실행에 실패했습니다.")

    async def _run_cancel_task(self, *, context: WebSocketBackgroundContext, task_run_id: str) -> None:
        try:
            completed_task = await context.websocket.app.state.orchestrator.cancel(task_run_id=task_run_id)
            await self._finalize_resumed_or_canceled_task(context=context, task=completed_task)
        except Exception:
            logger.exception("taskRun.cancel background 실행에 실패했습니다.")

    async def _finalize_resumed_or_canceled_task(self, *, context: WebSocketBackgroundContext, task: Any) -> None:
        session_id = str(getattr(task, "session_key", "") or "")
        if not session_id:
            return
        session_store = context.websocket.app.state.session_store
        session = session_store.get_session(session_id)
        if session is None or not _is_public_session(session):
            return
        status = str(getattr(task, "status", ""))
        if status == TaskStatus.WAITING.value:
            await context.send_json(
                _event_frame(
                    "session.message.waiting",
                    {
                        "session_id": session_id,
                        "message_id": f"waiting:{task.task_run_id}",
                        "task_run_id": task.task_run_id,
                        "status": status,
                        "pending_approval": _pending_approval_payload(
                            context.websocket.app.state.repository.get_open_approval(task.task_run_id)
                        ),
                    },
                )
            )
            return
        if status == TaskStatus.COMPLETED.value:
            content = _assistant_content_from_task(task)
            expected_version = int((getattr(task, "input_payload", {}) or {}).get("completion_expected_version") or session.get("history_version") or 0)
            assistant_append = session_store.append_assistant_message_and_finish_task(
                owner_key=str(getattr(task, "owner_key", "") or session.get("user_id") or ""),
                session_id=session_id,
                task_run_id=task.task_run_id,
                content=content,
                completion_expected_version=expected_version,
                status=status,
            )
            await context.send_json(
                _event_frame(
                    "session.message.completed",
                    {
                        "session_id": session_id,
                        "message_id": _stored_message_id(session_store, session_id=session_id, stored_ref=assistant_append["message_id"]),
                        "content": content,
                        "task_run_id": task.task_run_id,
                        "status": status,
                        "finish_reason": "stop",
                        "history_version": assistant_append["completion_result_version"],
                    },
                )
            )
            return
        session_store.clear_stale_running_task(
            owner_key=str(getattr(task, "owner_key", "") or session.get("user_id") or ""),
            session_id=session_id,
            task_run_id=task.task_run_id,
        )
        await context.send_json(
            _event_frame(
                "session.message.failed",
                {
                    "session_id": session_id,
                    "message_id": f"failed:{task.task_run_id}",
                    "task_run_id": task.task_run_id,
                    "status": status,
                    "error": {
                        "code": "task_not_completed",
                        "message": _assistant_content_from_task(task),
                        "retryable": status in {TaskStatus.FAILED.value, TaskStatus.CANCELED.value},
                    },
                },
            )
        )

    async def _send_result(self, context: WebSocketCommandContext, response_type: str, request_id: Any, payload: dict[str, Any]) -> None:
        await context.send_json(
            {
                "protocolVersion": 1,
                "type": response_type,
                "requestId": request_id,
                "serverTime": utc_now().isoformat(),
                "payload": _jsonable(payload),
            }
        )

    async def _send_error(
        self,
        context: WebSocketCommandContext,
        request_id: Any,
        code: str,
        message: str,
        *,
        retryable: bool = False,
    ) -> None:
        await context.send_json(
            {
                "protocolVersion": 1,
                "type": "command.error",
                "requestId": request_id,
                "serverTime": utc_now().isoformat(),
                "error": {
                    "code": code,
                    "message": message,
                    "retryable": retryable,
                },
            }
        )


def _event_frame(frame_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocolVersion": 1,
        "type": frame_type,
        "serverTime": utc_now().isoformat(),
        "payload": _jsonable(payload),
    }


def _task_snapshot_payload(task: Any) -> dict[str, Any]:
    task_payload = _jsonable(task)
    task_payload["displayContext"] = build_task_display_context(task)
    return {
        "task": task_payload,
        "task_run": task_payload,
        "events": [],
    }


def _create_public_session(context: WebSocketCommandContext, *, content: str, model: str | None, settings: dict[str, Any] | None = None) -> dict[str, Any]:
    session_id = new_id("session")
    metadata = {"source": _PUBLIC_SESSION_SOURCE}
    if context.auth.workspace_key:
        metadata["workspace_key"] = context.auth.workspace_key
    context.websocket.app.state.session_store.create_session(
        session_id=session_id,
        session_key=session_id,
        source=_PUBLIC_SESSION_SOURCE,
        user_id=context.auth.user_id,
        model=model,
        title=_derive_session_title(content),
        metadata=metadata,
        settings=settings or {},
    )
    session = context.websocket.app.state.session_store.get_session(session_id)
    if session is None:
        raise WebSocketCommandError("internal_error", "session was not created", retryable=True)
    return session


def _work_id_from_task_input(task_input: dict[str, Any]) -> str | None:
    candidate = task_input.get("workId") or task_input.get("work_id")
    text = str(candidate or "").strip()
    return text or None


def _attach_work_context_or_ws_error(
    context: WebSocketCommandContext,
    *,
    task_input: dict[str, Any],
    work_id: str,
    session_id: str,
    owner_key: str,
) -> Any:
    repository = getattr(context.websocket.app.state, "work_repository", None)
    if repository is None:
        raise WebSocketCommandError("work_repository_missing", "work repository is not configured")
    work = repository.get_work(work_id)
    if work is None:
        raise WebSocketCommandError("work_not_found", "work not found")
    if str(work.owner_key) != str(owner_key):
        raise WebSocketCommandError("forbidden", "work owner mismatch")
    if work.session_id != session_id:
        raise WebSocketCommandError("work_session_mismatch", "work belongs to another session")
    task_input["workId"] = work.work_id
    task_input["workIdentifier"] = work.identifier
    task_input["workAssigneeAgentId"] = work.assignee_agent_id
    task_input["workContext"] = repository.context_preview(work.work_id)
    _attach_target_agent_context(context.websocket.app.state, task_input=task_input, work=work)
    _apply_work_execution_defaults(task_input, settings=context.websocket.app.state.settings)
    return work


def _attach_target_agent_context(state: Any, *, task_input: dict[str, Any], work: Any) -> None:
    assignee_agent_id = str(work.assignee_agent_id or "").strip()
    agent_repository = getattr(state, "agent_repository", None)
    if agent_repository is None:
        return
    if not assignee_agent_id or assignee_agent_id == "CEO":
        profile = agent_repository.ensure_session_main_agent(
            session_id=work.session_id,
            owner_key=str(work.owner_key),
            owner_user_id=None,
        )
    else:
        profile = agent_repository.get_session_agent(profile_id=assignee_agent_id, owner_key=str(work.owner_key))
    if profile is None:
        return
    task_input["targetAgentProfile"] = _agent_profile_prompt_payload(
        profile,
        skill_registry=getattr(state, "skill_registry", None),
    )
    profile_id = str(profile.get("profile_id") or assignee_agent_id)
    _attach_effective_skill_names(
        state,
        task_input=task_input,
        owner_key=str(work.owner_key),
        profile=profile,
        profile_id=profile_id,
    )
    if not assignee_agent_id or assignee_agent_id == "CEO":
        _attach_session_agent_candidates(state, task_input=task_input, session_id=work.session_id, owner_key=str(work.owner_key))
    profile_model = _profile_model(profile)
    if profile_model:
        task_input["model"] = profile_model
    profile_provider = _profile_provider_name(profile)
    if profile_provider:
        task_input["provider_name"] = profile_provider
    bundle = agent_repository.get_instruction_bundle(profile_id=profile_id, owner_key=str(work.owner_key))
    if bundle is None:
        return
    task_input["targetAgentInstructions"] = _instruction_bundle_prompt_payload(bundle)


def _attach_main_agent_context(
    state: Any,
    *,
    task_input: dict[str, Any],
    session_id: str,
    owner_key: str,
) -> dict[str, Any] | None:
    agent_repository = getattr(state, "agent_repository", None)
    if agent_repository is None:
        return None
    profile = agent_repository.ensure_session_main_agent(
        session_id=session_id,
        owner_key=str(owner_key),
        owner_user_id=_owner_user_id(owner_key),
    )
    if profile is None:
        return None
    task_input["targetAgentProfile"] = _agent_profile_prompt_payload(
        profile,
        skill_registry=getattr(state, "skill_registry", None),
    )
    profile_id = str(profile.get("profile_id") or "").strip()
    _attach_effective_skill_names(
        state,
        task_input=task_input,
        owner_key=str(owner_key),
        profile=profile,
        profile_id=profile_id or None,
    )
    if profile_id:
        bundle = agent_repository.get_instruction_bundle(profile_id=profile_id, owner_key=str(owner_key))
        if bundle is not None:
            task_input["targetAgentInstructions"] = _instruction_bundle_prompt_payload(bundle)
    return profile


def _apply_work_execution_defaults(task_input: dict[str, Any], *, settings: Any) -> None:
    if task_input.get("max_iterations") not in (None, ""):
        return
    raw_value = getattr(settings, "work_execution_max_iterations", 24)
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = 24
    raw_upper = getattr(settings, "agent_loop_max_iterations", 120)
    try:
        upper_bound = int(raw_upper)
    except (TypeError, ValueError):
        upper_bound = 120
    task_input["max_iterations"] = max(1, min(value, max(1, upper_bound)))


def _apply_ws_linked_work_result(context: WebSocketBackgroundContext, *, task: Any) -> None:
    WorkService(context.websocket.app.state.work_repository).apply_linked_task_result(task=task)


def _mark_ws_linked_work_run_failed(context: WebSocketBackgroundContext, *, task: Any) -> None:
    work_id = _work_id_from_task_input(dict(getattr(task, "input_payload", {}) or {}))
    if work_id is None:
        return
    try:
        context.websocket.app.state.work_repository.update_run_status(work_id, task.task_run_id, "FAILED")
    except Exception:
        logger.exception("작업 실행 연결 상태 갱신에 실패했습니다.")


def _create_task_transcript_session(session_store: Any, *, session_id: str, owner_key: str, title: str | None, model: str | None) -> str:
    transcript_session_id = new_id("agent_session")
    session_store.create_session(
        session_id=transcript_session_id,
        session_key=session_id,
        source=_TASK_TRANSCRIPT_SOURCE,
        user_id=owner_key,
        model=model,
        parent_session_id=session_id,
        title=title,
        metadata={"source": _TASK_TRANSCRIPT_SOURCE, "public_session_id": session_id},
    )
    return transcript_session_id


def _get_public_session(context: WebSocketCommandContext, session_id: str, *, allow_deleted: bool = False) -> dict[str, Any]:
    session = context.websocket.app.state.session_store.get_session(session_id)
    if session is None or not _is_public_session(session, allow_deleted=allow_deleted):
        raise WebSocketCommandError("not_found", "session not found")
    return session


def _ensure_session_idle(session: dict[str, Any]) -> None:
    if session.get("running_task_run_id"):
        raise WebSocketCommandError("conflict", "session has a running task", retryable=True)


def _refresh_stale_running_guard(context: WebSocketCommandContext, session: dict[str, Any]) -> dict[str, Any]:
    task_run_id = session.get("running_task_run_id")
    if not task_run_id:
        return session
    task = context.websocket.app.state.repository.get_task(str(task_run_id))
    liveness = classify_task_run_liveness(task)
    if liveness.blocks_session:
        return session
    _recover_stale_task_if_needed(context.websocket.app.state.repository, task, liveness=liveness)
    # Postgres의 running_task_run_id는 재시작 뒤에도 남는 영속 guard다.
    # TaskRun이 이미 terminal이거나 projection/task row를 잃은 경우에는 다음 명령을 막지 않도록
    # 같은 task_run_id 소유 guard만 정리한다.
    context.websocket.app.state.session_store.clear_stale_running_task(
        owner_key=str(session.get("user_id") or context.auth.user_id),
        session_id=str(session["id"]),
        task_run_id=str(task_run_id),
    )
    refreshed = context.websocket.app.state.session_store.get_session(str(session["id"]))
    return refreshed or session


def _is_public_session(session: dict[str, Any], *, allow_deleted: bool = False) -> bool:
    metadata = dict(session.get("metadata") or {})
    if session.get("deleted_at") is not None and not allow_deleted:
        return False
    return session.get("source") == _PUBLIC_SESSION_SOURCE or metadata.get("source") == _PUBLIC_SESSION_SOURCE


def _prepare_retry_turn(session_store: Any, *, owner_key: str, session_id: str, target_message_id: str | None) -> dict[str, Any]:
    messages = session_store.list_messages(session_id)
    user_message = _select_retry_user_message(messages, target_message_id=target_message_id)
    if user_message is None:
        raise WebSocketCommandError("not_found", "retry target user message not found")
    user_sequence = int(user_message.get("id") or user_message.get("message_sequence") or 0)
    if user_sequence <= 0:
        raise WebSocketCommandError("invalid_state", "retry target message has no sequence")
    trimmed = _truncate_public_session_tail(
        session_store,
        owner_key=owner_key,
        session_id=session_id,
        keep_through_message_id=str(user_sequence),
        default_remove_last=False,
    )
    task_run_id = new_id("task")
    _start_existing_user_message_task(
        session_store,
        owner_key=owner_key,
        session_id=session_id,
        task_run_id=task_run_id,
        expected_history_version=trimmed["history_version"],
    )
    refreshed = session_store.list_messages(session_id)
    return {
        "task_run_id": task_run_id,
        "user_message_id": user_sequence,
        "content": str(user_message.get("content") or ""),
        "history_rows": [message for message in refreshed if int(message.get("id") or 0) < user_sequence],
        "base_history_version": trimmed["history_version"],
        "completion_expected_version": trimmed["history_version"],
    }


def _select_retry_user_message(messages: list[dict[str, Any]], *, target_message_id: str | None) -> dict[str, Any] | None:
    if target_message_id:
        for message in messages:
            if _message_matches_client_ref(message, target_message_id) and message.get("role") == "user":
                return message
        return None
    for message in reversed(messages):
        if message.get("role") == "user":
            return message
    return None


def _message_matches_client_ref(message: dict[str, Any], message_ref: str) -> bool:
    candidates = {
        str(message.get("id") or ""),
        str(message.get("message_id") or ""),
        str(message.get("messageId") or ""),
        str(message.get("message_sequence") or ""),
    }
    return message_ref in candidates


def _truncate_public_session_tail(
    session_store: Any,
    *,
    owner_key: str,
    session_id: str,
    keep_through_message_id: str | None,
    default_remove_last: bool,
) -> dict[str, Any]:
    if hasattr(session_store, "connection_factory"):
        return _truncate_postgres_public_session_tail(
            session_store,
            owner_key=owner_key,
            session_id=session_id,
            keep_through_message_id=keep_through_message_id,
            default_remove_last=default_remove_last,
        )
    return _truncate_memory_public_session_tail(
        session_store,
        owner_key=owner_key,
        session_id=session_id,
        keep_through_message_id=keep_through_message_id,
        default_remove_last=default_remove_last,
    )


def _truncate_memory_public_session_tail(
    session_store: Any,
    *,
    owner_key: str,
    session_id: str,
    keep_through_message_id: str | None,
    default_remove_last: bool,
) -> dict[str, Any]:
    session = session_store.get_session(session_id)
    if session is None:
        raise WebSocketCommandError("not_found", "session not found")
    if str(session.get("user_id") or session.get("owner_key") or "") != str(owner_key):
        raise WebSocketCommandError("forbidden", "forbidden")
    messages = session_store.messages.get(session_id, [])
    if keep_through_message_id is None and default_remove_last:
        keep_count = max(0, len(messages) - 1)
    else:
        keep_sequence = _resolve_memory_message_sequence(messages, keep_through_message_id)
        keep_count = len([message for message in messages if int(message.get("id") or 0) <= keep_sequence])
    session_store.messages[session_id] = messages[:keep_count]
    mutable_session = session_store.sessions[session_id]
    mutable_session["message_count"] = keep_count
    mutable_session["history_version"] = int(mutable_session.get("history_version") or 0) + 1
    mutable_session["running_task_run_id"] = None
    mutable_session["updated_at"] = utc_now()
    return {"history_version": mutable_session["history_version"]}


def _resolve_memory_message_sequence(messages: list[dict[str, Any]], message_ref: str | None) -> int:
    if not message_ref:
        return 0
    for message in messages:
        if _message_matches_client_ref(message, message_ref):
            return int(message.get("id") or message.get("message_sequence") or 0)
    try:
        return int(message_ref)
    except ValueError as error:
        raise WebSocketCommandError("not_found", "message not found") from error


def _truncate_postgres_public_session_tail(
    session_store: Any,
    *,
    owner_key: str,
    session_id: str,
    keep_through_message_id: str | None,
    default_remove_last: bool,
) -> dict[str, Any]:
    connection = session_store.connection_factory()
    owner_sql, owner_params = _owner_filter(owner_key)
    session_row = connection.execute(
        f"SELECT * FROM agent_sessions WHERE session_id = %s AND {owner_sql} FOR UPDATE",
        tuple([session_id, *owner_params]),
    ).fetchone()
    if session_row is None:
        raise WebSocketCommandError("not_found", "session not found")
    if session_row.get("running_task_run_id"):
        raise WebSocketCommandError("conflict", "session has a running task", retryable=True)
    if keep_through_message_id is None and default_remove_last:
        row = connection.execute(
            "SELECT COALESCE(MAX(message_sequence), 0) - 1 AS keep_sequence FROM agent_messages WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        keep_sequence = max(0, int((row or {}).get("keep_sequence") or 0))
    else:
        keep_sequence = _resolve_postgres_message_sequence(connection, session_id=session_id, message_ref=keep_through_message_id)
    connection.execute(
        "DELETE FROM agent_messages WHERE session_id = %s AND message_sequence > %s",
        (session_id, keep_sequence),
    )
    count_row = connection.execute(
        "SELECT COUNT(*) AS count FROM agent_messages WHERE session_id = %s",
        (session_id,),
    ).fetchone()
    next_version = int(session_row.get("history_version") or 0) + 1
    connection.execute(
        f"""
        UPDATE agent_sessions
        SET history_version = %s,
            running_task_run_id = NULL,
            updated_at = now(),
            metadata = jsonb_set(metadata, '{message_count}', to_jsonb(%s::int), true)
        WHERE session_id = %s AND {owner_sql}
        """,
        tuple([next_version, int((count_row or {}).get("count") or 0), session_id, *owner_params]),
    )
    connection.commit()
    return {"history_version": next_version}


def _resolve_postgres_message_sequence(connection: Any, *, session_id: str, message_ref: str | None) -> int:
    if not message_ref:
        return 0
    row = connection.execute(
        """
        SELECT message_sequence
        FROM agent_messages
        WHERE session_id = %s
          AND (message_id = %s OR message_sequence::text = %s)
        ORDER BY message_sequence ASC
        LIMIT 1
        """,
        (session_id, message_ref, message_ref),
    ).fetchone()
    if row is not None:
        return int(row.get("message_sequence") or 0)
    try:
        return int(message_ref)
    except ValueError as error:
        raise WebSocketCommandError("not_found", "message not found") from error


def _start_existing_user_message_task(
    session_store: Any,
    *,
    owner_key: str,
    session_id: str,
    task_run_id: str,
    expected_history_version: int,
) -> None:
    if hasattr(session_store, "connection_factory"):
        connection = session_store.connection_factory()
        owner_sql, owner_params = _owner_filter(owner_key)
        row = connection.execute(
            f"""
            UPDATE agent_sessions
            SET running_task_run_id = %s,
                updated_at = now()
            WHERE session_id = %s
              AND {owner_sql}
              AND history_version = %s
              AND running_task_run_id IS NULL
            RETURNING session_id
            """,
            tuple([task_run_id, session_id, *owner_params, expected_history_version]),
        ).fetchone()
        connection.commit()
        if row is None:
            raise WebSocketCommandError("conflict", "session history changed", retryable=True)
        return
    session = session_store.sessions.get(session_id)
    if session is None or str(session.get("user_id") or "") != str(owner_key):
        raise WebSocketCommandError("not_found", "session not found")
    if int(session.get("history_version") or 0) != expected_history_version or session.get("running_task_run_id"):
        raise WebSocketCommandError("conflict", "session history changed", retryable=True)
    session["running_task_run_id"] = task_run_id


def _update_public_session_title(session_store: Any, *, owner_key: str, session_id: str, title: str) -> None:
    if hasattr(session_store, "update_title"):
        session_store.update_title(owner_key=owner_key, session_id=session_id, title=title)
        return
    if hasattr(session_store, "connection_factory"):
        connection = session_store.connection_factory()
        owner_sql, owner_params = _owner_filter(owner_key)
        connection.execute(
            f"UPDATE agent_sessions SET title = %s, updated_at = now() WHERE session_id = %s AND {owner_sql} AND deleted_at IS NULL",
            tuple([title, session_id, *owner_params]),
        )
        connection.commit()
        return
    session = session_store.sessions.get(session_id)
    if session is not None and str(session.get("user_id") or "") == str(owner_key):
        session["title"] = title
        session["updated_at"] = utc_now()


def _patch_public_session_metadata(
    session_store: Any,
    *,
    owner_key: str,
    session_id: str,
    metadata_patch: dict[str, Any],
    bump_history_version: bool,
) -> dict[str, Any]:
    if hasattr(session_store, "connection_factory"):
        connection = session_store.connection_factory()
        owner_sql, owner_params = _owner_filter(owner_key)
        row = connection.execute(
            f"SELECT metadata, history_version FROM agent_sessions WHERE session_id = %s AND {owner_sql} FOR UPDATE",
            tuple([session_id, *owner_params]),
        ).fetchone()
        if row is None:
            raise WebSocketCommandError("not_found", "session not found")
        metadata = _json_load(row.get("metadata"), {})
        metadata.update(metadata_patch)
        next_version = int(row.get("history_version") or 0) + (1 if bump_history_version else 0)
        connection.execute(
            f"""
            UPDATE agent_sessions
            SET metadata = %s::jsonb,
                history_version = %s,
                updated_at = now()
            WHERE session_id = %s AND {owner_sql}
              AND deleted_at IS NULL
            """,
            tuple([_json_dumps(metadata), next_version, session_id, *owner_params]),
        )
        connection.commit()
        return {"history_version": next_version, "metadata": metadata}
    session = session_store.sessions.get(session_id)
    if session is None or str(session.get("user_id") or "") != str(owner_key):
        raise WebSocketCommandError("not_found", "session not found")
    metadata = dict(session.get("metadata") or {})
    metadata.update(metadata_patch)
    session["metadata"] = metadata
    if bump_history_version:
        session["history_version"] = int(session.get("history_version") or 0) + 1
    session["updated_at"] = utc_now()
    return {"history_version": int(session.get("history_version") or 0), "metadata": metadata}


def _validate_metadata_patch(metadata_patch: dict[str, Any]) -> None:
    protected = _PROTECTED_SESSION_METADATA_KEYS.intersection(metadata_patch)
    if protected:
        raise WebSocketCommandError("invalid_payload", "metadataPatch contains protected fields")
    unknown = set(metadata_patch) - _SESSION_METADATA_PATCH_ALLOWLIST
    if unknown:
        raise WebSocketCommandError("invalid_payload", "metadataPatch contains unsupported fields")


def _session_command_signature(operation: str, payload: dict[str, Any]) -> str:
    return json.dumps({"operation": operation, "payload": payload}, ensure_ascii=False, sort_keys=True, default=str)


def _normalize_session_settings(settings: dict[str, Any]) -> dict[str, Any]:
    unknown = set(settings) - _SESSION_SETTINGS_ALLOWLIST
    if unknown:
        raise WebSocketCommandError("invalid_payload", "settings contains unsupported fields")
    normalized: dict[str, Any] = {}
    model = settings.get("model")
    if model is not None:
        if not isinstance(model, str) or not model.strip():
            raise WebSocketCommandError("invalid_payload", "settings.model must be a non-empty string")
        normalized["model"] = model.strip()
    system_prompt = settings.get("systemPrompt", settings.get("system_prompt"))
    if system_prompt is not None:
        if not isinstance(system_prompt, str):
            raise WebSocketCommandError("invalid_payload", "settings.systemPrompt must be a string")
        normalized["systemPrompt"] = system_prompt
    toolsets = settings.get("toolsets")
    if toolsets is not None:
        if not isinstance(toolsets, list) or any(not isinstance(item, str) or not item.strip() for item in toolsets):
            raise WebSocketCommandError("invalid_payload", "settings.toolsets must be a string array")
        normalized_toolsets = [item.strip() for item in toolsets]
        if any(item not in _PUBLIC_SESSION_TOOLSETS for item in normalized_toolsets):
            raise WebSocketCommandError("invalid_payload", "settings.toolsets contains unsupported toolsets")
        normalized["toolsets"] = normalized_toolsets
    delegation_policy = settings.get("delegationPolicy", settings.get("delegation_policy"))
    if delegation_policy is not None:
        if not isinstance(delegation_policy, dict):
            raise WebSocketCommandError("invalid_payload", "settings.delegationPolicy must be an object")
        normalized["delegationPolicy"] = _normalize_delegation_policy(delegation_policy)
    return normalized


def _normalize_delegation_policy(policy: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {"canDelegate", "maxWorkerDepth"}
    if set(policy) - allowed_keys:
        raise WebSocketCommandError("invalid_payload", "settings.delegationPolicy contains unsupported fields")
    can_delegate = policy.get("canDelegate", False)
    if not isinstance(can_delegate, bool):
        raise WebSocketCommandError("invalid_payload", "settings.delegationPolicy.canDelegate must be a boolean")
    max_worker_depth = policy.get("maxWorkerDepth", 0)
    if not isinstance(max_worker_depth, int) or max_worker_depth < 0 or max_worker_depth > 1:
        raise WebSocketCommandError("invalid_payload", "settings.delegationPolicy.maxWorkerDepth must be 0 or 1")
    # 세션 설정은 실행 권한을 넓히지 않는다. 위임 도구 노출은 별도 승인된 runtime toolset에서만 결정한다.
    return {"canDelegate": can_delegate, "maxWorkerDepth": max_worker_depth}


def _session_settings_snapshot(session: dict[str, Any]) -> dict[str, Any]:
    settings = session.get("settings")
    if not isinstance(settings, dict):
        return {}
    return dict(settings)


def _apply_session_settings_snapshot(task_input: dict[str, Any], settings: dict[str, Any], *, session: dict[str, Any]) -> None:
    """세션 설정을 TaskRun 입력에 복사해 이후 재시작/재생 시 같은 실행 기준을 유지한다."""

    snapshot = dict(settings)
    task_input["settings_snapshot"] = snapshot
    if "model" in snapshot and not task_input.get("model"):
        task_input["model"] = snapshot["model"]
    if "toolsets" in snapshot:
        task_input["toolsets"] = list(snapshot["toolsets"])
        task_input["enabled_toolsets"] = list(snapshot["toolsets"])
    if "delegationPolicy" in snapshot:
        task_input["delegation_policy"] = dict(snapshot["delegationPolicy"])
    task_input["system_prompt_snapshot"] = get_system_prompt_snapshot(session)


def _default_agent_loop_toolsets(state: Any) -> tuple[str, ...]:
    tool_catalog = getattr(state, "tool_catalog", None)
    default_toolsets = getattr(tool_catalog, "default_toolsets", None)
    if isinstance(default_toolsets, tuple):
        return default_toolsets
    if isinstance(default_toolsets, list):
        return tuple(str(item) for item in default_toolsets if str(item).strip())
    # 세션 설정 allowlist는 사용자가 저장할 수 있는 안전한 설정 범위이고,
    # 기본 실행 권한은 실제 agent.loop 런타임 조립값을 우선 신뢰한다.
    return tuple(sorted(_PUBLIC_SESSION_TOOLSETS))


async def _list_openai_models_for_user(state: Any, *, user_id: str, fallback_model: str) -> list[str]:
    models: list[str] = []
    registry = getattr(state, "provider_registry", None)
    provider = None
    if registry is not None and hasattr(registry, "get"):
        try:
            provider = registry.get("openai_api")
        except KeyError:
            provider = None
    if provider is not None and hasattr(provider, "list_user_models"):
        try:
            models = await provider.list_user_models(user_id=user_id, model=fallback_model)
        except Exception:
            models = []

    preferred = [fallback_model, *_OPENAI_MODEL_FALLBACKS]
    configured = getattr(getattr(state, "settings", None), "openai_allowed_models", None)
    if isinstance(configured, str):
        preferred.extend([item.strip() for item in configured.split(",") if item.strip()])
    elif isinstance(configured, (list, tuple, set)):
        preferred.extend([str(item).strip() for item in configured if str(item).strip()])

    merged: list[str] = []
    seen: set[str] = set()
    for model in [*preferred, *models]:
        model_id = str(model or "").strip()
        if not model_id or model_id in seen:
            continue
        seen.add(model_id)
        merged.append(model_id)
    return merged or [fallback_model]


def _json_dumps(value: Any) -> str:
    import json

    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _json_load(value: Any, default: Any) -> Any:
    import json

    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _owner_filter(owner_key: str) -> tuple[str, list[Any]]:
    owner_user_id = _owner_user_id(owner_key)
    if owner_user_id is None:
        return "owner_key = %s", [owner_key]
    return "owner_user_id = %s", [owner_user_id]


def _owner_user_id(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _public_session_payload(session: dict[str, Any], *, context: WebSocketCommandContext | None = None) -> dict[str, Any]:
    payload = {
        "session_id": str(session["id"]),
        "session_key": session.get("session_key"),
        "title": session.get("title"),
        "owner_key": session.get("user_id"),
        "owner_user_id": session.get("owner_user_id"),
        "status": session.get("status"),
        "source": session.get("source"),
        "parent_session_id": session.get("parent_session_id"),
        "message_count": int(session.get("message_count") or 0),
        "history_version": int(session.get("history_version") or 0),
        "metadata": dict(session.get("metadata") or {}),
        "settings": dict(session.get("settings") or {}),
        "created_at": session.get("created_at") or session.get("started_at"),
        "updated_at": session.get("updated_at"),
        "ended_at": session.get("ended_at"),
        "archived_at": session.get("archived_at"),
        "deleted_at": session.get("deleted_at"),
        "purge_after": session.get("purge_after"),
    }
    if context is not None:
        payload.update(_session_list_preview_payload(context, session_id=str(session["id"])))
    return payload


def _session_list_preview_payload(context: WebSocketCommandContext, *, session_id: str) -> dict[str, Any]:
    """세션 목록만으로 사이드바를 복구할 수 있게 최근 메시지와 TaskRun 상태를 붙인다.

    상세 화면은 별도 messages/snapshot query를 다시 호출하지만, 목록은 이 값만으로
    mock preview나 임의 spinner 없이 실제 DB 상태를 표시한다.
    """

    result: dict[str, Any] = {
        "last_message": None,
        "last_message_at": None,
        "active_task_run_id": None,
        "last_task_run_status": None,
    }

    messages = context.websocket.app.state.session_store.list_messages(session_id)
    if messages:
        last_message = messages[-1]
        result["last_message"] = last_message.get("content")
        result["last_message_at"] = last_message.get("timestamp")

    tasks = context.websocket.app.state.repository.list_tasks(session_key=session_id, limit=50, offset=0)
    tasks = [task for task in tasks if not _is_expired_running_task(task)]
    if not tasks:
        return result

    active_task = next((task for task in tasks if _is_sidebar_active_task(task)), None)
    latest_task = active_task or tasks[0]
    result["last_task_run_status"] = latest_task.status
    if active_task is not None:
        result["active_task_run_id"] = active_task.task_run_id
    return result


def _is_sidebar_active_task(task: Any) -> bool:
    return classify_task_run_liveness(task).blocks_session


def _is_live_active_task(repository: Any, task: Any) -> bool:
    liveness = classify_task_run_liveness(task)
    if liveness.reason == "direct_run_without_supervisor_claim" and _is_active_direct_run_stale(task):
        return False
    if liveness.blocks_session:
        return True
    _recover_stale_task_if_needed(repository, task, liveness=liveness)
    return False


def _is_active_direct_run_stale(task: Any) -> bool:
    updated_at = getattr(task, "updated_at", None)
    if not isinstance(updated_at, datetime):
        return False
    return (utc_now() - updated_at).total_seconds() > _ACTIVE_DIRECT_RUN_TTL_SECONDS


def _recover_stale_task_if_needed(repository: Any, task: Any, *, liveness: Any | None = None) -> None:
    if task is None:
        return
    current_liveness = liveness or classify_task_run_liveness(task)
    if not current_liveness.should_recover:
        return
    recover = getattr(repository, "recover_stale_task_run", None)
    if recover is None:
        return
    recover(str(task.task_run_id), reason=str(current_liveness.reason))


def _is_expired_running_task(task: Any) -> bool:
    liveness = classify_task_run_liveness(task)
    return liveness.should_recover and not liveness.blocks_session


def _message_payload(message: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(message.get("metadata") or {})
    sequence = int(message["id"])
    durable_message_id = message.get("message_id") or message.get("messageId") or sequence
    return {
        "id": sequence,
        "message_id": str(durable_message_id),
        "message_sequence": sequence,
        "session_id": str(message["session_id"]),
        "role": str(message["role"]),
        "content": message.get("content"),
        "task_run_id": metadata.get("task_run_id") or metadata.get("taskRunId"),
        "client_message_id": metadata.get("client_message_id") or metadata.get("clientMessageId"),
        "metadata": metadata,
        "timestamp": message.get("timestamp"),
        "created_at": message.get("timestamp"),
        "finish_reason": message.get("finish_reason"),
    }


def _stored_message_id(session_store: Any, *, session_id: str, stored_ref: Any) -> str:
    """append_message 반환값을 WebSocket용 durable message_id로 정규화한다.

    Postgres 저장소는 HTTP 증분 조회 호환성을 위해 append_message에서 세션 내 sequence를
    돌려줄 수 있다. WebSocket 채팅 store의 최종 key는 DB message_id가 기준이므로,
    저장 직후 row를 다시 읽어 실제 message_id가 있으면 그 값을 우선 사용한다.
    """

    stored_ref_text = str(stored_ref)
    for message in session_store.list_messages(session_id):
        message_payload = _message_payload(message)
        if str(message_payload["id"]) == stored_ref_text or str(message_payload["message_id"]) == stored_ref_text:
            return str(message_payload["message_id"])
    return stored_ref_text


def _find_accepted_message_by_client_id(
    context: WebSocketCommandContext,
    *,
    session_id: str | None,
    client_message_id: str,
) -> dict[str, Any] | None:
    """durable 저장소에서 clientMessageId 재전송 여부를 찾는다."""

    session_store = context.websocket.app.state.session_store
    candidate_sessions = [session_store.get_session(session_id)] if session_id else session_store.list_sessions(user_id=context.auth.user_id, limit=10_000, offset=0)
    for session in candidate_sessions:
        if session is None or not _is_public_session(session):
            continue
        if str(session.get("user_id") or "") != str(context.auth.user_id):
            continue
        public_session_id = str(session["id"])
        for message in session_store.list_messages(public_session_id):
            metadata = dict(message.get("metadata") or {})
            if metadata.get("client_message_id") != client_message_id and metadata.get("clientMessageId") != client_message_id:
                continue
            task_run_id = metadata.get("task_run_id") or metadata.get("taskRunId")
            if not task_run_id:
                continue
            return {
                "session_id": public_session_id,
                "user_message_id": str(_message_payload(message)["message_id"]),
                "assistant_message_id": _find_assistant_message_id_for_task(session_store, public_session_id, str(task_run_id)),
                "task_run_id": str(task_run_id),
                "status": _task_status_for_payload(context, str(task_run_id)),
                "client_message_id": client_message_id,
            }
    return None


def _find_assistant_message_id_for_task(session_store: Any, session_id: str, task_run_id: str) -> str | None:
    for message in session_store.list_messages(session_id):
        if str(message.get("role") or "") != "assistant":
            continue
        metadata = dict(message.get("metadata") or {})
        if str(metadata.get("task_run_id") or metadata.get("taskRunId") or "") == task_run_id:
            return str(_message_payload(message)["message_id"])
    return None


def _task_status_for_payload(context: WebSocketCommandContext, task_run_id: str) -> str | None:
    task = context.websocket.app.state.repository.get_task(task_run_id)
    return str(task.status) if task is not None else None


def _active_task_payload(task: Any, steps: list[Any], *, source: str, repository: Any) -> dict[str, Any]:
    current_step = _select_current_step(task, steps)
    current_step_payload = _step_payload_with_display_context(task, current_step) if current_step is not None else None
    return {
        "task_run_id": task.task_run_id,
        "source": source,
        "session_key": task.session_key,
        "status": task.status,
        "title": task.title,
        "current_step_run_id": task.current_step_run_id,
        "current_step": current_step_payload,
        "updated_at": task.updated_at,
        "wait_reason": (task.wait_payload or {}).get("reason"),
        "pending_approval": _pending_approval_payload(repository.get_open_approval(task.task_run_id)),
        "displayContext": build_task_display_context(task),
    }


def _seed_default_session_agents_if_requested(
    state: Any,
    *,
    task_input: dict[str, Any],
    session_id: str,
    owner_key: str,
) -> None:
    snapshot = task_input.get("sessionConfigSnapshot") or task_input.get("session_config_snapshot")
    if not isinstance(snapshot, dict) or snapshot.get("seedDefaultAgents") is not True:
        return
    agent_repository = getattr(state, "agent_repository", None)
    if agent_repository is None:
        return
    agent_repository.create_default_session_agents(
        session_id=session_id,
        owner_key=str(owner_key),
        owner_user_id=_owner_user_id(owner_key),
    )


def _attach_session_agent_candidates(
    state: Any,
    *,
    task_input: dict[str, Any],
    session_id: str,
    owner_key: str,
) -> list[dict[str, Any]]:
    agent_repository = getattr(state, "agent_repository", None)
    if agent_repository is None:
        return []
    profiles = [
        _agent_profile_prompt_payload(
            item,
            skill_registry=getattr(state, "skill_registry", None),
        )
        for item in agent_repository.list_session_agents(session_id=session_id, owner_key=str(owner_key))
    ]
    if profiles:
        task_input["sessionAgentProfiles"] = profiles
    return profiles


def _attach_effective_skill_names(
    state: Any,
    *,
    task_input: dict[str, Any],
    owner_key: str,
    profile: dict[str, Any],
    profile_id: str | None,
) -> None:
    skill_repository = getattr(state, "skill_repository", None)
    if skill_repository is None:
        return
    config = profile.get("config_snapshot") if isinstance(profile.get("config_snapshot"), dict) else {}
    task_input["enabledSkillNames"] = skill_repository.effective_skill_names(
        owner_key=str(owner_key),
        profile_id=profile_id,
        requested_skill_names=[str(skill) for skill in list(config.get("skills") or [])],
        explicit_agent_selection=config.get("skillSelectionMode") == "explicit",
    )


def _step_payload_with_display_context(task: Any, step: Any) -> dict[str, Any]:
    payload = _jsonable(step)
    payload["displayContext"] = build_task_display_context(task, step)
    return payload


def _projection_steps(projection: Any, task_run_id: str) -> list[Any]:
    steps = []
    for step_run_id in projection.list_task_steps(task_run_id):
        step = projection.get_step_snapshot(step_run_id)
        if step is not None:
            steps.append(step)
    return steps


def _task_events_payload(
    *,
    repository: Any,
    projection: Any,
    task_run_id: str,
    limit: int = 200,
) -> list[dict[str, Any]]:
    if projection is not None:
        events = projection.list_recent_events(task_run_id)
        if events:
            return [_jsonable(event) for event in events[:limit]]
    return [_jsonable(event) for event in repository.list_events(task_run_id)[:limit]]


def _select_current_step(task: Any, steps: list[Any]) -> Any | None:
    if task.current_step_run_id:
        for step in steps:
            if step.step_run_id == task.current_step_run_id:
                return step
    active_statuses = {"PENDING", "RUNNING", "WAITING", "BLOCKED"}
    for step in steps:
        if step.status in active_statuses:
            return step
    return steps[-1] if steps else None


def _pending_approval_payload(approval: dict[str, Any] | None) -> dict[str, Any] | None:
    if approval is None:
        return None
    request_payload = dict(approval.get("request_payload") or {})
    return {
        "approval_id": approval.get("approval_id"),
        "task_run_id": approval.get("task_run_id"),
        "step_run_id": approval.get("step_run_id"),
        "status": approval.get("status"),
        "reason": request_payload.get("reason") or request_payload.get("approvalReason"),
        "tool_call_id": request_payload.get("pending_tool_call_id") or request_payload.get("tool_call_id"),
        "tool_name": request_payload.get("pending_tool_name") or request_payload.get("tool_name"),
        "payload": request_payload,
        "request_payload": request_payload,
        "requested_at": approval.get("created_at") or approval.get("requested_at"),
        "created_at": approval.get("created_at") or approval.get("requested_at"),
        "can_approve": bool(approval.get("can_approve", approval.get("status") == "PENDING")),
        "can_reject": bool(approval.get("can_reject", approval.get("status") == "PENDING")),
    }


def _normalize_resume_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """프론트 승인 command shape를 agent.loop resume shape로 맞춘다.

    UI는 디버깅을 위해 decision/response를 함께 보내지만, 실제 tool resume 로직은
    top-level approved/reason/message 값을 읽는다. 서버 경계에서 한 번만 펴서 저장/실행한다.
    """

    normalized = dict(payload)
    response = normalized.get("response")
    if isinstance(response, dict):
        normalized.update(response)

    decision = str(normalized.get("decision") or "").strip().upper()
    if "approved" not in normalized and decision:
        normalized["approved"] = decision in {"APPROVED", "APPROVE", "ACCEPTED", "YES"}
    if normalized.get("approved") is False and not normalized.get("reason"):
        normalized["reason"] = normalized.get("message") or "사용자가 도구 실행을 거절했습니다"
    return normalized


def _ensure_owner(context: WebSocketCommandContext, owner_key: Any) -> None:
    if str(owner_key or "") != str(context.auth.user_id):
        raise WebSocketCommandError("forbidden", "forbidden")


def _assistant_content_from_task(task: Any) -> str:
    result_payload = dict(getattr(task, "result_payload", {}) or {})
    for key in ("text", "output_text", "summary", "message", "content"):
        value = result_payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    if getattr(task, "progress_summary", None):
        return str(task.progress_summary)
    if getattr(task, "error_message", None):
        return str(task.error_message)
    if getattr(task, "status", None) == "WAITING":
        return "추가 확인이 필요합니다."
    return "요청 처리가 완료되었습니다."


def _derive_session_title(content: str) -> str:
    title = " ".join(content.split())
    return title[:60] or "새 AI 대화"


def _required_str(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    label = keys[0]
    raise WebSocketCommandError("invalid_payload", f"{label} is required")


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    raise WebSocketCommandError("invalid_payload", "expected string")


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        raise WebSocketCommandError("invalid_payload", "expected integer")
    try:
        result = int(value)
    except (TypeError, ValueError) as error:
        raise WebSocketCommandError("invalid_payload", "expected integer") from error
    if result < 0:
        raise WebSocketCommandError("invalid_payload", "expected non-negative integer")
    return result


def _positive_int(value: Any, *, default: int, maximum: int) -> int:
    result = default if value is None else _optional_int(value)
    if result is None or result < 1:
        raise WebSocketCommandError("invalid_payload", "expected positive integer")
    return min(result, maximum)


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=False)
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value
