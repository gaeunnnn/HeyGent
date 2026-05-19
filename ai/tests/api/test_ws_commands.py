from __future__ import annotations

from datetime import timedelta

from app.clients.backend_auth import BackendAuthVerifyResult
from app.clients.backend_memory import BackendMemoryItem
from app.contracts.event.task_events import TaskEventEnvelope
from app.core.time import utc_now
from app.domain.providers.model.base import AgentMessage, AgentModelResponse, AssistantToolCall
from app.domain.tasks.models import TaskRun
from tests.domain.test_work_service import FakeWorkRepository


class RealtimeFakeWorkRepository(FakeWorkRepository):
    def context_preview(self, work_id: str) -> dict:
        work = self.get_work(work_id)
        if work is None:
            return {}
        return {
            "workId": work.work_id,
            "identifier": work.identifier,
            "title": work.title,
            "status": work.status,
            "assigneeAgentId": work.assignee_agent_id,
            "latestRunId": work.latest_run_id,
        }

    def release_stale_active_work_runs(self, *, stale_after_seconds: int, limit: int = 50) -> list:
        return []

    def close(self) -> None:
        return None


class FakeBackendAuthClient:
    def __init__(self, *, user_id: str = "ws-user") -> None:
        self.user_id = user_id

    async def verify_access_token(self, access_token: str, *, workspace_key: str | None = None) -> BackendAuthVerifyResult:
        return BackendAuthVerifyResult(user_id=self.user_id, workspace_key=workspace_key)


def _patch_respond(monkeypatch, text: str = "WS_COMMAND_DONE") -> None:
    def fake_respond(self, messages, tools, model, tool_choice=None, runtime_context=None):
        return AgentModelResponse(
            provider_name="openai_api",
            model=model,
            message=AgentMessage(role="assistant", content=text, tool_calls=[]),
            output_text=text,
            tool_calls=[],
            finish_reason="stop",
            metadata={"model": model},
        )

    async def fake_respond_async(self, messages, tools, model, tool_choice=None, runtime_context=None):
        return fake_respond(
            self,
            messages=messages,
            tools=tools,
            model=model,
            tool_choice=tool_choice,
            runtime_context=runtime_context,
        )

    monkeypatch.setattr("app.domain.providers.model.openai_api.OpenAIAPIProvider.respond", fake_respond)
    monkeypatch.setattr("app.domain.providers.model.openai_api.OpenAIAPIProvider.respond_async", fake_respond_async)


def _patch_respond_sequence(monkeypatch, responses: list[AgentModelResponse]) -> None:
    remaining = list(responses)

    def fake_respond(self, messages, tools, model, tool_choice=None, runtime_context=None):
        if not remaining:
            return _model_text_response(model=model, text="SEQUENCE_EXHAUSTED")
        return remaining.pop(0)

    async def fake_respond_async(self, messages, tools, model, tool_choice=None, runtime_context=None):
        return fake_respond(
            self,
            messages=messages,
            tools=tools,
            model=model,
            tool_choice=tool_choice,
            runtime_context=runtime_context,
        )

    monkeypatch.setattr("app.domain.providers.model.openai_api.OpenAIAPIProvider.respond", fake_respond)
    monkeypatch.setattr("app.domain.providers.model.openai_api.OpenAIAPIProvider.respond_async", fake_respond_async)


def _model_text_response(*, model: str, text: str, work_disposition: dict | None = None) -> AgentModelResponse:
    return AgentModelResponse(
        provider_name="openai_api",
        model=model,
        message=AgentMessage(role="assistant", content=text, tool_calls=[]),
        output_text=text,
        tool_calls=[],
        finish_reason="stop",
        metadata={"model": model},
        work_disposition=work_disposition,
        visible_text=text,
    )


def _model_tool_response(*, model: str, tool_calls: list[AssistantToolCall]) -> AgentModelResponse:
    return AgentModelResponse(
        provider_name="openai_api",
        model=model,
        message=AgentMessage(role="assistant", content="", tool_calls=tool_calls),
        output_text="",
        tool_calls=tool_calls,
        finish_reason="tool_calls",
        metadata={"model": model},
    )


def _tool_call(call_id: str, name: str, arguments: dict) -> AssistantToolCall:
    return AssistantToolCall(id=call_id, name=name, arguments=arguments)


def _patch_respond_failure(monkeypatch) -> None:
    async def fake_execute_initial(self, *, task, handler, resume_payload):
        raise RuntimeError("테스트용 background 실패")

    monkeypatch.setattr("app.domain.orchestration.agent.loop.TaskEngine._execute_initial", fake_execute_initial)


def _authenticated_socket(client, *, user_id: str = "ws-user"):
    client.app.state.backend_auth_client = FakeBackendAuthClient(user_id=user_id)
    websocket_context = client.websocket_connect("/ai/api/v1/realtime/user/ws")
    websocket = websocket_context.__enter__()
    websocket.send_json({"type": "auth.start", "accessToken": "token-secret"})
    assert websocket.receive_json()["type"] == "auth.ok"
    return websocket_context, websocket


def _receive_until(
    websocket,
    frame_type: str,
    *,
    max_frames: int = 20,
    seen_types: list[str] | None = None,
    seen_frames: list[dict] | None = None,
):
    for _ in range(max_frames):
        frame = websocket.receive_json()
        if seen_frames is not None:
            seen_frames.append(frame)
        if seen_types is not None:
            seen_types.append(frame.get("type"))
        if frame.get("type") == frame_type:
            return frame
    raise AssertionError(f"{frame_type} frame was not received")


def _receive_command_frame(
    websocket,
    frame_type: str,
    request_id: str,
    *,
    max_frames: int = 40,
    seen_frames: list[dict] | None = None,
) -> dict:
    seen: list[tuple[str | None, str | None]] = []
    for _ in range(max_frames):
        frame = websocket.receive_json()
        if seen_frames is not None:
            seen_frames.append(frame)
        seen.append((frame.get("type"), frame.get("requestId")))
        if frame.get("type") == frame_type and frame.get("requestId") == request_id:
            return frame
    raise AssertionError(f"{frame_type} frame for {request_id} was not received; seen={seen}")


def test_ws_unknown_command_returns_command_error_with_request_id(client):
    context, websocket = _authenticated_socket(client)
    try:
        websocket.send_json({"protocolVersion": 1, "type": "unknown.command", "requestId": "req_error", "payload": {}})

        response = websocket.receive_json()

        assert response["type"] == "command.error"
        assert response["requestId"] == "req_error"
        assert response["error"]["code"] == "unknown_command"
    finally:
        context.__exit__(None, None, None)


