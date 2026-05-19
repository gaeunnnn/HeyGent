from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import sys

from app.clients.backend_auth import BackendAuthVerifyResult
from app.clients.backend_memory import BackendMemoryItem
from app.contracts.event.task_events import TaskEventEnvelope
from app.contracts.task.task_status import TaskStatus
from app.domain.orchestration.delegation.spec import ChildSessionLaunchResult
from app.domain.providers.model.base import AgentMessage, AgentModelResponse, AssistantToolCall
from app.domain.tasks.models import StepRun, TaskRun
from app.storage.redis import FakeRedis, RedisTaskProjectionStore


class FakeBackendAuthClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    async def verify_access_token(self, access_token: str, *, workspace_key: str | None = None) -> BackendAuthVerifyResult:
        self.calls.append({"access_token": access_token, "workspace_key": workspace_key})
        return BackendAuthVerifyResult(user_id=access_token)


def _response(
    *,
    text: str = "",
    tool_calls: list[AssistantToolCall] | None = None,
    model: str = "gpt-test",
    progress_update: dict | None = None,
    work_disposition: dict | None = None,
) -> AgentModelResponse:
    calls = tool_calls or []
    return AgentModelResponse(
        provider_name="openai_api",
        model=model,
        message=AgentMessage(role="assistant", content=text, tool_calls=calls),
        output_text=text,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        metadata={"model": model},
        progress_update=progress_update,
        work_disposition=work_disposition,
        visible_text=text,
    )


def _tool_call(call_id: str, name: str, arguments: dict) -> AssistantToolCall:
    return AssistantToolCall(id=call_id, name=name, arguments=arguments)


def _patch_respond(monkeypatch, responses: list[AgentModelResponse | Exception]) -> list[dict]:
    iterator = iter(responses)
    calls: list[dict] = []

    def fake_respond(self, messages, tools, model, tool_choice=None, runtime_context=None):
        calls.append({"messages": messages, "tools": tools, "model": model, "tool_choice": tool_choice})
        next_response = next(iterator)
        if isinstance(next_response, Exception):
            raise next_response
        return next_response

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
    return calls