def test_ws_session_message_create_returns_accepted_before_completed_and_stores_result(client, monkeypatch):
    _patch_respond(monkeypatch, text="WS_ACCEPTED_DONE")
    context, websocket = _authenticated_socket(client, user_id="ws-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_create",
                "payload": {
                    "content": "WebSocket command 테스트",
                    "clientMessageId": "client_msg_ws_1",
                    "model": "gpt-test",
                },
            }
        )

        accepted = websocket.receive_json()
        assert accepted["type"] == "session.message.accepted"
        assert accepted["requestId"] == "req_create"
        assert accepted["payload"]["session_id"].startswith("session_")
        assert isinstance(accepted["payload"]["user_message_id"], str)
        assert accepted["payload"]["task_run_id"].startswith("task_")
        assert accepted["payload"]["assistant_message_id"] is None

        seen_types: list[str] = []
        completed = _receive_until(websocket, "session.message.completed", seen_types=seen_types)
        assert "session.message.delta" not in seen_types
        assert isinstance(completed["payload"]["message_id"], str)
        assert completed["payload"]["content"] == "WS_ACCEPTED_DONE"
        assert completed["payload"]["task_run_id"] == accepted["payload"]["task_run_id"]

        task = client.app.state.repository.get_task(accepted["payload"]["task_run_id"])
        assert task is not None
        assert "token-secret" not in str(task.input_payload)
        messages = client.app.state.session_store.list_messages(accepted["payload"]["session_id"])
        assert [message["role"] for message in messages] == ["user", "assistant"]
    finally:
        context.__exit__(None, None, None)


def test_ws_session_message_create_attaches_backend_memory_context(client, monkeypatch):
    client.app.state.backend_memory_client.memories = [
        BackendMemoryItem(
            id=21,
            memory_type="PREFERENCE",
            store_type="PROFILE",
            scope_type="GLOBAL",
            content="사용자는 코드 변경 내역을 기능 단위로 분리해 보길 원한다.",
        )
    ]
    _patch_respond(monkeypatch, text="WS_MEMORY_DONE")
    context, websocket = _authenticated_socket(client, user_id="77")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_memory",
                "payload": {
                    "content": "이번 작업 커밋 분리해줘",
                    "clientMessageId": "client_msg_memory_1",
                    "model": "gpt-test",
                    "inputPayload": {"persistent_memory_context": "client supplied context"},
                },
            }
        )

        accepted = websocket.receive_json()
        assert accepted["type"] == "session.message.accepted"
        completed = _receive_until(websocket, "session.message.completed")
        assert completed["payload"]["content"] == "WS_MEMORY_DONE"

        task = client.app.state.repository.get_task(accepted["payload"]["task_run_id"])
        assert task is not None
        assert "사용자는 코드 변경 내역을 기능 단위로 분리해 보길 원한다." in task.input_payload["persistent_memory_context"]
        assert "client supplied context" not in str(task.input_payload)
        assert client.app.state.backend_memory_client.calls[-1]["user_id"] == "77"
    finally:
        context.__exit__(None, None, None)


def test_ws_session_message_create_resends_snapshot_after_memory_observation(client, monkeypatch):
    _patch_respond(monkeypatch, text="WS_MEMORY_OBSERVATION_DONE")
    context, websocket = _authenticated_socket(client, user_id="ws-memory-observation-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_memory_observation",
                "payload": {
                    "content": "나 국수 좋아해",
                    "clientMessageId": "client_msg_memory_observation_1",
                    "model": "gpt-test",
                },
            }
        )

        accepted = websocket.receive_json()
        assert accepted["type"] == "session.message.accepted"
        completed = _receive_until(websocket, "session.message.completed")
        assert completed["payload"]["content"] == "WS_MEMORY_OBSERVATION_DONE"

        snapshot = _receive_until(websocket, "taskRun.snapshot.result")
        task_payload = snapshot["payload"]["task"]
        observation = task_payload["result_payload"]["memory_observation"]
        assert task_payload["task_run_id"] == accepted["payload"]["task_run_id"]
        assert observation["writeback"]["status"] == "no_candidates"
        assert observation["mark_used"]["status"] == "skipped"
    finally:
        context.__exit__(None, None, None)


def test_ws_followup_message_passes_previous_public_messages_without_current_user(client, monkeypatch):
    provider_calls: list[dict] = []

    def fake_respond(self, messages, tools, model, tool_choice=None, runtime_context=None):
        provider_calls.append({"messages": messages, "tools": tools, "model": model, "tool_choice": tool_choice})
        return AgentModelResponse(
            provider_name="openai_api",
            model=model,
            message=AgentMessage(role="assistant", content="FOLLOWUP_DONE", tool_calls=[]),
            output_text="FOLLOWUP_DONE",
            tool_calls=[],
            finish_reason="stop",
            metadata={"model": model},
        )

    async def fake_respond_async(self, messages, tools, model, tool_choice=None, runtime_context=None):
        return fake_respond(
            self,
            messages=messages,
            tools=tools,
            model=model,
            tool_choice=tool_choice,
            runtime_context=runtime_context,
        )

    monkeypatch.setattr("app.domain.providers.model.openai_api.OpenAIAPIProvider.respond", fake_respond)
    monkeypatch.setattr("app.domain.providers.model.openai_api.OpenAIAPIProvider.respond_async", fake_respond_async)
    context, websocket = _authenticated_socket(client, user_id="ws-followup-owner")
    try:
        session_store = client.app.state.session_store
        session_store.create_session(
            session_id="public_followup_session",
            session_key="public_followup_session",
            source="api.session",
            user_id="ws-followup-owner",
            metadata={"source": "api.session"},
        )
        session_store.append_message(
            session_id="public_followup_session",
            role="user",
            content="강남역에서 지갑 잃어버렸어",
            metadata={"source": "api.session"},
        )
        session_store.append_message(
            session_id="public_followup_session",
            role="assistant",
            content="분실물 조회 경로를 확인했습니다.",
            metadata={"source": "api.session"},
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_followup",
                "payload": {
                    "sessionId": "public_followup_session",
                    "content": "ㄴㄴ 분실물찾은거",
                    "clientMessageId": "client_msg_ws_followup",
                    "model": "gpt-test",
                },
            }
        )

        accepted = websocket.receive_json()
        _receive_until(websocket, "session.message.completed")

        task = client.app.state.repository.get_task(accepted["payload"]["task_run_id"])
        assert task is not None
        assert task.input_payload["conversation_history"] == [
            {"role": "user", "content": "강남역에서 지갑 잃어버렸어"},
            {"role": "assistant", "content": "분실물 조회 경로를 확인했습니다."},
        ]
        assert "ㄴㄴ 분실물찾은거" not in str(task.input_payload["conversation_history"])
        assert [message.role for message in provider_calls[0]["messages"][:2]] == ["user", "assistant"]
        current_user_count = sum(
            str(message.content).count("ㄴㄴ 분실물찾은거")
            for message in provider_calls[0]["messages"]
            if message.role == "user"
        )
        assert current_user_count == 1
    finally:
        context.__exit__(None, None, None)


def test_ws_session_message_create_sends_failed_frame_after_background_error(client, monkeypatch):
    _patch_respond_failure(monkeypatch)
    context, websocket = _authenticated_socket(client, user_id="ws-fail-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_create_fail",
                "payload": {
                    "content": "실패 frame 테스트",
                    "clientMessageId": "client_msg_ws_fail",
                    "model": "gpt-test",
                },
            }
        )

        accepted = websocket.receive_json()
        failed = _receive_until(websocket, "session.message.failed")

        assert accepted["type"] == "session.message.accepted"
        assert failed["payload"]["session_id"] == accepted["payload"]["session_id"]
        assert failed["payload"]["message_id"] != str(accepted["payload"]["user_message_id"])
        assert failed["payload"]["message_id"] == f"failed:{accepted['payload']['task_run_id']}"
        assert failed["payload"]["task_run_id"] == accepted["payload"]["task_run_id"]
        assert failed["payload"]["status"] == "FAILED"
        assert failed["payload"]["error"]["code"] == "background_task_failed"
    finally:
        context.__exit__(None, None, None)


def test_ws_list_snapshot_and_replay_happy_path(client, monkeypatch):
    _patch_respond(monkeypatch, text="WS_QUERY_DONE")
    context, websocket = _authenticated_socket(client, user_id="ws-query-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_create_query",
                "payload": {"content": "조회 테스트", "clientMessageId": "client_msg_ws_query", "model": "gpt-test"},
            }
        )
        accepted = websocket.receive_json()
        completed = _receive_until(websocket, "session.message.completed")
        session_id = accepted["payload"]["session_id"]
        task_run_id = completed["payload"]["task_run_id"]

        websocket.send_json({"protocolVersion": 1, "type": "session.list", "requestId": "req_sessions", "payload": {}})
        sessions = _receive_command_frame(websocket, "session.list.result", "req_sessions")
        assert sessions["type"] == "session.list.result"
        assert sessions["requestId"] == "req_sessions"
        assert [item["session_id"] for item in sessions["payload"]["items"]] == [session_id]

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.messages.list",
                "requestId": "req_messages",
                "payload": {"sessionId": session_id},
            }
        )
        messages = _receive_command_frame(websocket, "session.messages.list.result", "req_messages")
        assert messages["type"] == "session.messages.list.result"
        assert messages["type"] != "session.messages.result"
        assert messages["requestId"] == "req_messages"
        assert [item["role"] for item in messages["payload"]["items"]] == ["user", "assistant"]
        assert [item["role"] for item in messages["payload"]["messages"]] == ["user", "assistant"]
        assert all(isinstance(item["message_id"], str) for item in messages["payload"]["items"])

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRun.snapshot.get",
                "requestId": "req_snapshot",
                "payload": {"taskRunId": task_run_id, "includeSteps": True},
            }
        )
        snapshot = _receive_command_frame(websocket, "taskRun.snapshot.result", "req_snapshot")
        assert snapshot["type"] == "taskRun.snapshot.result"
        assert snapshot["requestId"] == "req_snapshot"
        assert snapshot["payload"]["task"]["task_run_id"] == task_run_id
        assert snapshot["payload"]["task_run"]["task_run_id"] == task_run_id
        assert len(snapshot["payload"]["steps"]) == 1
        assert len(snapshot["payload"]["step_runs"]) == 1
        assert snapshot["payload"]["approvals"] == []
        assert snapshot["payload"]["events"]
        assert snapshot["payload"]["events"][0]["task_run_id"] == task_run_id

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRun.events.replay",
                "requestId": "req_replay",
                "payload": {"taskRunId": task_run_id, "afterSequence": 0},
            }
        )
        replay = _receive_command_frame(websocket, "taskRun.events.replay.result", "req_replay")
        assert replay["type"] == "taskRun.events.replay.result"
        assert replay["requestId"] == "req_replay"
        assert replay["payload"]["events"]
        assert replay["payload"]["events"][0]["task_run_id"] == task_run_id
    finally:
        context.__exit__(None, None, None)