def test_agent_loop_executes_native_tool_calls_on_runtime_step(client, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(
                progress_update={
                    "title": "요청 도구 실행 점검",
                    "summary": "필요한 도구를 실행한다.",
                },
                tool_calls=[
                    _tool_call(
                        "call_todo",
                        "todo",
                        {
                            "todos": [
                                {"id": "plan", "content": "계획 정리", "status": "completed"},
                                {"id": "ship", "content": "배포 점검", "status": "pending"},
                            ]
                        },
                    ),
                    _tool_call("call_terminal", "terminal_run", {"argv": [sys.executable, "-c", "print('TOOL_OK')"]}),
                ]
            ),
            _response(text="NATIVE_LOOP_DONE"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "tool-user",
            "session_key": "sess_native_loop",
            "input_payload": {"prompt": "필요하면 도구를 사용해 정리해줘.", "model": "gpt-test"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert "task_type" in body
    assert body["result_payload"]["text"] == "NATIVE_LOOP_DONE"
    assert [item["name"] for item in body["result_payload"]["tool_results"]] == ["todo", "terminal.run"]
    assert body["todo_state"]["currentKey"] is None
    exposed_tool_names = [tool["function"]["name"] for tool in provider_calls[0]["tools"]]
    assert "skills_list" in exposed_tool_names
    assert "skills_read" in exposed_tool_names
    assert "web_search" not in exposed_tool_names
    assert "http_get" in exposed_tool_names
    assert "terminal_run" in exposed_tool_names
    assert "step" not in exposed_tool_names
    assert all("." not in name for name in exposed_tool_names)

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert len(steps) == 1
    assert steps[0]["title"] == "요청 도구 실행 점검"
    assert steps[0]["input_payload"].get("todo_key") is None
    assert steps[0]["status"] == "COMPLETED"
    todo_items = steps[0]["detail_json"]["planningDetail"]["todoItems"]
    assert [item["key"] for item in todo_items] == ["plan", "ship"]
    assert [item["status"] for item in todo_items] == ["completed", "cancelled"]

    transcript_session = client.app.state.session_store.get_latest_session_by_key("sess_native_loop")
    transcript = client.app.state.session_store.list_messages(transcript_session["id"])
    assert [message["role"] for message in transcript] == ["user", "assistant", "tool", "tool", "assistant"]
    assert transcript[1]["tool_calls"][0]["id"] == "call_todo"
    assert transcript[2]["tool_call_id"] == "call_todo"


def test_direct_task_run_attaches_backend_memory_context(client, monkeypatch):
    client.app.state.backend_memory_client.memories = [
        BackendMemoryItem(
            id=11,
            memory_type="PREFERENCE",
            store_type="PROFILE",
            scope_type="GLOBAL",
            content="사용자는 결과를 세 줄 요약으로 받는 것을 선호한다.",
            metadata={"workspaceKey": "team-a"},
        )
    ]
    provider_calls = _patch_respond(monkeypatch, [_response(text="MEMORY_CONTEXT_DONE")])

    response = client.post(
        "/ai/api/v1/taskRuns",
        headers={"Authorization": "Bearer 42", "X-Workspace-Key": "team-a"},
        json={
            "owner_key": "ignored-owner",
            "session_key": "sess_memory_context",
            "input_payload": {
                "prompt": "회의 내용을 정리해줘",
                "persistent_memory_context": "client supplied context",
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    task = client.app.state.repository.get_task(body["task_run_id"])
    assert task is not None
    assert "사용자는 결과를 세 줄 요약으로 받는 것을 선호한다." in task.input_payload["persistent_memory_context"]
    assert "client supplied context" not in str(task.input_payload)
    assert client.app.state.backend_memory_client.calls[0]["user_id"] == "42"
    assert client.app.state.backend_memory_client.calls[0]["workspace_key"] == "team-a"
    assert "사용자는 결과를 세 줄 요약" in str(provider_calls[0]["messages"])


def test_agent_loop_emits_runtime_tool_progress_events_before_completion(client, monkeypatch, tmp_path):
    workspace = tmp_path / "progress-workspace"
    workspace.mkdir()
    _patch_respond(
        monkeypatch,
        [
            _response(
                tool_calls=[
                    _tool_call(
                        "call_todo",
                        "todo",
                        {
                            "todos": [
                                {"id": "research", "content": "이승엽 기록 자료 조사", "status": "in_progress"},
                                {"id": "write", "content": "이승엽 조사 보고서 파일 작성", "status": "pending"},
                            ]
                        },
                    ),
                    _tool_call(
                        "call_write",
                        "write_file",
                        {
                            "path": "tmp/testfile/progress.md",
                            "content": "progress file\n",
                        },
                    ),
                ]
            ),
            _response(text="파일 작성 완료"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "progress-user",
            "input_payload": {
                "prompt": "이승엽 보고서를 tmp/testfile/progress.md 파일로 작성해줘.",
                "workspace_root": str(workspace),
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert (workspace / "tmp/testfile/progress.md").read_text(encoding="utf-8") == "progress file\n"

    events = client.app.state.repository.list_events(body["task_run_id"])
    event_types = [event.event_type for event in events]
    assert "tool.started" in event_types
    assert "tool.completed" in event_types
    assert event_types.index("tool.completed") < event_types.index("task.completed")

    tool_completed = [event for event in events if event.event_type == "tool.completed"]
    assert [event.payload["tool_name"] for event in tool_completed] == ["todo", "write_file"]
    assert [event.status for event in tool_completed] == ["COMPLETED", "COMPLETED"]
    assert tool_completed[0].summary_message == "이승엽 기록 자료 조사"
    assert tool_completed[1].payload["path"] == "tmp/testfile/progress.md"


def test_agent_loop_keeps_tool_progress_run_scoped_without_step_declaration(client, monkeypatch, tmp_path):
    workspace = tmp_path / "run-scoped-tool-workspace"
    workspace.mkdir()
    _patch_respond(
        monkeypatch,
        [
            _response(
                tool_calls=[
                    _tool_call(
                        "call_write",
                        "write_file",
                        {
                            "path": "tmp/testfile/fallback.md",
                            "content": "fallback step\n",
                        },
                    ),
                ]
            ),
            _response(text="fallback done"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "fallback-step-user",
            "input_payload": {
                "prompt": "파일을 바로 작성해줘.",
                "workspace_root": str(workspace),
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert (workspace / "tmp/testfile/fallback.md").read_text(encoding="utf-8") == "fallback step\n"

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert len(steps) == 1
    assert steps[0]["status"] == "COMPLETED"

    events = client.app.state.repository.list_events(body["task_run_id"])
    tool_started = next(event for event in events if event.event_type == "tool.started")
    assert "step.created" in [event.event_type for event in events]
    assert "step.started" in [event.event_type for event in events]
    assert tool_started.step_run_id == steps[0]["step_run_id"]
    assert "internal_step_anchor" not in tool_started.payload
    assert "step_visibility" not in tool_started.payload


def test_agent_loop_keeps_single_runtime_step_after_tool_events_and_model_progress(client, monkeypatch, tmp_path):
    workspace = tmp_path / "run-scoped-to-semantic-workspace"
    workspace.mkdir()
    _patch_respond(
        monkeypatch,
        [
            _response(
                tool_calls=[
                    _tool_call(
                        "call_probe",
                        "write_file",
                        {
                            "path": "tmp/testfile/probe.md",
                            "content": "probe\n",
                        },
                    ),
                ]
            ),
            _response(
                progress_update={
                    "title": "보고서 작성",
                    "summary": "보고서 작성 중",
                },
            ),
            _response(text="semantic steps done"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "fallback-semantic-user",
            "input_payload": {
                "prompt": "먼저 확인한 뒤 의미 단계를 선언해줘.",
                "workspace_root": str(workspace),
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert [step["status"] for step in steps] == ["COMPLETED"]
    assert [step["title"] for step in steps] == ["보고서 작성"]
    assert all(step["input_payload"].get("progress_fallback_step") is None for step in steps)

    events = client.app.state.repository.list_events(body["task_run_id"])
    probe_started = next(
        event
        for event in events
        if event.event_type == "tool.started" and event.payload.get("tool_name") == "write_file"
    )
    step_created = next(event for event in events if event.event_type == "step.created")
    task_completed = next(event for event in events if event.event_type == "task.completed")
    assert probe_started.step_run_id == steps[0]["step_run_id"]
    assert events.index(step_created) < events.index(probe_started)
    assert events.index(probe_started) < events.index(task_completed)


def test_agent_loop_does_not_create_steprun_before_first_provider_call(client, monkeypatch):
    observed_step_counts: list[int] = []

    def fake_respond(self, messages, tools, model, tool_choice=None, runtime_context=None):
        _ = (self, messages, tools, model, tool_choice)
        tasks = client.app.state.repository.list_tasks(limit=10)
        assert len(tasks) == 1
        observed_step_counts.append(len(client.app.state.repository.list_steps(tasks[0].task_run_id)))
        return _response(text="FIRST_PROVIDER_DONE")

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

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "first-provider-user",
            "input_payload": {
                "prompt": "관련 자료를 조사하고 파일 초안을 작성해줘.",
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert observed_step_counts == [1]

    events = client.app.state.repository.list_events(body["task_run_id"])
    event_types = [event.event_type for event in events]
    assert "step.created" in event_types
    assert len(client.app.state.repository.list_steps(body["task_run_id"])) == 1


def test_agent_loop_uses_native_async_provider_without_thread_fallback(client, monkeypatch):
    to_thread_calls: list[str] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        to_thread_calls.append(getattr(func, "__name__", repr(func)))
        return func(*args, **kwargs)

    monkeypatch.setattr("app.domain.orchestration.agent.tool_calling_loop.asyncio.to_thread", fake_to_thread)
    _patch_respond(monkeypatch, [_response(text="ASYNC_PROVIDER_DONE")])

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "provider-thread-user",
            "input_payload": {
                "prompt": "provider 호출 thread 경계 확인",
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert to_thread_calls == []


def test_step_events_use_model_progress_title_as_realtime_summary(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(
                progress_update={
                    "title": "이승엽 기록 근거 확인",
                    "summary": "이승엽 기록 근거 확인 중",
                },
                tool_calls=[
                    _tool_call("call_todo", "todo", {"todos": [{"id": "check", "content": "근거 확인", "status": "in_progress"}]})
                ]
            ),
            _response(text="STEP_DECLARED_DONE"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "step-summary-user",
            "input_payload": {
                "prompt": "관련 자료를 조사하고 파일 초안을 작성해줘.",
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    events = client.app.state.repository.list_events(body["task_run_id"])
    step_created = [event for event in events if event.event_type == "step.created"]
    step_started = [event for event in events if event.event_type == "step.started"]
    event_types = [event.event_type for event in events]

    assert [event.summary_message for event in step_created] == ["agent loop 실행 중"]
    step_updated = next(event for event in events if event.event_type == "step.updated" and event.payload.get("reason") == "model.progress")
    assert step_updated.summary_message == "이승엽 기록 근거 확인 중"
    assert event_types.index("step.created") < event_types.index("step.updated")
    assert event_types.index("step.updated") < event_types.index("tool.started")
    assert event_types.index("tool.completed") < event_types.index("step.completed")
    tool_events = [event for event in events if event.event_type.startswith("tool.")]
    assert all(event.step_run_id == body["current_step_run_id"] for event in tool_events)


def test_agent_loop_model_progress_updates_single_runtime_steprun(client, monkeypatch):
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(
                progress_update={
                    "title": "뉴스 브리핑 결과 검토",
                    "summary": "뉴스 브리핑 결과 검토 중",
                },
                tool_calls=[
                    _tool_call("call_todo", "todo", {"todos": [{"id": "review", "content": "브리핑 결과 검토", "status": "in_progress"}]})
                ]
            ),
            _response(text="DECLARED_STEPS_DONE"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "declared-step-user",
            "input_payload": {"prompt": "진행 단계를 선언하면서 처리해줘.", "model": "gpt-test"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["progress_summary"] == "DECLARED_STEPS_DONE"

    exposed_tool_names = [tool["function"]["name"] for tool in provider_calls[0]["tools"]]
    assert "step" not in exposed_tool_names

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert len(steps) == 1
    assert steps[0]["title"] == "뉴스 브리핑 결과 검토"
    assert steps[0]["summary_message"] == "DECLARED_STEPS_DONE"
    assert steps[0]["semantic"]["key"] == "agent.loop"
    assert all(step["input_payload"].get("todo_key") is None for step in steps)
    assert all(step["status"] == "COMPLETED" for step in steps)


def test_agent_loop_updates_same_runtime_steprun_when_model_progress_changes(client, monkeypatch, tmp_path):
    workspace = tmp_path / "declared-progress-workspace"
    workspace.mkdir()
    _patch_respond(
        monkeypatch,
        [
            _response(
                progress_update={
                    "title": "이승엽 기록 근거 조사",
                    "summary": "이승엽 기록 근거 조사 중",
                },
                tool_calls=[
                    _tool_call(
                        "call_todo_research",
                        "todo",
                        {
                            "todos": [
                                {
                                    "content": "이승엽 관련 공식 기록 확인",
                                    "status": "in_progress",
                                }
                            ]
                        },
                    ),
                ]
            ),
            _response(
                progress_update={
                    "title": "이승엽 조사 문서 작성",
                    "summary": "이승엽 조사 문서 작성 중",
                },
                tool_calls=[
                    _tool_call(
                        "call_write_file",
                        "write_file",
                        {
                            "path": "tmp/testfile/lee.md",
                            "content": "# 이승엽\n",
                        },
                    ),
                ]
            ),
            _response(text="작성 완료"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "declared-progress-user",
            "input_payload": {
                "prompt": "이승엽 정보를 조사하고 tmp/testfile/lee.md 파일로 작성해줘.",
                "workspace_root": str(workspace),
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert [step["title"] for step in steps] == ["이승엽 조사 문서 작성"]
    assert all(step["status"] == "COMPLETED" for step in steps)
    assert body["current_step_run_id"] == steps[0]["step_run_id"]
    assert (workspace / "tmp/testfile/lee.md").read_text(encoding="utf-8") == "# 이승엽\n"

    events = client.app.state.repository.list_events(body["task_run_id"])
    step_created_events = [event for event in events if event.event_type == "step.created"]
    step_started_events = [event for event in events if event.event_type == "step.started"]
    todo_started_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "tool.started" and event.payload.get("tool_name") == "todo"
    )
    write_started_index = next(
        index
        for index, event in enumerate(events)
        if event.event_type == "tool.started" and event.payload.get("tool_name") == "write_file"
    )
    assert [event.payload["step_title"] for event in step_created_events] == ["agent loop 실행"]
    assert [event.payload["step_title"] for event in step_started_events] == ["agent loop 실행"]
    assert todo_started_index < write_started_index

    write_events = [
        event
        for event in events
        if event.event_type.startswith("tool.") and event.payload.get("tool_name") == "write_file"
    ]
    assert write_events
    assert all(event.step_run_id == steps[0]["step_run_id"] for event in write_events)
    assert write_events[0].payload["input"]["path"] == "tmp/testfile/lee.md"
    assert write_events[-1].payload["result"]["path"] == "tmp/testfile/lee.md"
    assert len({event.step_run_id for event in events if event.event_type == "step.completed"}) == 1


def test_agent_loop_keeps_tool_on_current_runtime_steprun_after_model_progress(client, monkeypatch, tmp_path):
    workspace = tmp_path / "pending-tool-workspace"
    workspace.mkdir()
    _patch_respond(
        monkeypatch,
        [
            _response(
                progress_update={
                    "title": "이승엽 자료 조사",
                    "summary": "이승엽 주요 이력 조사 중",
                },
                tool_calls=[
                    _tool_call(
                        "call_write_file",
                        "write_file",
                        {
                            "path": "tmp/testfile/lee-pending.md",
                            "content": "# 이승엽\n",
                        },
                    ),
                ]
            ),
            _response(text="작성 완료"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "pending-tool-user",
            "input_payload": {
                "prompt": "이승엽에 대하여 조사하고 tmp/testfile 여기에 md 파일로 저장해줘.",
                "workspace_root": str(workspace),
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert [step["title"] for step in steps] == ["이승엽 자료 조사"]
    assert [step["status"] for step in steps] == ["COMPLETED"]
    assert (workspace / "tmp/testfile/lee-pending.md").read_text(encoding="utf-8") == "# 이승엽\n"

    events = client.app.state.repository.list_events(body["task_run_id"])
    write_tool_started = next(
        event
        for event in events
        if event.event_type == "tool.started" and event.payload.get("tool_name") == "write_file"
    )

    assert write_tool_started.step_run_id == steps[0]["step_run_id"]
    assert [
        event.step_run_id
        for event in events
        if event.event_type == "step.completed"
    ] == [steps[0]["step_run_id"]]


def test_agent_loop_keeps_delegate_step_running_until_worker_result_before_file_write(client, monkeypatch, tmp_path):
    workspace = tmp_path / "delegate-order-workspace"
    workspace.mkdir()

    async def fake_worker_start(**kwargs):
        return ChildSessionLaunchResult(
            agent_id="agent_web_research",
            status=TaskStatus.COMPLETED,
            summary="웹 자료 조사, 실무 운영 관점, 아키텍처 관점, 사용자 경험 관점 검토 완료",
            output_payload={
                "tool_results": [
                    {"tool_call_id": "worker_http", "name": "http_get", "result": {"ok": True}},
                ]
            },
        )

    client.app.state.child_session_launcher.bind_worker_start(fake_worker_start)
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(
                progress_update={
                    "title": "AI 서브에이전트 depth1 설계 관점별 조사",
                    "summary": "worker 서브에이전트로 관점별 조사를 진행한다.",
                },
                tool_calls=[
                    _tool_call(
                        "call_delegate",
                        "delegate_task",
                        {
                            "goal": "AI 서브에이전트 depth1 설계 관점별 조사",
                            "context": "웹 자료, 실무 운영, 아키텍처, 사용자 경험 관점을 분리해 검토한다.",
                            "toolsets": ["web", "file"],
                            "max_iterations": 5,
                        },
                    ),
                    _tool_call(
                        "call_write_too_early",
                        "write_file",
                        {
                            "path": "tmp/testfile/depth1/report.md",
                            "content": "# premature\n",
                        },
                    ),
                ]
            ),
            _response(
                progress_update={
                    "title": "종합 보고서와 관점별 md 파일 작성",
                    "summary": "조사 결과를 파일로 저장한다.",
                },
                tool_calls=[
                    _tool_call(
                        "call_write_after_worker",
                        "write_file",
                        {
                            "path": "tmp/testfile/depth1/report.md",
                            "content": "# AI 서브에이전트 depth1 설계\n\nworker 조사 완료 후 작성\n",
                        },
                    )
                ]
            ),
            _response(text="보고서 저장 완료"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "delegate-order-user",
            "input_payload": {
                "prompt": "AI 서브에이전트를 depth1로만 두는 설계를 조사하고 tmp/testfile 아래에 md로 정리해줘.",
                "workspace_root": str(workspace),
                "enabled_toolsets": ["local-core", "delegation", "file", "web"],
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["displayContext"]["taskRunId"] == body["task_run_id"]
    assert body["displayContext"]["assigneeAgent"]["kind"] == "main"
    assert (workspace / "tmp/testfile/depth1/report.md").read_text(encoding="utf-8").startswith("# AI 서브에이전트 depth1 설계")

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert [step["title"] for step in steps] == ["종합 보고서와 관점별 md 파일 작성"]
    research_step = steps[0]
    write_step = steps[0]
    assert research_step["detail_json"]["agentDetail"]["workerSessionId"] is not None
    assert research_step["detail_json"]["agentDetail"]["workers"][0]["status"] == TaskStatus.COMPLETED
    assert research_step["displayContext"]["stepRunId"] == research_step["step_run_id"]
    assert research_step["displayContext"]["actorAgent"]["kind"] == "worker"
    assert research_step["displayContext"]["delegatedAgents"][0]["agentSessionId"] == research_step["detail_json"]["agentDetail"]["workerSessionId"]

    events = client.app.state.repository.list_events(body["task_run_id"])
    delegate_update = next(
        event
        for event in events
        if event.event_type == "step.updated"
        and event.step_run_id == research_step["step_run_id"]
        and event.payload.get("reason") == "delegate.started"
    )
    write_tool_started = next(
        event
        for event in events
        if event.event_type == "tool.started" and event.payload.get("tool_call_id") == "call_write_after_worker"
    )
    assert events.index(delegate_update) < events.index(write_tool_started)
    assert write_tool_started.step_run_id == write_step["step_run_id"]
    assert write_tool_started.payload["displayContext"]["taskRunId"] == body["task_run_id"]
    assert write_tool_started.payload["displayContext"]["stepRunId"] == write_step["step_run_id"]

    first_turn_tool_messages = [
        message for message in provider_calls[1]["messages"]
        if getattr(message, "tool_call_id", None) in {"call_delegate", "call_write_too_early"}
    ]
    assert "관점 검토 완료" in first_turn_tool_messages[0].content
    assert "이번 turn에서 실행하지 않았습니다" in first_turn_tool_messages[1].content


def test_agent_loop_provider_timeout_fails_task_without_fallback_step(client, monkeypatch):
    _patch_respond(monkeypatch, [TimeoutError("provider read timeout")])

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "timeout-user",
            "input_payload": {"prompt": "provider timeout을 실패로 저장해줘.", "model": "gpt-test"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "FAILED"
    assert body["error_message"] == "TimeoutError: provider read timeout"
    assert body["progress_summary"] == "TimeoutError: provider read timeout"
    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert len(steps) == 1
    assert body["current_step_run_id"] == steps[0]["step_run_id"]
    assert steps[0]["status"] == "FAILED"

    events = client.app.state.repository.list_events(body["task_run_id"])
    task_failed_event = next(event for event in events if event.event_type == "task.failed")
    assert task_failed_event.step_run_id == steps[0]["step_run_id"]
    assert task_failed_event.payload["error_message"] == "TimeoutError: provider read timeout"


def test_agent_loop_explicit_task_plan_is_reference_only_for_runtime_steprun(client, monkeypatch):
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(text="PLAN_REFERENCE_DONE"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "explicit-plan-user",
            "input_payload": {
                "prompt": "명시 계획을 순서대로 처리해줘.",
                "task_plan": {
                    "title": "명시 계획 실행",
                    "steps": [
                        {"key": "analyze", "title": "요청 분석", "goal": "요청을 분석한다."},
                        {"key": "write", "title": "초안 작성", "goal": "초안을 작성한다."},
                        {"key": "share", "title": "결과 공유", "goal": "결과를 공유한다."},
                    ],
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["result_payload"]["text"] == "PLAN_REFERENCE_DONE"
    assert len(provider_calls) == 1

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert len(steps) == 1

    events = client.app.state.repository.list_events(body["task_run_id"])
    assert [event.event_type for event in events if event.event_type == "step.created"] == ["step.created"]

def test_agent_loop_does_not_inject_prompt_plan_from_keywords(client, monkeypatch):
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(text="KEYWORD_PROMPT_DONE"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "prompt-plan-user",
            "input_payload": {
                "prompt": "관련 자료를 조사하고 파일 초안을 작성해줘.",
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["result_payload"]["text"] == "KEYWORD_PROMPT_DONE"
    assert len(provider_calls) == 1
    saved_task = client.app.state.repository.get_task(body["task_run_id"])
    assert "task_plan" not in saved_task.input_payload
    assert "task_plan_source" not in saved_task.input_payload

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert len(steps) == 1


def test_agent_loop_todo_does_not_force_prompt_plan_step_boundary(client, monkeypatch):
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(
                tool_calls=[
                    _tool_call(
                        "call_todo",
                        "todo",
                        {
                            "todos": [
                                {"id": "write", "content": "초안 작성", "status": "completed"},
                            ]
                        },
                    )
                ]
            ),
            _response(text="TODO_DONE"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "prompt-plan-todo-user",
            "input_payload": {
                "prompt": "관련 자료를 조사하고 파일 초안을 작성해줘.",
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["result_payload"]["text"] == "TODO_DONE"
    assert len(provider_calls) == 2

    steps = client.get(f"/ai/api/v1/taskRuns/{body['task_run_id']}/steps").json()
    assert len(steps) == 1
    events = client.app.state.repository.list_events(body["task_run_id"])
    assert [event.event_type for event in events if event.event_type == "step.completed"] == ["step.completed"]


def test_agent_loop_uses_input_workspace_root_for_file_and_terminal_runtime(client, monkeypatch, tmp_path):
    workspace = tmp_path / "request-workspace"
    workspace.mkdir()
    file_name = f"request-root-{tmp_path.name}.txt"
    requested_file = workspace / "drafts" / file_name
    server_cwd_file = Path.cwd() / "drafts" / file_name
    server_cwd_terminal_marker = Path.cwd() / "terminal-marker.txt"
    if server_cwd_file.exists():
        server_cwd_file.unlink()
    if server_cwd_terminal_marker.exists():
        server_cwd_terminal_marker.unlink()
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(
                tool_calls=[
                    _tool_call(
                        "call_write",
                        "write_file",
                        {
                            "workspace_root": str(Path.cwd()),
                            "path": f"drafts/{file_name}",
                            "content": "request workspace file\n",
                        },
                    ),
                    _tool_call(
                        "call_terminal",
                        "terminal_run",
                        {"argv": [sys.executable, "-c", "import pathlib; pathlib.Path('terminal-marker.txt').write_text('ok')"]},
                    ),
                ]
            ),
            _response(text="WORKSPACE_ROOT_DONE"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "workspace-root-user",
            "input_payload": {
                "prompt": "요청 workspace에서 파일과 터미널 작업을 실행해줘.",
                "workspace_root": str(workspace),
                "enabled_toolsets": ["file", "terminal"],
            },
        },
    )
    server_cwd_created = server_cwd_file.exists()
    if server_cwd_created:
        server_cwd_file.unlink()
    server_cwd_terminal_created = server_cwd_terminal_marker.exists()
    if server_cwd_terminal_created:
        server_cwd_terminal_marker.unlink()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert requested_file.read_text(encoding="utf-8") == "request workspace file\n"
    assert (workspace / "terminal-marker.txt").read_text(encoding="utf-8") == "ok"
    assert server_cwd_created is False
    assert server_cwd_terminal_created is False
    assert len(provider_calls) == 2


def test_agent_loop_does_not_fail_file_prompt_with_static_intent_check(client, monkeypatch, tmp_path):
    workspace = tmp_path / "missing-file-write-workspace"
    workspace.mkdir()
    _patch_respond(monkeypatch, [_response(text="파일 작성 완료")])

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "missing-file-write-user",
            "input_payload": {
                "prompt": "이승엽 조사 보고서를 tmp/testfile/missing.md 파일로 작성해줘.",
                "workspace_root": str(workspace),
                "model": "gpt-test",
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    assert body["error_message"] is None
    assert not (workspace / "tmp/testfile/missing.md").exists()
    assert body["result_payload"]["tool_results"] == []


def test_agent_loop_waits_for_approval_and_resumes_same_step(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_terminal", "terminal_run", {"argv": [sys.executable, "-c", "print('WAIT_OK')"]})]),
            _response(tool_calls=[_tool_call("call_followup", "terminal_run", {"argv": [sys.executable, "-c", "print('FOLLOWUP_OK')"]})]),
            _response(text="APPROVED_DONE"),
        ],
    )

    create_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "approval-user",
            "input_payload": {
                "prompt": "승인 후 터미널 확인을 진행해줘.",
                "approval_required": True,
                "approval_reason": "터미널 실행 전 승인 필요",
            },
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "WAITING"
    assert created["wait_payload"]["pending_tool_call_id"] == "call_terminal"
    assert created["wait_payload"]["pending_tool_name"] == "terminal.run"
    assert created["current_step_run_id"]

    events = client.get(f"/ai/api/v1/taskRuns/{created['task_run_id']}/events").json()
    approval_id = next(event["payload"]["approval_id"] for event in events if event["event_type"] == "approval.requested")
    waiting_step_id = created["current_step_run_id"]

    resume_response = client.post(
        f"/ai/api/v1/taskRuns/{created['task_run_id']}/resume",
        json={"approval_id": approval_id, "payload": {"approved": True}},
    )

    assert resume_response.status_code == 200
    resumed = resume_response.json()
    assert resumed["status"] == "COMPLETED"
    assert resumed["current_step_run_id"] == waiting_step_id
    assert resumed["result_payload"]["text"] == "APPROVED_DONE"
    assert [item["tool_call_id"] for item in resumed["result_payload"]["tool_results"]] == ["call_terminal", "call_followup"]

    resumed_events = client.get(f"/ai/api/v1/taskRuns/{created['task_run_id']}/events").json()
    assert [event["event_type"] for event in resumed_events].count("approval.requested") == 1


def test_agent_loop_resume_provider_runtime_error_fails_existing_step(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_terminal", "terminal_run", {"argv": [sys.executable, "-c", "print('WAIT')"]})]),
            RuntimeError("provider unavailable"),
        ],
    )

    create_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "resume-error-user",
            "input_payload": {
                "prompt": "승인 후 provider 오류를 실패로 저장해줘.",
                "approval_required": True,
            },
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "WAITING"
    waiting_step_id = created["current_step_run_id"]

    events = client.get(f"/ai/api/v1/taskRuns/{created['task_run_id']}/events").json()
    approval_id = next(event["payload"]["approval_id"] for event in events if event["event_type"] == "approval.requested")

    resume_response = client.post(
        f"/ai/api/v1/taskRuns/{created['task_run_id']}/resume",
        json={"approval_id": approval_id, "payload": {"approved": True}},
    )

    assert resume_response.status_code == 200
    resumed = resume_response.json()
    assert resumed["status"] == "FAILED"
    assert resumed["current_step_run_id"] == waiting_step_id
    assert resumed["error_message"] == "RuntimeError: provider unavailable"

    steps = client.get(f"/ai/api/v1/taskRuns/{created['task_run_id']}/steps").json()
    assert len(steps) == 1
    assert steps[0]["step_run_id"] == waiting_step_id
    assert steps[0]["status"] == "FAILED"
    assert steps[0]["error_message"] == "RuntimeError: provider unavailable"
    operations = steps[0]["detail_json"]["operationDetail"]["operations"]
    assert operations[-3]["key"] == "handler.diagnose"
    assert operations[-2]["key"] == "handler.retry.unavailable"
    assert operations[-1]["key"] == "handler.failure"
    approval_detail = steps[0]["detail_json"]["approvalDetail"]
    assert approval_detail["approvalRequested"] is False
    assert approval_detail["approvalId"] == approval_id
    assert approval_detail["response"] == {"approved": True}


def test_taskruns_resume_rejects_missing_approval_id_for_waiting_task(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_terminal", "terminal_run", {"argv": [sys.executable, "-c", "print('WAIT')"]})]),
            _response(text="SHOULD_NOT_RESUME"),
        ],
    )

    create_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "approval-missing-user",
            "input_payload": {"prompt": "승인 대기", "approval_required": True},
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "WAITING"

    resume_response = client.post(
        f"/ai/api/v1/taskRuns/{created['task_run_id']}/resume",
        json={"payload": {"approved": True}},
    )

    assert resume_response.status_code == 409
    assert "approval id is required" in resume_response.json()["detail"]
    assert client.get(f"/ai/api/v1/taskRuns/{created['task_run_id']}").json()["status"] == "WAITING"


def test_taskruns_resume_rejects_approval_id_from_other_waiting_task(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_task_a", "terminal_run", {"argv": [sys.executable, "-c", "print('A')"]})]),
            _response(tool_calls=[_tool_call("call_task_b", "terminal_run", {"argv": [sys.executable, "-c", "print('B')"]})]),
            _response(text="SHOULD_NOT_RESUME"),
        ],
    )

    task_a_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "approval-a",
            "input_payload": {"prompt": "A 작업", "approval_required": True},
        },
    )
    task_b_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "approval-b",
            "input_payload": {"prompt": "B 작업", "approval_required": True},
        },
    )
    assert task_a_response.status_code == 200
    assert task_b_response.status_code == 200
    task_a = task_a_response.json()
    task_b = task_b_response.json()

    task_b_events = client.get(f"/ai/api/v1/taskRuns/{task_b['task_run_id']}/events").json()
    task_b_approval_id = next(event["payload"]["approval_id"] for event in task_b_events if event["event_type"] == "approval.requested")

    resume_response = client.post(
        f"/ai/api/v1/taskRuns/{task_a['task_run_id']}/resume",
        json={"approval_id": task_b_approval_id, "payload": {"approved": True}},
    )

    assert resume_response.status_code == 409
    assert "does not match open approval" in resume_response.json()["detail"]
    assert client.get(f"/ai/api/v1/taskRuns/{task_a['task_run_id']}").json()["status"] == "WAITING"


def test_taskruns_cancel_records_pending_tool_result_without_resuming_loop(client, monkeypatch):
    provider_calls = _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_cancel", "terminal_run", {"argv": [sys.executable, "-c", "print('CANCEL')"]})]),
        ],
    )

    create_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "cancel-user",
            "session_key": "sess_cancel_pending",
            "input_payload": {
                "prompt": "취소될 도구 실행",
                "approval_required": True,
                "approval_reason": "터미널 실행 전 승인 필요",
            },
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "WAITING"

    cancel_response = client.post(f"/ai/api/v1/taskRuns/{created['task_run_id']}/cancel")

    assert cancel_response.status_code == 200
    canceled = cancel_response.json()
    assert canceled["status"] == "CANCELED"
    assert len(provider_calls) == 1

    steps = client.get(f"/ai/api/v1/taskRuns/{created['task_run_id']}/steps").json()
    step = next(item for item in steps if item["step_run_id"] == created["current_step_run_id"])
    tool_results = step["output_payload"]["tool_results"]
    canceled_tool = next(item for item in tool_results if item["tool_call_id"] == "call_cancel")
    assert canceled_tool["name"] == "terminal.run"
    assert canceled_tool["result"]["ok"] is False
    assert canceled_tool["result"]["error"]["code"] == "tool_canceled"

    transcript_session = client.app.state.session_store.get_latest_session_by_key("sess_cancel_pending")
    transcript = client.app.state.session_store.list_messages(transcript_session["id"])
    tool_messages = [message for message in transcript if message["role"] == "tool"]
    canceled_tool_message = next(message for message in tool_messages if message["tool_call_id"] == "call_cancel")
    assert canceled_tool_message["tool_name"] == "terminal.run"


def test_taskruns_resume_and_cancel_reject_non_waiting_task(client, monkeypatch):
    _patch_respond(monkeypatch, [_response(text="NON_WAITING_DONE")])

    create_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "non-waiting-user",
            "input_payload": {"prompt": "바로 완료되는 작업"},
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "COMPLETED"

    resume_response = client.post(f"/ai/api/v1/taskRuns/{created['task_run_id']}/resume", json={"payload": {"approved": True}})
    assert resume_response.status_code == 409
    assert resume_response.json()["detail"] == "task is not waiting"

    cancel_response = client.post(f"/ai/api/v1/taskRuns/{created['task_run_id']}/cancel")
    assert cancel_response.status_code == 409
    assert cancel_response.json()["detail"] == "task is not waiting"


def test_removed_request_route_field_is_rejected(client):
    legacy_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "removed_route": "model.generate",
            "owner_key": "legacy-user",
            "input_payload": {"prompt": "legacy"},
        },
    )
    assert legacy_response.status_code == 422

    workflow_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "workflow-user",
            "input_payload": {"prompt": "workflow", "workflow_hint": "legacy.workflow"},
        },
    )
    assert workflow_response.status_code == 200


def test_runtime_tool_error_is_model_observation_not_immediate_task_failure(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_terminal", "terminal.run", {"argv": [sys.executable, "-c", "print('BLOCKED')"]})]),
            _response(text="BLOCKED_TOOL_REPORTED"),
        ],
    )

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "restricted-tools-user",
            "input_payload": {
                "prompt": "terminal tool should be reported as unavailable here.",
                "enabled_toolsets": ["skills"],
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "COMPLETED"
    tool_result = body["result_payload"]["tool_results"][0]["result"]
    assert tool_result["ok"] is False
    assert tool_result["error"]["code"] == "tool_unavailable"


def test_taskruns_active_supports_session_filter_and_recent_terminal(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(text="DONE"),
            _response(tool_calls=[_tool_call("call_terminal", "terminal.run", {"argv": [sys.executable, "-c", "print('WAIT')"]})]),
            _response(tool_calls=[_tool_call("call_terminal", "terminal.run", {"argv": [sys.executable, "-c", "print('WAIT')"]})]),
        ],
    )

    completed_response = client.post(
        "/ai/api/v1/taskRuns",
        json={"owner_key": "completed-user", "input_payload": {"prompt": "완료 작업"}},
    )
    assert completed_response.status_code == 200
    completed_task = completed_response.json()

    waiting_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "waiting-user",
            "session_key": "sess_a",
            "input_payload": {"prompt": "대기 작업", "approval_required": True},
        },
    )
    assert waiting_response.status_code == 200
    waiting_task = waiting_response.json()
    assert waiting_task["status"] == "WAITING"

    active_response = client.get("/ai/api/v1/taskRuns/active", params={"sessionId": "sess_a"})
    assert active_response.status_code == 200
    active_body = active_response.json()
    assert active_body["total_count"] == 1
    assert active_body["items"][0]["task_run_id"] == waiting_task["task_run_id"]
    assert active_body["items"][0]["pendingApproval"]["approval_id"]
    assert active_body["items"][0]["pendingApproval"]["step_run_id"] == waiting_task["current_step_run_id"]
    assert active_body["items"][0]["pendingApproval"]["status"] == "PENDING"
    assert active_body["items"][0]["pendingApproval"]["reason"]
    assert active_body["items"][0]["pendingApproval"]["tool_call_id"] == "call_terminal"
    assert active_body["items"][0]["pendingApproval"]["tool_name"] == "terminal.run"
    assert active_body["items"][0]["pendingApproval"]["requested_at"]
    assert active_body["items"][0]["pendingApproval"]["can_approve"] is True
    assert active_body["items"][0]["pendingApproval"]["can_reject"] is True

    completed_at = datetime.fromisoformat(completed_task["updated_at"])
    monkeypatch.setattr("app.api.http.tasks.utc_now", lambda: completed_at + timedelta(seconds=301))
    expired_active = client.get("/ai/api/v1/taskRuns/active", params={"sessionId": "missing"})
    assert expired_active.status_code == 200
    assert expired_active.json()["items"] == []


def test_taskruns_active_filters_by_session_id(client):
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_session_match",
            task_type="agent.loop",
            owner_key="session-user",
            session_key="target_session",
            status="RUNNING",
            title="sessionId 작업",
        )
    )
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_other_session",
            task_type="agent.loop",
            owner_key="other-user",
            session_key="other_session",
            status="RUNNING",
            title="다른 세션 작업",
        )
    )

    response = client.get(
        "/ai/api/v1/taskRuns/active",
        params={"sessionId": "target_session"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["task_run_id"] == "task_session_match"
    assert body["items"][0]["session_key"] == "target_session"


def test_taskruns_rejects_removed_session_aliases(client):
    create_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "alias-user",
            "sessionKey": "legacy_create_session",
            "productSessionId": "removed_create_session",
            "input_payload": {"prompt": "옛 세션 alias는 거절한다.", "model": "gpt-test"},
        },
    )
    active_response = client.get(
        "/ai/api/v1/taskRuns/active",
        params={"sessionKey": "legacy_session", "productSessionId": "removed_session"},
    )

    assert create_response.status_code == 422
    assert active_response.status_code == 422


def test_public_session_message_creates_taskrun_and_stores_public_transcript(client, monkeypatch):
    _patch_respond(monkeypatch, [_response(text="PUBLIC_SESSION_DONE")])

    message_response = client.post(
        "/ai/api/v1/sessions/messages",
        json={"content": "공개 세션 메시지를 처리해줘.", "model": "gpt-test"},
    )

    assert message_response.status_code == 200
    body = message_response.json()
    session_id = body["sessionId"]
    assert body["sessionId"] == session_id
    assert body["status"] == "COMPLETED"
    assert body["taskRunId"].startswith("task_")
    assert body["assistantMessage"]["content"] == "PUBLIC_SESSION_DONE"
    assert body["assistantMessage"]["taskRunId"] == body["taskRunId"]
    assert body["userMessage"]["role"] == "user"

    messages = client.get(f"/ai/api/v1/sessions/{session_id}/messages").json()
    assert [message["role"] for message in messages["items"]] == ["user", "assistant"]
    assert [message["content"] for message in messages["items"]] == ["공개 세션 메시지를 처리해줘.", "PUBLIC_SESSION_DONE"]

    task = client.get(f"/ai/api/v1/taskRuns/{body['taskRunId']}").json()
    assert task["session_key"] == session_id


def test_public_session_message_enables_team_lead_awesome_design_skill(client, monkeypatch):
    _patch_respond(monkeypatch, [_response(text="DESIGN_SKILL_READY")])

    message_response = client.post(
        "/ai/api/v1/sessions/messages",
        json={"content": "AI 고객지원 SaaS 대시보드 만들어줘", "model": "gpt-test"},
    )

    assert message_response.status_code == 200
    task_run_id = message_response.json()["taskRunId"]
    task = client.app.state.repository.get_task(task_run_id)

    assert task is not None
    assert "awesome-design" in task.input_payload["enabledSkillNames"]
    assert "design" in task.input_payload["enabled_toolsets"]
    assert "design" in task.input_payload["capability_resolution"]["skillRequiredToolsets"]


def test_http_followup_message_uses_previous_public_messages_without_current_user(client, monkeypatch):
    provider_calls = _patch_respond(monkeypatch, [_response(text="HTTP_FOLLOWUP_DONE")])
    session_store = client.app.state.session_store
    session_store.create_session(
        session_id="http_followup_session",
        session_key="http_followup_session",
        source="api.session",
        user_id="local-user",
        title="후속 메시지",
        metadata={"source": "api.session"},
    )
    session_store.append_message(
        session_id="http_followup_session",
        role="user",
        content="강남역에서 지갑 잃어버렸어",
        metadata={"source": "api.session"},
    )
    session_store.append_message(
        session_id="http_followup_session",
        role="assistant",
        content="공식 조회 경로를 확인했습니다.",
        metadata={"source": "api.session"},
    )

    response = client.post(
        "/ai/api/v1/sessions/http_followup_session/messages",
        json={"content": "ㄴㄴ 분실물찾은거", "model": "gpt-test"},
    )

    assert response.status_code == 200
    body = response.json()
    task = client.app.state.repository.get_task(body["taskRunId"])
    assert task is not None
    assert task.input_payload["conversation_history"] == [
        {"role": "user", "content": "강남역에서 지갑 잃어버렸어"},
        {"role": "assistant", "content": "공식 조회 경로를 확인했습니다."},
    ]
    assert "ㄴㄴ 분실물찾은거" not in str(task.input_payload["conversation_history"])
    assert [message.role for message in provider_calls[0]["messages"][:2]] == ["user", "assistant"]


def test_http_session_message_reuses_client_message_id_without_duplicate_user_append(client, monkeypatch):
    _patch_respond(monkeypatch, [_response(text="HTTP_IDEMPOTENT_DONE")])
    session_store = client.app.state.session_store
    session_store.create_session(
        session_id="http_idempotent_session",
        session_key="http_idempotent_session",
        source="api.session",
        user_id="local-user",
        title="중복 방지",
        metadata={"source": "api.session"},
    )

    first = client.post(
        "/ai/api/v1/sessions/http_idempotent_session/messages",
        json={
            "content": "같은 HTTP 메시지",
            "clientMessageId": "client_http_idempotent",
            "model": "gpt-test",
        },
    )
    second = client.post(
        "/ai/api/v1/sessions/http_idempotent_session/messages",
        json={
            "content": "같은 HTTP 메시지",
            "clientMessageId": "client_http_idempotent",
            "model": "gpt-test",
        },
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["taskRunId"] == second.json()["taskRunId"]
    messages = session_store.list_messages("http_idempotent_session")
    assert [message["role"] for message in messages] == ["user", "assistant"]


def test_http_session_message_clears_stale_running_guard_before_append(client, monkeypatch):
    _patch_respond(monkeypatch, [_response(text="HTTP_STALE_DONE")])
    session_store = client.app.state.session_store
    session_store.create_session(
        session_id="http_stale_guard_session",
        session_key="http_stale_guard_session",
        source="api.session",
        user_id="local-user",
        title="stale guard",
        metadata={"source": "api.session"},
    )
    session_store.append_user_message_and_start_task(
        owner_key="local-user",
        session_id="http_stale_guard_session",
        content="이전 실행 입력",
        client_message_id="client_http_stale_old",
        task_run_id="task_http_stale_terminal",
        base_history_version=0,
    )
    client.app.state.repository.create_task(
        TaskRun(
            task_run_id="task_http_stale_terminal",
            task_type="agent.loop",
            owner_key="local-user",
            session_key="http_stale_guard_session",
            status="FAILED",
            title="끝난 실행",
        )
    )

    response = client.post(
        "/ai/api/v1/sessions/http_stale_guard_session/messages",
        json={"content": "새 입력은 막히면 안 된다", "model": "gpt-test"},
    )

    assert response.status_code == 200
    assert response.json()["assistantMessage"]["content"] == "HTTP_STALE_DONE"
    assert session_store.get_session("http_stale_guard_session")["running_task_run_id"] is None


def test_public_session_message_rejects_new_session_over_limit(client, monkeypatch):
    _patch_respond(monkeypatch, [_response(text="LIMIT_TEST")])
    client.app.state.settings.public_session_limit_per_user = 1
    session_store = client.app.state.session_store
    session_store.create_session(
        session_id="existing_public_session",
        session_key="existing_public_session",
        source="api.session",
        user_id="local-user",
        title="이미 있는 세션",
    )

    response = client.post(
        "/ai/api/v1/sessions/messages",
        json={"content": "새 세션을 하나 더 만들려고 한다.", "model": "gpt-test"},
    )

    assert response.status_code == 409
    assert "public session limit exceeded" in response.json()["detail"]


def test_public_sessions_list_and_get_only_public_sessions(client):
    session_store = client.app.state.session_store
    session_store.create_session(
        session_id="public_session_visible",
        session_key="public_session_visible",
        source="api.session",
        user_id="local-user",
        title="보이는 세션",
    )
    session_store.create_session(
        session_id="agent_session_hidden",
        session_key="public_session_visible",
        source="agent.loop",
        user_id="local-user",
        title="숨겨진 내부 세션",
    )

    list_response = client.get("/ai/api/v1/sessions")
    detail_response = client.get("/ai/api/v1/sessions/public_session_visible")
    hidden_response = client.get("/ai/api/v1/sessions/agent_session_hidden")

    assert list_response.status_code == 200
    assert [item["sessionId"] for item in list_response.json()["items"]] == ["public_session_visible"]
    assert detail_response.status_code == 200
    assert detail_response.json()["title"] == "보이는 세션"
    assert hidden_response.status_code == 404


def test_agent_session_messages_returns_wrapper_after_numeric_message_id(client):
    session_store = client.app.state.session_store
    session_store.create_session(
        session_id="agent_session_messages_api",
        session_key="session_messages",
        source="agent.loop",
        user_id="messages-user",
        model="gpt-test",
        title="messages API",
    )
    first_id = session_store.append_message(session_id="agent_session_messages_api", role="user", content="첫 메시지")
    second_id = session_store.append_message(session_id="agent_session_messages_api", role="assistant", content="둘째 메시지")
    session_store.append_message(session_id="agent_session_messages_api", role="tool", content="셋째 메시지", tool_name="terminal.run")

    response = client.get(
        "/ai/api/v1/agentSessions/agent_session_messages_api/messages",
        params={"afterMessageId": first_id, "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["agentSessionId"] == "agent_session_messages_api"
    assert body["afterMessageId"] == first_id
    assert body["limit"] == 1
    assert body["totalCount"] == 1
    assert body["nextAfterMessageId"] == second_id
    assert [message["id"] for message in body["items"]] == [second_id]
    assert body["items"][0]["role"] == "assistant"
    assert body["items"][0]["content"] == "둘째 메시지"


def test_agent_session_messages_returns_not_found_for_authenticated_missing_session(client):
    client.app.state.backend_auth_client = FakeBackendAuthClient()

    response = client.get(
        "/ai/api/v1/agentSessions/missing_agent_session/messages",
        headers={"Authorization": "Bearer messages-user"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "agent session not found"


def test_authenticated_http_request_passes_workspace_key_hint_to_backend(client):
    auth_client = FakeBackendAuthClient()
    client.app.state.backend_auth_client = auth_client

    response = client.get(
        "/ai/api/v1/taskRuns/active",
        params={"sessionId": "workspace-hint-session", "workspaceKey": "workspace-a"},
        headers={"Authorization": "Bearer owner-a", "X-Workspace-Key": "workspace-header"},
    )

    assert response.status_code == 200
    assert auth_client.calls == [{"access_token": "owner-a", "workspace_key": "workspace-header"}]


def test_taskruns_create_rejects_second_active_task_in_same_session(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_active_lock", "terminal.run", {"argv": [sys.executable, "-c", "print('WAIT')"]})]),
            _response(text="SHOULD_NOT_START"),
        ],
    )

    first_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "active-lock-user",
            "session_key": "sess_active_lock",
            "input_payload": {"prompt": "첫 작업은 승인 대기", "approval_required": True},
        },
    )
    assert first_response.status_code == 200
    assert first_response.json()["status"] == "WAITING"

    second_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "active-lock-user",
            "session_key": "sess_active_lock",
            "input_payload": {"prompt": "동일 세션 두 번째 작업"},
        },
    )

    assert second_response.status_code == 409
    assert "active task already exists" in second_response.json()["detail"]


def test_taskruns_create_active_lock_is_scoped_by_authenticated_owner(client, monkeypatch):
    client.app.state.backend_auth_client = FakeBackendAuthClient()
    _patch_respond(
        monkeypatch,
        [
            _response(tool_calls=[_tool_call("call_owner_a_wait", "terminal.run", {"argv": [sys.executable, "-c", "print('WAIT')"]})]),
            _response(text="OWNER_B_DONE"),
        ],
    )

    first_response = client.post(
        "/ai/api/v1/taskRuns",
        headers={"Authorization": "Bearer owner-a"},
        json={
            "owner_key": "ignored-owner",
            "session_key": "shared_session",
            "input_payload": {"prompt": "owner-a 작업은 승인 대기", "approval_required": True},
        },
    )
    assert first_response.status_code == 200
    assert first_response.json()["status"] == "WAITING"

    second_response = client.post(
        "/ai/api/v1/taskRuns",
        headers={"Authorization": "Bearer owner-b"},
        json={
            "owner_key": "ignored-owner",
            "session_key": "shared_session",
            "input_payload": {"prompt": "owner-b는 같은 sessionId라도 별도 사용자"},
        },
    )

    assert second_response.status_code == 200
    body = second_response.json()
    assert body["session_key"] == "shared_session"
    assert body["status"] == "COMPLETED"
    assert client.app.state.repository.get_task(body["task_run_id"]).owner_key == "owner-b"


def test_taskruns_create_uses_redis_active_session_lock_before_start(client, monkeypatch):
    _patch_respond(monkeypatch, [_response(text="SHOULD_NOT_START")])
    projection = RedisTaskProjectionStore(FakeRedis(), ttl_seconds=60)
    client.app.state.task_projection_store = projection
    assert projection.acquire_active_session_lock("sess_locked_by_redis", "existing_task", owner_key="active-lock-user") is True

    response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "active-lock-user",
            "session_key": "sess_locked_by_redis",
            "input_payload": {"prompt": "Redis lock이 있으면 시작하면 안 됨"},
        },
    )

    assert response.status_code == 409
    assert "active task already exists" in response.json()["detail"]


def test_taskruns_active_prefers_redis_projection_for_live_session(client):
    projection = RedisTaskProjectionStore(FakeRedis(), ttl_seconds=60)
    client.app.state.task_projection_store = projection
    task = TaskRun(
        task_run_id="task_projection_active",
        task_type="agent.loop",
        owner_key="projection-user",
        session_key="sess_projection",
        status="RUNNING",
        title="projection 작업",
        progress_summary="projection 실행 중",
    )
    step = StepRun(
        step_run_id="step_projection_active",
        task_run_id=task.task_run_id,
        step_order=1,
        step_type="agent.loop.execute",
        status="RUNNING",
        title="projection 단계",
    )
    task.current_step_run_id = step.step_run_id
    projection.save_task_snapshot(task)
    projection.save_step_snapshot(step)

    response = client.get("/ai/api/v1/taskRuns/active", params={"sessionId": "sess_projection"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_count"] == 1
    assert body["items"][0]["task_run_id"] == "task_projection_active"
    assert body["items"][0]["source"] == "active"
    assert body["items"][0]["current_step"]["step_run_id"] == "step_projection_active"


def test_taskruns_events_reads_redis_recent_projection_with_sequence_window(client):
    projection = RedisTaskProjectionStore(FakeRedis(), ttl_seconds=60)
    client.app.state.task_projection_store = projection
    for index in range(3):
        projection.append_event(
            TaskEventEnvelope(
                event_id=f"event_projection_{index}",
                event_type="task.updated",
                task_run_id="task_projection_events",
                step_run_id="step_projection_events",
                producer="test",
                occurred_at=f"2026-04-29T00:00:0{index}+00:00",
                status="RUNNING",
                summary_message=f"event {index}",
            )
        )

    response = client.get(
        "/ai/api/v1/taskRuns/task_projection_events/events",
        params={"afterSequence": 1, "limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["event_id"] == "event_projection_1"
    assert body[0]["sequence"] == 2


def test_taskruns_flow_returns_observed_step_node(client, monkeypatch):
    _patch_respond(
        monkeypatch,
        [
            _response(
                text=(
                    "안녕하세요. 현재 연결은 정상으로 보이며, 로컬 도구 호출도 가능한 상태입니다.\n"
                    "지금 바로 파일 조회, 검색, 터미널 실행, 계획 단계 설정 등을 진행할 수 있습니다."
                )
            )
        ],
    )

    create_response = client.post(
        "/ai/api/v1/taskRuns",
        json={
            "owner_key": "flow-user",
            "input_payload": {"prompt": "흐름 확인", "model": "gpt-test"},
        },
    )

    assert create_response.status_code == 200
    created = create_response.json()
    flow_response = client.get(f"/ai/api/v1/taskRuns/{created['task_run_id']}/flow")
    assert flow_response.status_code == 200
    flow = flow_response.json()
    assert "nodes" in flow
    assert len(flow["nodes"]) == 1
    assert flow["nodes"][0]["title"] == "agent loop 실행"
    assert "현재 연결은 정상" in flow["summary"]