def test_ws_session_agent_task_child_taskrun_can_be_subscribed_snapshotted_and_replayed(client, monkeypatch):
    work_repository = RealtimeFakeWorkRepository()
    client.app.state.work_repository = work_repository
    client.app.state.task_engine.work_repository = work_repository
    client.app.state.tool_runtime.work_repository = work_repository

    _patch_respond_sequence(
        monkeypatch,
        [
            _model_tool_response(
                model="gpt-test",
                tool_calls=[
                    _tool_call(
                        "call-session-agent-1",
                        "session_agent_task",
                        {
                            "title": "강남역 지갑 분실 대응",
                            "instruction": "강남역에서 분실한 지갑을 찾기 위한 한국 지하철 유실물 확인 절차를 정리합니다.",
                            "requiredSkillNames": ["subway-lost-property"],
                            "expectedDeliverable": "공식 확인 경로와 다음 행동 목록",
                            "constraints": ["한국 기준으로 안내"],
                        },
                    ),
                ],
            ),
            _model_text_response(
                model="gpt-test",
                text="CHILD_DONE",
                work_disposition={"status": "done", "summary": "지하철 유실물 확인 절차를 정리했습니다."},
            ),
            _model_text_response(model="gpt-test", text="PARENT_DONE"),
        ],
    )
    context, websocket = _authenticated_socket(client, user_id="ws-session-agent-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_session_agent_realtime",
                "payload": {
                    "content": "강남역에서 지갑을 잃어버렸는데 유실물 확인을 맡겨줘",
                    "clientMessageId": "client_session_agent_realtime",
                    "model": "gpt-test",
                    "inputPayload": {"sessionConfigSnapshot": {"seedDefaultAgents": True}},
                },
            }
        )

        accepted = websocket.receive_json()
        assert accepted["type"] == "session.message.accepted"
        parent_task_run_id = accepted["payload"]["task_run_id"]
        child_task_run_id = None
        parent_start_payload = None
        seen_types: list[str] = []

        for _ in range(80):
            frame = websocket.receive_json()
            seen_types.append(str(frame.get("type")))
            if frame.get("type") != "task.event":
                continue
            data = frame.get("data") or {}
            payload = data.get("payload") or {}
            if (
                data.get("task_run_id") == parent_task_run_id
                and data.get("event_type") == "step.updated"
                and payload.get("reason") == "session_agent_work.started"
            ):
                parent_start_payload = payload
                child_task_run_id = str(payload["childTaskRunId"])
                break

        assert child_task_run_id is not None, seen_types
        assert parent_start_payload["childTaskRunId"] == child_task_run_id
        assert parent_start_payload["taskRunId"] == child_task_run_id
        assert parent_start_payload["childWorkId"].startswith("work_")
        assert parent_start_payload["profileId"].startswith("agent_profile_")
        assert parent_start_payload["workStatus"] == "in_progress"
        assert client.app.state.repository.get_task(child_task_run_id) is not None

        observed_after_child_handoff: list[dict] = []
        websocket.send_json({"type": "subscribe.task", "requestId": "req_child_subscribe", "taskRunId": child_task_run_id})
        subscribed = _receive_until(
            websocket,
            "subscribed",
            max_frames=80,
            seen_frames=observed_after_child_handoff,
        )
        assert subscribed["requestId"] == "req_child_subscribe"
        assert subscribed["taskRunId"] == child_task_run_id

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRun.snapshot.get",
                "requestId": "req_child_snapshot",
                "payload": {"taskRunId": child_task_run_id, "includeSteps": True, "includeEvents": True},
            }
        )
        snapshot = _receive_command_frame(
            websocket,
            "taskRun.snapshot.result",
            "req_child_snapshot",
            max_frames=80,
            seen_frames=observed_after_child_handoff,
        )
        assert snapshot["requestId"] == "req_child_snapshot"
        assert snapshot["payload"]["task"]["task_run_id"] == child_task_run_id
        assert snapshot["payload"]["events"]
        assert {event["task_run_id"] for event in snapshot["payload"]["events"]} == {child_task_run_id}

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRun.events.replay",
                "requestId": "req_child_replay",
                "payload": {"taskRunId": child_task_run_id, "afterSequence": 0},
            }
        )
        replay = _receive_command_frame(
            websocket,
            "taskRun.events.replay.result",
            "req_child_replay",
            max_frames=80,
            seen_frames=observed_after_child_handoff,
        )
        assert replay["requestId"] == "req_child_replay"
        assert replay["payload"]["events"]
        assert {event["task_run_id"] for event in replay["payload"]["events"]} == {child_task_run_id}
        assert replay["payload"]["retention_exceeded"] is False

        # child 구독 ack보다 parent 완료 frame이 먼저 도착할 수 있으므로 이미 본 frame을 재사용한다.
        completed = next(
            (
                frame
                for frame in observed_after_child_handoff
                if frame.get("type") == "session.message.completed"
                and (frame.get("payload") or {}).get("task_run_id") == parent_task_run_id
            ),
            None,
        )
        if completed is None:
            completed = _receive_until(websocket, "session.message.completed", max_frames=80)
        assert completed["payload"]["task_run_id"] == parent_task_run_id
        assert completed["payload"]["content"] == "PARENT_DONE"
    finally:
        context.__exit__(None, None, None)


def test_ws_task_runs_active_list_filters_authenticated_owner(client):
    client.app.state.backend_auth_client = FakeBackendAuthClient(user_id="active-owner")
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_active_ws_owner",
            task_type="agent.loop",
            owner_key="active-owner",
            session_key="session_active_ws",
            status="RUNNING",
            title="active command",
        )
    )
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_active_ws_other",
            task_type="agent.loop",
            owner_key="other-owner",
            session_key="session_active_ws",
            status="RUNNING",
            title="other command",
        )
    )

    with client.websocket_connect("/ai/api/v1/realtime/user/ws") as websocket:
        websocket.send_json({"type": "auth.start", "accessToken": "token-secret"})
        websocket.receive_json()
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRuns.active.list",
                "requestId": "req_active",
                "payload": {"sessionId": "session_active_ws"},
            }
        )

        response = websocket.receive_json()

    assert response["type"] == "taskRuns.active.list.result"
    assert response["type"] != "taskRuns.active.result"
    assert response["requestId"] == "req_active"
    assert [item["task_run_id"] for item in response["payload"]["items"]] == ["task_active_ws_owner"]
    assert [item["task_run_id"] for item in response["payload"]["task_runs"]] == ["task_active_ws_owner"]


def test_ws_task_runs_active_list_pushes_authenticated_owner_filter_to_repository(client):
    client.app.state.backend_auth_client = FakeBackendAuthClient(user_id="active-owner")
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_active_ws_owner_filter",
            task_type="agent.loop",
            owner_key="active-owner",
            session_key="session_active_ws_owner_filter",
            status="RUNNING",
            title="active command",
        )
    )

    class _OwnerRecordingRepository:
        def __init__(self, inner):
            self.inner = inner
            self.list_owner_keys: list[str | None] = []

        def __getattr__(self, name):
            return getattr(self.inner, name)

        def list_tasks_by_statuses(self, statuses, *, session_key=None, owner_key=None, limit=50, offset=0):
            self.list_owner_keys.append(owner_key)
            return self.inner.list_tasks_by_statuses(
                statuses,
                session_key=session_key,
                owner_key=owner_key,
                limit=limit,
                offset=offset,
            )

    recording_repository = _OwnerRecordingRepository(client.app.state.repository)
    client.app.state.repository = recording_repository

    with client.websocket_connect("/ai/api/v1/realtime/user/ws") as websocket:
        websocket.send_json({"type": "auth.start", "accessToken": "token-secret"})
        websocket.receive_json()
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRuns.active.list",
                "requestId": "req_active_owner_filter",
                "payload": {"sessionId": "session_active_ws_owner_filter"},
            }
        )

        response = websocket.receive_json()

    assert response["type"] == "taskRuns.active.list.result"
    assert recording_repository.list_owner_keys == ["active-owner"]


def test_ws_task_run_snapshot_and_replay_include_activity_transcript(client):
    client.app.state.backend_auth_client = FakeBackendAuthClient(user_id="activity-owner")
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_activity_ws",
            task_type="agent.loop",
            owner_key="activity-owner",
            session_key="session_activity_ws",
            status="COMPLETED",
            title="activity command",
        )
    )
    for sequence, event_type in ((1, "tool.started"), (2, "tool.completed")):
        client.app.state.repository.append_event(
            TaskEventEnvelope(
                event_id=f"event-activity-{sequence}",
                event_type=event_type,
                task_run_id="task_activity_ws",
                step_run_id="step-activity",
                producer="test",
                occurred_at=f"2026-05-14T00:00:0{sequence}+00:00",
                status="RUNNING" if event_type == "tool.started" else "COMPLETED",
                summary_message="날씨 조회",
                payload={
                    "tool_call_id": "call-weather",
                    "tool_name": "http_get",
                    "title": "날씨 조회",
                    "result": {"ok": True} if event_type == "tool.completed" else None,
                },
            )
        )

    with client.websocket_connect("/ai/api/v1/realtime/user/ws") as websocket:
        websocket.send_json({"type": "auth.start", "accessToken": "token-secret"})
        websocket.receive_json()
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRun.snapshot.get",
                "requestId": "req_activity_snapshot",
                "payload": {"taskRunId": "task_activity_ws", "includeSteps": False},
            }
        )
        snapshot = websocket.receive_json()
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRun.events.replay",
                "requestId": "req_activity_replay",
                "payload": {"taskRunId": "task_activity_ws", "afterSequence": 0},
            }
        )
        replay = websocket.receive_json()

    assert snapshot["payload"]["activity_items"][0]["activity_id"] == "tool:task_activity_ws:call-weather"
    assert snapshot["payload"]["activityItems"][0]["status"] == "COMPLETED"
    assert replay["payload"]["activity_items"][0]["completed_event_id"] == "event-activity-2"


def test_ws_task_runs_active_list_hides_orphaned_running_task(client):
    client.app.state.backend_auth_client = FakeBackendAuthClient(user_id="active-orphan-owner")
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_active_orphan_ws",
            task_type="agent.loop",
            owner_key="active-orphan-owner",
            session_key="session_active_orphan_ws",
            status="RUNNING",
            title="orphan command",
            queue_status="running",
        )
    )
    client.app.state.repository.tasks["task_active_orphan_ws"].updated_at = utc_now() - timedelta(minutes=20)

    with client.websocket_connect("/ai/api/v1/realtime/user/ws") as websocket:
        websocket.send_json({"type": "auth.start", "accessToken": "token-secret"})
        websocket.receive_json()
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRuns.active.list",
                "requestId": "req_active_orphan",
                "payload": {"sessionId": "session_active_orphan_ws"},
            }
        )

        response = websocket.receive_json()

    assert response["type"] == "taskRuns.active.list.result"
    assert response["payload"]["items"] == []
    assert response["payload"]["task_runs"] == []


def test_ws_task_runs_active_list_hides_projection_only_task(client):
    client.app.state.backend_auth_client = FakeBackendAuthClient(user_id="active-projection-owner")
    client.app.state.task_projection_store.save_task_snapshot(
        TaskRun(
            task_run_id="task_projection_only_ws",
            task_type="agent.loop",
            owner_key="active-projection-owner",
            session_key="session_projection_only_ws",
            status="RUNNING",
            title="projection only",
        )
    )

    with client.websocket_connect("/ai/api/v1/realtime/user/ws") as websocket:
        websocket.send_json({"type": "auth.start", "accessToken": "token-secret"})
        websocket.receive_json()
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "taskRuns.active.list",
                "requestId": "req_projection_only",
                "payload": {"sessionId": "session_projection_only_ws"},
            }
        )

        response = websocket.receive_json()

    assert response["type"] == "taskRuns.active.list.result"
    assert response["payload"]["items"] == []


def test_ws_session_undo_rejects_when_session_is_running(client):
    context, websocket = _authenticated_socket(client, user_id="undo-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="undo_running_session",
            session_key="undo_running_session",
            source="api.session",
            user_id="undo-owner",
            metadata={"source": "api.session"},
        )
        store.append_user_message_and_start_task(
            owner_key="undo-owner",
            session_id="undo_running_session",
            content="실행 중 메시지",
            client_message_id="client_undo_running",
            task_run_id="task_undo_running",
            base_history_version=0,
        )
        client.app.state.repository.create_task(
            TaskRun(
                task_run_id="task_undo_running",
                task_type="agent.loop",
                owner_key="undo-owner",
                session_key="undo_running_session",
                status="RUNNING",
                title="실행 중",
            )
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.undo",
                "requestId": "req_undo_running",
                "payload": {
                    "sessionId": "undo_running_session",
                    "clientCommandId": "cmd_undo_running",
                },
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "command.error"
        assert response["error"]["code"] == "conflict"
    finally:
        context.__exit__(None, None, None)


def test_ws_session_retry_reuses_last_user_message_without_duplicate_user_append(client, monkeypatch):
    _patch_respond(monkeypatch, text="RETRY_DONE")
    context, websocket = _authenticated_socket(client, user_id="retry-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="retry_session",
            session_key="retry_session",
            source="api.session",
            user_id="retry-owner",
            metadata={"source": "api.session"},
        )
        user_message_id = store.append_message(
            session_id="retry_session",
            role="user",
            content="강남역 분실물 다시 확인해줘",
            metadata={"source": "api.session"},
        )
        store.append_message(
            session_id="retry_session",
            role="assistant",
            content="이전 답변",
            metadata={"source": "api.session", "task_run_id": "task_old_retry"},
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.retry",
                "requestId": "req_retry",
                "payload": {
                    "sessionId": "retry_session",
                    "targetMessageId": str(user_message_id),
                    "clientCommandId": "cmd_retry",
                },
            }
        )

        accepted = websocket.receive_json()
        completed = _receive_until(websocket, "session.message.completed")
        messages = store.list_messages("retry_session")

        assert accepted["type"] == "session.message.accepted"
        assert completed["payload"]["content"] == "RETRY_DONE"
        assert [message["role"] for message in messages] == ["user", "assistant"]
        assert [message["content"] for message in messages] == [
            "강남역 분실물 다시 확인해줘",
            "RETRY_DONE",
        ]
    finally:
        context.__exit__(None, None, None)


def test_ws_session_retry_clears_running_guard_when_task_creation_fails(client, monkeypatch):
    context, websocket = _authenticated_socket(client, user_id="retry-fail-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="retry_fail_session",
            session_key="retry_fail_session",
            source="api.session",
            user_id="retry-fail-owner",
            metadata={"source": "api.session"},
        )
        user_message_id = store.append_message(
            session_id="retry_fail_session",
            role="user",
            content="실패해도 guard는 정리한다",
            metadata={"source": "api.session"},
        )
        store.append_message(
            session_id="retry_fail_session",
            role="assistant",
            content="이전 답변",
            metadata={"source": "api.session", "task_run_id": "task_old_retry_fail"},
        )

        def fail_create_task(task):
            raise RuntimeError("create_task failed")

        monkeypatch.setattr(client.app.state.repository, "create_task", fail_create_task)

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.retry",
                "requestId": "req_retry_fail",
                "payload": {
                    "sessionId": "retry_fail_session",
                    "targetMessageId": str(user_message_id),
                    "clientCommandId": "cmd_retry_fail",
                },
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "command.error"
        assert response["error"]["code"] == "internal_error"
        assert store.get_session("retry_fail_session")["running_task_run_id"] is None
    finally:
        context.__exit__(None, None, None)


def test_ws_session_update_changes_title_for_owner(client):
    context, websocket = _authenticated_socket(client, user_id="update-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="update_title_session",
            session_key="update_title_session",
            source="api.session",
            user_id="update-owner",
            title="이전 제목",
            metadata={"source": "api.session"},
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.update",
                "requestId": "req_update_title",
                "payload": {
                    "sessionId": "update_title_session",
                    "clientCommandId": "cmd_update_title",
                    "title": "변경된 제목",
                },
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "session.updated"
        assert response["payload"]["session"]["title"] == "변경된 제목"
        assert store.get_session("update_title_session")["title"] == "변경된 제목"
    finally:
        context.__exit__(None, None, None)


def test_ws_session_update_rejects_protected_metadata_patch(client):
    context, websocket = _authenticated_socket(client, user_id="metadata-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="metadata_patch_session",
            session_key="metadata_patch_session",
            source="api.session",
            user_id="metadata-owner",
            metadata={"source": "api.session"},
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.update",
                "requestId": "req_metadata_patch",
                "payload": {
                    "sessionId": "metadata_patch_session",
                    "clientCommandId": "cmd_metadata_patch",
                    "metadataPatch": {
                        "owner_key": "other-user",
                        "source": "api.session",
                        "message_count": 999,
                        "running_task_run_id": "task_injected",
                        "history_version": 999,
                    },
                },
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "command.error"
        assert response["error"]["code"] == "invalid_payload"
        assert store.get_session("metadata_patch_session")["user_id"] == "metadata-owner"
        assert store.get_session("metadata_patch_session")["running_task_run_id"] is None
    finally:
        context.__exit__(None, None, None)


def test_ws_session_update_denies_cross_user_session(client):
    store = client.app.state.session_store
    store.create_session(
        session_id="cross_user_update_session",
        session_key="cross_user_update_session",
        source="api.session",
        user_id="session-owner",
        title="원래 제목",
        metadata={"source": "api.session"},
    )
    context, websocket = _authenticated_socket(client, user_id="other-user")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.update",
                "requestId": "req_cross_user_update",
                "payload": {
                    "sessionId": "cross_user_update_session",
                    "clientCommandId": "cmd_cross_user_update",
                    "title": "바꾸면 안 되는 제목",
                },
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "command.error"
        assert response["error"]["code"] == "forbidden"
        assert store.get_session("cross_user_update_session")["title"] == "원래 제목"
    finally:
        context.__exit__(None, None, None)


def test_ws_session_update_rejects_running_session(client):
    context, websocket = _authenticated_socket(client, user_id="running-update-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="running_update_session",
            session_key="running_update_session",
            source="api.session",
            user_id="running-update-owner",
            title="실행 중",
            metadata={"source": "api.session"},
        )
        store.append_user_message_and_start_task(
            owner_key="running-update-owner",
            session_id="running_update_session",
            content="작업 중",
            client_message_id="client_running_update",
            task_run_id="task_running_update",
            base_history_version=0,
        )
        client.app.state.repository.create_task(
            TaskRun(
                task_run_id="task_running_update",
                task_type="agent.loop",
                owner_key="running-update-owner",
                session_key="running_update_session",
                status="RUNNING",
                title="실행 중",
            )
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.update",
                "requestId": "req_running_update",
                "payload": {
                    "sessionId": "running_update_session",
                    "clientCommandId": "cmd_running_update",
                    "title": "실행 중 변경",
                },
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "command.error"
        assert response["error"]["code"] == "conflict"
    finally:
        context.__exit__(None, None, None)


def test_ws_session_update_clears_orphaned_running_guard(client):
    context, websocket = _authenticated_socket(client, user_id="orphaned-update-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="orphaned_update_session",
            session_key="orphaned_update_session",
            source="api.session",
            user_id="orphaned-update-owner",
            title="멈춘 실행",
            metadata={"source": "api.session"},
        )
        store.append_user_message_and_start_task(
            owner_key="orphaned-update-owner",
            session_id="orphaned_update_session",
            content="멈춘 작업",
            client_message_id="client_orphaned_update",
            task_run_id="task_orphaned_update",
            base_history_version=0,
        )
        task = TaskRun(
            task_run_id="task_orphaned_update",
            task_type="agent.loop",
            owner_key="orphaned-update-owner",
            session_key="orphaned_update_session",
            status="RUNNING",
            title="멈춘 실행",
            queue_status="running",
        )
        client.app.state.repository.create_task(task)
        client.app.state.repository.tasks["task_orphaned_update"].updated_at = utc_now() - timedelta(minutes=20)

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.update",
                "requestId": "req_orphaned_update",
                "payload": {
                    "sessionId": "orphaned_update_session",
                    "clientCommandId": "cmd_orphaned_update",
                    "title": "다시 수정 가능",
                },
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "session.updated"
        assert store.get_session("orphaned_update_session")["running_task_run_id"] is None
        recovered = client.app.state.repository.get_task("task_orphaned_update")
        assert recovered is not None
        assert recovered.status == "FAILED"
        assert recovered.queue_status == "terminal"
    finally:
        context.__exit__(None, None, None)


def test_ws_session_archive_and_delete_exclude_from_default_list(client):
    context, websocket = _authenticated_socket(client, user_id="lifecycle-owner")
    try:
        store = client.app.state.session_store
        for session_id in ("active_lifecycle_session", "archive_lifecycle_session", "delete_lifecycle_session"):
            store.create_session(
                session_id=session_id,
                session_key=session_id,
                source="api.session",
                user_id="lifecycle-owner",
                title=session_id,
                metadata={"source": "api.session"},
            )
        store.append_message(
            session_id="delete_lifecycle_session",
            role="user",
            content="삭제 후에도 보존될 메시지",
            metadata={"source": "api.session"},
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.archive",
                "requestId": "req_archive_session",
                "payload": {
                    "sessionId": "archive_lifecycle_session",
                    "clientCommandId": "cmd_archive_session",
                    "archived": True,
                },
            }
        )
        archived = websocket.receive_json()
        assert archived["type"] == "session.archived"

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.delete",
                "requestId": "req_delete_session",
                "payload": {
                    "sessionId": "delete_lifecycle_session",
                    "clientCommandId": "cmd_delete_session",
                },
            }
        )
        deleted = websocket.receive_json()
        assert deleted["type"] == "session.deleted"

        websocket.send_json({"protocolVersion": 1, "type": "session.list", "requestId": "req_lifecycle_list", "payload": {}})
        listed = websocket.receive_json()
        listed_ids = [item["session_id"] for item in listed["payload"]["items"]]

        assert listed_ids == ["active_lifecycle_session"]
        assert store.get_session("archive_lifecycle_session")["archived_at"] is not None
        assert store.get_session("delete_lifecycle_session")["deleted_at"] is not None
        assert [message["content"] for message in store.list_messages("delete_lifecycle_session")] == ["삭제 후에도 보존될 메시지"]

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.list",
                "requestId": "req_lifecycle_archived_list",
                "payload": {"includeArchived": True},
            }
        )
        archived_listed = websocket.receive_json()
        archived_listed_ids = [item["session_id"] for item in archived_listed["payload"]["items"]]
        assert archived_listed_ids == ["archive_lifecycle_session", "active_lifecycle_session"]

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.archive",
                "requestId": "req_restore_session",
                "payload": {
                    "sessionId": "archive_lifecycle_session",
                    "clientCommandId": "cmd_restore_session",
                    "archived": False,
                },
            }
        )
        restored = websocket.receive_json()
        assert restored["type"] == "session.archived"
        assert restored["payload"]["archived"] is False
        assert store.get_session("archive_lifecycle_session")["archived_at"] is None
    finally:
        context.__exit__(None, None, None)


def test_ws_session_settings_snapshot_wins_over_message_overrides(client, monkeypatch):
    _patch_respond(monkeypatch, text="SETTINGS_DONE")
    context, websocket = _authenticated_socket(client, user_id="settings-owner")
    try:
        store = client.app.state.session_store
        store.create_session(
            session_id="settings_snapshot_session",
            session_key="settings_snapshot_session",
            source="api.session",
            user_id="settings-owner",
            title="설정 스냅샷",
            metadata={"source": "api.session"},
        )

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.settings.update",
                "requestId": "req_settings_update",
                "payload": {
                    "sessionId": "settings_snapshot_session",
                    "clientCommandId": "cmd_settings_update",
                    "settings": {
                        "model": "gpt-session",
                        "systemPrompt": "세션에 저장된 시스템 프롬프트",
                        "toolsets": ["session", "planning"],
                        "delegationPolicy": {"canDelegate": False, "maxWorkerDepth": 1},
                    },
                },
            }
        )
        settings_response = websocket.receive_json()
        assert settings_response["type"] == "session.settings.updated"
        first_history_version = settings_response["payload"]["session"]["history_version"]

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.settings.update",
                "requestId": "req_settings_update_repeat",
                "payload": {
                    "sessionId": "settings_snapshot_session",
                    "clientCommandId": "cmd_settings_update",
                    "settings": {
                        "model": "gpt-session",
                        "systemPrompt": "세션에 저장된 시스템 프롬프트",
                        "toolsets": ["session", "planning"],
                        "delegationPolicy": {"canDelegate": False, "maxWorkerDepth": 1},
                    },
                },
            }
        )
        repeated_settings_response = websocket.receive_json()
        assert repeated_settings_response["type"] == "session.settings.updated"
        assert repeated_settings_response["payload"]["session"]["history_version"] == first_history_version

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.settings.update",
                "requestId": "req_settings_update_conflict",
                "payload": {
                    "sessionId": "settings_snapshot_session",
                    "clientCommandId": "cmd_settings_update",
                    "settings": {"model": "gpt-conflict"},
                },
            }
        )
        conflict_response = websocket.receive_json()
        assert conflict_response["type"] == "command.error"
        assert conflict_response["error"]["code"] == "conflict"

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.settings.update",
                "requestId": "req_settings_update_forbidden_toolset",
                "payload": {
                    "sessionId": "settings_snapshot_session",
                    "clientCommandId": "cmd_settings_update_forbidden_toolset",
                    "settings": {"toolsets": ["all"]},
                },
            }
        )
        invalid_toolset_response = websocket.receive_json()
        assert invalid_toolset_response["type"] == "command.error"
        assert invalid_toolset_response["error"]["code"] == "invalid_payload"

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.settings.update",
                "requestId": "req_settings_update_patch",
                "payload": {
                    "sessionId": "settings_snapshot_session",
                    "clientCommandId": "cmd_settings_update_patch",
                    "settings": {"model": "gpt-session-patch"},
                },
            }
        )
        patched_settings_response = websocket.receive_json()
        assert patched_settings_response["type"] == "session.settings.updated"
        assert patched_settings_response["payload"]["settings"]["model"] == "gpt-session-patch"
        assert patched_settings_response["payload"]["settings"]["toolsets"] == ["session", "planning"]

        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_settings_message",
                "payload": {
                    "sessionId": "settings_snapshot_session",
                    "content": "설정 스냅샷으로 실행해줘",
                    "clientMessageId": "client_settings_snapshot",
                    "model": "gpt-request",
                    "inputPayload": {
                        "model": "gpt-input-payload",
                        "systemPrompt": "요청 본문 프롬프트",
                        "toolsets": ["web"],
                        "delegationPolicy": {"canDelegate": True},
                    },
                },
            }
        )

        accepted = websocket.receive_json()
        _receive_until(websocket, "session.message.completed")
        task = client.app.state.repository.get_task(accepted["payload"]["task_run_id"])

        assert task is not None
        assert task.input_payload["model"] == "gpt-5.4"
        assert task.input_payload["system_prompt_snapshot"] == "세션에 저장된 시스템 프롬프트"
        assert task.input_payload["toolsets"] == ["session", "planning"]
        assert task.input_payload["enabled_toolsets"] == ["session", "planning"]
        assert task.input_payload["delegation_policy"] == {"canDelegate": False, "maxWorkerDepth": 1}
        assert task.input_payload["settings_snapshot"]["model"] == "gpt-session-patch"
    finally:
        context.__exit__(None, None, None)


def test_ws_model_options_returns_provider_model_choices(client):
    context, websocket = _authenticated_socket(client, user_id="model-options-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "model.options",
                "requestId": "req_model_options",
                "payload": {},
            }
        )

        response = websocket.receive_json()

        assert response["type"] == "model.options.result"
        assert response["payload"]["model"]
        assert response["payload"]["providers"]
        assert all("models" in provider for provider in response["payload"]["providers"])
    finally:
        context.__exit__(None, None, None)


def test_ws_new_session_message_can_seed_safe_session_settings(client, monkeypatch):
    _patch_respond(monkeypatch, text="NEW_SETTINGS_DONE")
    context, websocket = _authenticated_socket(client, user_id="new-settings-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_new_settings_message",
                "payload": {
                    "content": "새 설정 세션을 시작해줘",
                    "clientMessageId": "client_new_settings_message",
                    "settings": {
                        "systemPrompt": "새 세션에서만 적용할 프롬프트",
                        "toolsets": ["session", "planning"],
                    },
                },
            }
        )

        accepted = websocket.receive_json()
        _receive_until(websocket, "session.message.completed")
        session = client.app.state.session_store.get_session(accepted["payload"]["session_id"])
        task = client.app.state.repository.get_task(accepted["payload"]["task_run_id"])

        assert session is not None
        assert session["settings"]["systemPrompt"] == "새 세션에서만 적용할 프롬프트"
        assert task is not None
        assert task.input_payload["system_prompt_snapshot"] == "새 세션에서만 적용할 프롬프트"
        assert task.input_payload["enabled_toolsets"] == ["session", "planning"]
    finally:
        context.__exit__(None, None, None)


def test_ws_new_session_message_augments_toolsets_for_enabled_skill(client, monkeypatch):
    _patch_respond(monkeypatch, text="SKILL_SETTINGS_DONE")
    client.app.state.skill_registry.register_many(
        [
            {
                "name": "korea-weather",
                "description": "날씨 조회",
                "body": "`http_get` runtime tool 로 조회한다.",
            }
        ]
    )
    client.app.state.skill_repository.sync_builtin_catalog(
        [
            {
                "name": "korea-weather",
                "description": "날씨 조회",
                "body": "`http_get` runtime tool 로 조회한다.",
            }
        ]
    )
    store = client.app.state.session_store
    store.create_session(
        session_id="skill_settings_session",
        session_key="skill_settings_session",
        source="api.session",
        user_id="skill-settings-owner",
        metadata={"source": "api.session"},
        settings={"toolsets": ["skills"]},
    )
    client.app.state.agent_repository.create_session_agent(
        session_id="skill_settings_session",
        owner_key="skill-settings-owner",
        owner_user_id=None,
        agent_type="main",
        config_snapshot={
            "name": "팀장",
            "skills": ["korea-weather"],
        },
        delegation_policy={"canDelegate": True},
    )
    context, websocket = _authenticated_socket(client, user_id="skill-settings-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_skill_settings_message",
                "payload": {
                    "sessionId": "skill_settings_session",
                    "content": "부산역 날씨 조회해줘",
                    "clientMessageId": "client_skill_settings_message",
                },
            }
        )

        accepted = websocket.receive_json()
        _receive_until(websocket, "session.message.completed")
        task = client.app.state.repository.get_task(accepted["payload"]["task_run_id"])

        assert task is not None
        assert "korea-weather" in task.input_payload["enabledSkillNames"]
        assert task.input_payload["enabled_toolsets"] == ["skills", "web", "tool-result"]
        assert task.input_payload["toolsets"] == ["skills", "web", "tool-result"]
    finally:
        context.__exit__(None, None, None)


def test_ws_main_agent_skill_keeps_default_local_toolsets(client, monkeypatch):
    _patch_respond(monkeypatch, text="MAIN_AGENT_DEFAULT_TOOLSETS_DONE")
    store = client.app.state.session_store
    store.create_session(
        session_id="main_agent_default_toolsets_session",
        session_key="main_agent_default_toolsets_session",
        source="api.session",
        user_id="main-agent-toolsets-owner",
        metadata={"source": "api.session"},
        settings={},
    )
    client.app.state.agent_repository.create_session_agent(
        session_id="main_agent_default_toolsets_session",
        owner_key="main-agent-toolsets-owner",
        owner_user_id=None,
        agent_type="main",
        config_snapshot={
            "name": "팀장",
            "skills": ["mattermost-send"],
        },
        delegation_policy={"canDelegate": True},
    )
    context, websocket = _authenticated_socket(client, user_id="main-agent-toolsets-owner")
    try:
        websocket.send_json(
            {
                "protocolVersion": 1,
                "type": "session.message.create",
                "requestId": "req_main_agent_default_toolsets_message",
                "payload": {
                    "sessionId": "main_agent_default_toolsets_session",
                    "content": "내 로컬에 html 파일 하나 만들어줘",
                    "clientMessageId": "client_main_agent_default_toolsets_message",
                },
            }
        )

        accepted = websocket.receive_json()
        _receive_until(websocket, "session.message.completed")
        task = client.app.state.repository.get_task(accepted["payload"]["task_run_id"])

        assert task is not None
        assert "mattermost-send" in task.input_payload["enabledSkillNames"]
        enabled_toolsets = set(task.input_payload["enabled_toolsets"])
        assert {"file", "terminal", "messaging"}.issubset(enabled_toolsets)
        assert "browser" not in enabled_toolsets
    finally:
        context.__exit__(None, None, None)


def test_ws_subscribe_task_preserves_request_id_when_provided(client):
    client.app.state.backend_auth_client = FakeBackendAuthClient(user_id="subscribe-owner")
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_subscribe_request_id",
            task_type="agent.loop",
            owner_key="subscribe-owner",
            status="RUNNING",
            title="subscribe command",
        )
    )

    with client.websocket_connect("/ai/api/v1/realtime/user/ws") as websocket:
        websocket.send_json({"type": "auth.start", "accessToken": "token-secret"})
        websocket.receive_json()
        websocket.send_json({"type": "subscribe.task", "requestId": "req_subscribe", "taskRunId": "task_subscribe_request_id"})

        response = websocket.receive_json()

    assert response["type"] == "subscribed"
    assert response["requestId"] == "req_subscribe"
    assert response["taskRunId"] == "task_subscribe_request_id"
