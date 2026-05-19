import json
from types import SimpleNamespace
import pytest

from app.contracts.task.step_status import StepStatus
from app.contracts.task.task_status import TaskStatus
from app.domain.orchestration.agent.tool_calling_loop import ToolCallingLoopHandler
from app.domain.orchestration.agent.tool_result_store import read_raw_tool_result_chunk
from app.domain.orchestration.agent.tool_guard import ToolGuardDecision, ToolGuardResult
from app.domain.providers.model.base import AgentMessage, AgentModelResponse, AssistantToolCall, ToolResultMessage


def _response(*, text: str = "", tool_calls: list[AssistantToolCall] | None = None) -> AgentModelResponse:
    calls = tool_calls or []
    return AgentModelResponse(
        provider_name="fake",
        model="gpt-test",
        message=AgentMessage(role="assistant", content=text, tool_calls=calls),
        output_text=text,
        tool_calls=calls,
        finish_reason="tool_calls" if calls else "stop",
        metadata={"model": "gpt-test"},
    )


def _tool_call(call_id: str, name: str, arguments: dict) -> AssistantToolCall:
    return AssistantToolCall(id=call_id, name=name, arguments=arguments)


class FakeProvider:
    name = "fake"

    def __init__(self, responses: list[AgentModelResponse], settings=None) -> None:
        self.responses = iter(responses)
        self.calls: list[dict] = []
        self.settings = settings

    def respond(self, messages, tools, model, tool_choice=None):
        self.calls.append({"messages": list(messages), "tools": tools, "model": model, "tool_choice": tool_choice})
        return next(self.responses)


class AsyncOnlyProvider(FakeProvider):
    def respond(self, *args, **kwargs):
        raise AssertionError("sync respond should not be used")

    async def respond_async(self, messages, tools, model, tool_choice=None, runtime_context=None):
        self.calls.append(
            {
                "messages": list(messages),
                "tools": tools,
                "model": model,
                "tool_choice": tool_choice,
                "runtime_context": runtime_context,
            }
        )
        return next(self.responses)


class FakePromptBuilder:
    def build_agent_loop_prompt(self, **kwargs) -> str:
        return "agent loop prompt"


class FakeToolCatalog:
    def list_available_tools(self, *, requested_toolsets=None):
        return [
            {
                "name": "terminal.run",
                "summary": "terminal",
                "toolset": "terminal",
                "schema": {
                    "name": "terminal.run",
                    "description": "terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]


class FakeDelegateToolCatalog:
    def list_available_tools(self, *, requested_toolsets=None):
        return [
            {
                "name": "delegate_task",
                "summary": "delegate",
                "toolset": "delegation",
                "schema": {
                    "name": "delegate_task",
                    "description": "delegate",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ]


class FakeToolResultCatalog:
    def list_available_tools(self, *, requested_toolsets=None):
        return [
            {
                "name": "terminal.run",
                "summary": "terminal",
                "toolset": "terminal",
                "schema": {
                    "name": "terminal.run",
                    "description": "terminal",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "name": "tool_result.read",
                "summary": "raw result reader",
                "toolset": "tool-result",
                "schema": {
                    "name": "tool_result.read",
                    "description": "read raw result",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "raw_ref": {"type": "string"},
                            "offset": {"type": "integer"},
                            "limit": {"type": "integer"},
                        },
                        "required": ["raw_ref"],
                    },
                },
            },
        ]


class FakeSessionStore:
    def __init__(self) -> None:
        self.sessions_by_key: dict[str, dict] = {}
        self.messages_by_session_id: dict[str, list[dict]] = {}

    def get_latest_session_by_key(self, session_key):
        return self.sessions_by_key.get(session_key)

    def get_session(self, session_id):
        if session_id in self.messages_by_session_id:
            return {"id": session_id, "metadata": {}}
        return None

    def create_session(self, *, session_id, session_key, source, user_id, model, title, metadata):
        session = {
            "id": session_id,
            "session_key": session_key,
            "source": source,
            "user_id": user_id,
            "model": model,
            "title": title,
            "metadata": metadata,
        }
        self.sessions_by_key[session_key] = session
        self.messages_by_session_id[session_id] = []

    def append_message(
        self,
        *,
        session_id,
        role,
        content,
        tool_name=None,
        tool_call_id=None,
        tool_calls=None,
        finish_reason=None,
        metadata=None,
    ):
        self.messages_by_session_id.setdefault(session_id, []).append(
            {
                "role": role,
                "content": content,
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "tool_calls": tool_calls or [],
                "finish_reason": finish_reason,
                "metadata": metadata or {},
            }
        )

    def list_messages(self, session_id):
        return list(self.messages_by_session_id.get(session_id, []))


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run_call(self, *, name, args, enabled_toolsets=None):
        self.calls.append({"name": name, "args": args, "enabled_toolsets": enabled_toolsets})
        return {"ok": True, "content": "executed"}


class SequenceRuntime(RecordingRuntime):
    def __init__(self, results: list[dict]) -> None:
        super().__init__()
        self.results = iter(results)

    def run_call(self, *, name, args, enabled_toolsets=None):
        self.calls.append({"name": name, "args": args, "enabled_toolsets": enabled_toolsets})
        return next(self.results)


class DelegationRuntime(RecordingRuntime):
    def run_call(self, *, name, args, enabled_toolsets=None):
        self.calls.append({"name": name, "args": args, "enabled_toolsets": enabled_toolsets})
        return {
            "ok": True,
            "child_session": {
                "goal": args["goal"],
                "context": args.get("context"),
                "toolsets": args.get("toolsets") or [],
                "max_iterations": args.get("max_iterations"),
                "input_payload": {"prompt": args["goal"]},
                "metadata": {"profile_key": args.get("profile_key") or "worker.default"},
            },
        }


class ToolResultReadRuntime(RecordingRuntime):
    def __init__(self, large_result: dict) -> None:
        super().__init__()
        self.large_result = large_result

    def run_call(self, *, name, args, enabled_toolsets=None):
        self.calls.append({"name": name, "args": args, "enabled_toolsets": enabled_toolsets})
        if name == "terminal.run":
            return self.large_result
        if name == "tool_result.read":
            return read_raw_tool_result_chunk(
                str(args.get("raw_ref") or ""),
                offset=int(args.get("offset") or 0),
                limit=int(args.get("limit") or 500),
            )
        return {"ok": False, "error": {"code": "unexpected_tool"}}


class StaticGuard:
    def __init__(self, result: ToolGuardResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    def evaluate(self, *, task_input, tool_call_id, tool_name, arguments):
        self.calls.append(
            {
                "task_input": task_input,
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "arguments": arguments,
            }
        )
        return self.result


class ProviderRateLimitError(Exception):
    status_code = 429


def test_worker_transcript_session_id_is_reused_without_collapsing_into_parent_session():
    session_store = FakeSessionStore()
    session_store.messages_by_session_id["agent_session_worker"] = []
    handler = ToolCallingLoopHandler(
        provider=FakeProvider([]),
        prompt_builder=FakePromptBuilder(),
        tool_runtime=RecordingRuntime(),
        tool_catalog=FakeToolCatalog(),
        session_store=session_store,
    )
    task = SimpleNamespace(
        task_run_id="task_child",
        owner_key="user_1",
        session_key="parent_session",
        title="Worker child",
    )

    session_id = handler._ensure_transcript_session(
        task=task,
        task_input={"transcript_session_id": "agent_session_worker"},
        model="gpt-test",
    )

    assert session_id == "agent_session_worker"
    assert "parent_session" not in session_store.sessions_by_key


@pytest.mark.asyncio
async def test_agent_loop_prefers_provider_respond_async():
    provider = AsyncOnlyProvider([_response(text="async ok")])
    handler = ToolCallingLoopHandler(
        provider=provider,
        prompt_builder=FakePromptBuilder(),
        tool_runtime=RecordingRuntime(),
        tool_catalog=FakeToolCatalog(),
    )

    outcome = await handler.execute_async(task=_task(), step=_step())

    assert outcome["step_status"] == StepStatus.COMPLETED
    assert outcome["result_payload"]["text"] == "async ok"
    assert provider.calls[0]["runtime_context"]["task_run_id"] == "task_guard"


@pytest.mark.asyncio
async def test_agent_loop_emits_model_call_timing_events():
    provider = AsyncOnlyProvider([_response(text="timed ok")])
    handler = ToolCallingLoopHandler(
        provider=provider,
        prompt_builder=FakePromptBuilder(),
        tool_runtime=RecordingRuntime(),
        tool_catalog=FakeToolCatalog(),
    )
    events: list[dict] = []

    async def progress_sink(**kwargs):
        events.append(kwargs)

    outcome = await handler.execute_async(task=_task(), step=_step(), progress_sink=progress_sink)

    assert outcome["step_status"] == StepStatus.COMPLETED
    assert [event["event_type"] for event in events] == ["model.started", "model.completed"]
    assert events[0]["payload"]["turnIndex"] == 1
    assert events[0]["payload"]["messageCount"] >= 1
    assert events[1]["payload"]["durationMs"] >= 0
    assert events[1]["payload"]["finishReason"] == "stop"
    assert events[1]["payload"]["toolCallCount"] == 0


def _task(input_payload: dict | None = None):
    return SimpleNamespace(
        task_run_id="task_guard",
        session_key=None,
        owner_key="tester",
        title="guard test",
        input_payload=input_payload or {"prompt": "run"},
        todo_state={},
    )


def _session_task(input_payload: dict | None = None):
    task = _task(input_payload)
    task.session_key = "sess_guard"
    return task


def _step(wait_payload: dict | None = None):
    return SimpleNamespace(step_run_id="step_guard", wait_payload=wait_payload or {})


def _handler(provider, runtime, guard, session_store=None) -> ToolCallingLoopHandler:
    return ToolCallingLoopHandler(
        provider=provider,
        prompt_builder=FakePromptBuilder(),
        tool_runtime=runtime,
        tool_catalog=FakeToolCatalog(),
        session_store=session_store,
        tool_guard=guard,
    )


def test_delegate_task_tool_result_becomes_child_session_outcome():
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    _tool_call(
                        "call_delegate",
                        "delegate_task",
                        {
                            "goal": "분리 검증",
                            "context": "worker가 별도 세션에서 검증한다.",
                            "toolsets": ["file"],
                            "max_iterations": 2,
                        },
                    )
                ]
            ),
            _response(text="worker 요청을 반영했습니다."),
        ]
    )
    runtime = DelegationRuntime()
    handler = ToolCallingLoopHandler(
        provider=provider,
        prompt_builder=FakePromptBuilder(),
        tool_runtime=runtime,
        tool_catalog=FakeDelegateToolCatalog(),
        tool_guard=StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW)),
    )

    outcome = handler.execute(
        task=_task(input_payload={"prompt": "worker에게 검증을 맡겨라.", "enabled_toolsets": ["delegation"]}),
        step=_step(),
    )

    assert outcome["child_session"]["goal"] == "분리 검증"
    assert outcome["child_session"]["toolsets"] == ["file"]
    assert outcome["child_session"]["max_iterations"] == 2


@pytest.mark.asyncio
async def test_delegate_task_executes_worker_before_deferring_later_sibling_tools():
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    _tool_call("call_delegate", "delegate_task", {"goal": "웹 자료 조사", "toolsets": ["web"]}),
                    _tool_call("call_write", "write_file", {"path": "tmp/report.md", "content": "# report"}),
                ]
            ),
            _response(text="worker 결과를 보고 다음 행동을 다시 판단했습니다."),
        ]
    )
    runtime = DelegationRuntime()
    handler = ToolCallingLoopHandler(
        provider=provider,
        prompt_builder=FakePromptBuilder(),
        tool_runtime=runtime,
        tool_catalog=FakeDelegateToolCatalog(),
        tool_guard=StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW)),
    )

    async def delegate_executor(*, child_session, tool_call_id, args, accepted_result):
        assert child_session["goal"] == "웹 자료 조사"
        return {
            "ok": True,
            "content": "worker 조사 요약",
            "delegate": {
                "agent_id": "agent_web",
                "workerSessionId": "session_worker_web",
                "profileKey": "worker.default",
                "status": TaskStatus.COMPLETED,
                "summary": "worker 조사 요약",
            },
        }

    outcome = await handler.execute_async(
        task=_task(input_payload={"prompt": "조사 후 작성", "enabled_toolsets": ["delegation", "file"]}),
        step=_step(),
        delegate_executor=delegate_executor,
    )

    tool_results = outcome["result_payload"]["tool_results"]
    assert [item["name"] for item in tool_results] == ["delegate_task", "write_file"]
    assert tool_results[0]["result"]["delegate"]["workerSessionId"] == "session_worker_web"
    assert tool_results[1]["result"]["error"]["code"] == "tool_deferred_by_delegate_boundary"
    assert runtime.calls == [
        {
            "name": "delegate_task",
            "args": {"goal": "웹 자료 조사", "toolsets": ["web"]},
            "enabled_toolsets": ("delegation", "file", "tool-result"),
        }
    ]
    assert "child_session" not in outcome
    replayed_tool_messages = [message for message in provider.calls[1]["messages"] if isinstance(message, ToolResultMessage)]
    assert json.loads(replayed_tool_messages[0].content)["content"] == "worker 조사 요약"


def test_guard_block_appends_blocked_tool_result_without_runtime_call():
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call("call_block", "terminal_run", {"argv": ["echo", "blocked"]})]),
            _response(text="BLOCK_OBSERVED"),
        ]
    )
    runtime = RecordingRuntime()
    guard = StaticGuard(
        ToolGuardResult(
            decision=ToolGuardDecision.BLOCK,
            reason="blocked by policy",
            payload={"policy": "deny_terminal"},
        )
    )

    outcome = _handler(provider, runtime, guard).execute(task=_task(), step=_step())

    assert runtime.calls == []
    assert outcome["task_status"] == TaskStatus.COMPLETED
    blocked_result = outcome["result_payload"]["tool_results"][0]
    assert blocked_result["tool_call_id"] == "call_block"
    assert blocked_result["result"]["ok"] is False
    assert blocked_result["result"]["error"]["code"] == "tool_blocked"
    assert blocked_result["result"]["guard"]["decision"] == "BLOCK"

    replayed_tool_messages = [message for message in provider.calls[1]["messages"] if isinstance(message, ToolResultMessage)]
    assert len(replayed_tool_messages) == 1
    assert replayed_tool_messages[0].tool_call_id == "call_block"
    assert "blocked by policy" in replayed_tool_messages[0].content


def test_large_tool_result_is_stored_as_raw_ref_and_replayed_as_bounded_observation(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGENT_TOOL_RESULT_STORE_DIR", str(tmp_path / "tool-results"))
    large_rows = [{"index": index, "value": "x" * 1500} for index in range(120)]
    runtime = SequenceRuntime([{"ok": True, "json": {"items": large_rows}, "content_type": "application/json"}])
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call("call_large", "terminal_run", {"argv": ["fake-large"]})]),
            _response(text="LARGE_DONE"),
        ]
    )
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))

    outcome = _handler(provider, runtime, guard).execute(task=_task(), step=_step())

    observed_result = outcome["result_payload"]["tool_results"][0]["result"]
    assert observed_result["truncated"] is True
    assert observed_result["raw_ref"].startswith("tool-result://")
    assert observed_result["raw_chars"] > 20_000
    assert "x" * 1500 not in str(observed_result)

    replayed_tool_messages = [message for message in provider.calls[1]["messages"] if isinstance(message, ToolResultMessage)]
    assert len(replayed_tool_messages) == 1
    assert replayed_tool_messages[0].tool_call_id == "call_large"
    assert len(replayed_tool_messages[0].content) <= ToolCallingLoopHandler.TOOL_RESULT_OBSERVATION_MAX_CHARS
    assert "Use tool_result.read" in replayed_tool_messages[0].content
    assert "raw_ref" in replayed_tool_messages[0].content
    assert "preview" in replayed_tool_messages[0].content
    assert "x" * 1500 not in replayed_tool_messages[0].content

    raw_chunk = read_raw_tool_result_chunk(observed_result["raw_ref"], limit=500)
    assert raw_chunk["ok"] is True
    assert raw_chunk["raw_chars"] == observed_result["raw_chars"]
    assert '"items"' in raw_chunk["content"]
    assert outcome["output_payload"]["tool_results"][0]["result"] == observed_result


@pytest.mark.asyncio
async def test_large_tool_result_transcript_and_progress_store_bounded_observation(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGENT_TOOL_RESULT_STORE_DIR", str(tmp_path / "tool-results"))
    large_rows = [{"index": index, "value": "x" * 1500} for index in range(120)]
    runtime = SequenceRuntime([{"ok": True, "json": {"items": large_rows}, "content_type": "application/json"}])
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call("call_large", "terminal_run", {"argv": ["fake-large"]})]),
            _response(text="LARGE_DONE"),
        ]
    )
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))
    session_store = FakeSessionStore()
    events: list[dict] = []

    async def progress_sink(**kwargs):
        events.append(kwargs)

    outcome = await _handler(provider, runtime, guard, session_store=session_store).execute_async(
        task=_session_task(),
        step=_step(),
        progress_sink=progress_sink,
    )

    observed_result = outcome["result_payload"]["tool_results"][0]["result"]
    session_id = session_store.sessions_by_key["sess_guard"]["id"]
    tool_rows = [row for row in session_store.messages_by_session_id[session_id] if row["role"] == "tool"]
    assert len(tool_rows) == 1
    assert "raw_ref" in tool_rows[0]["content"]
    assert "preview" in tool_rows[0]["content"]
    assert "x" * 1500 not in tool_rows[0]["content"]

    completed = [event for event in events if event["event_type"] == "tool.completed"]
    assert len(completed) == 1
    progress_result = completed[0]["payload"]["result"]
    assert progress_result["raw_ref"] == observed_result["raw_ref"]
    assert progress_result["truncated"] is True
    assert "x" * 1500 not in json.dumps(progress_result, ensure_ascii=False)


def test_tool_result_read_can_follow_raw_ref_without_reexpanding_result(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGENT_TOOL_RESULT_STORE_DIR", str(tmp_path / "tool-results"))
    large_rows = [{"index": index, "value": "x" * 1500} for index in range(120)]
    runtime = ToolResultReadRuntime({"ok": True, "json": {"items": large_rows}, "content_type": "application/json"})

    class RawRefProvider(FakeProvider):
        def __init__(self) -> None:
            super().__init__([])

        def respond(self, messages, tools, model, tool_choice=None):
            self.calls.append({"messages": list(messages), "tools": tools, "model": model, "tool_choice": tool_choice})
            if len(self.calls) == 1:
                return _response(tool_calls=[_tool_call("call_large", "terminal_run", {"argv": ["fake-large"]})])
            if len(self.calls) == 2:
                tool_message = next(message for message in messages if isinstance(message, ToolResultMessage))
                raw_ref = json.loads(tool_message.content)["raw_ref"]
                return _response(
                    tool_calls=[
                        _tool_call(
                            "call_read",
                            "tool_result_read",
                            {"raw_ref": raw_ref, "offset": 0, "limit": 500},
                        )
                    ]
                )
            return _response(text="READ_DONE")

    provider = RawRefProvider()
    handler = ToolCallingLoopHandler(
        provider=provider,
        prompt_builder=FakePromptBuilder(),
        tool_runtime=runtime,
        tool_catalog=FakeToolResultCatalog(),
        tool_guard=StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW)),
    )

    outcome = handler.execute(task=_task({"prompt": "read raw", "enabled_toolsets": ["terminal"]}), step=_step())

    assert [call["name"] for call in runtime.calls] == ["terminal.run", "tool_result.read"]
    assert runtime.calls[0]["enabled_toolsets"] == ("terminal", "tool-result")
    assert runtime.calls[1]["enabled_toolsets"] == ("terminal", "tool-result")
    read_result = outcome["result_payload"]["tool_results"][1]["result"]
    assert read_result["ok"] is True
    assert read_result["returned_chars"] <= 500
    assert "truncated" not in read_result
    assert outcome["result_payload"]["text"] == "READ_DONE"


def test_agent_loop_explicit_max_iterations_can_exceed_legacy_hard_clamp():
    responses = [
        _response(tool_calls=[_tool_call(f"call_{index}", "terminal_run", {"argv": ["echo", str(index)]})])
        for index in range(13)
    ]
    responses.append(_response(text="ITERATION_13_DONE"))
    provider = FakeProvider(
        responses,
        settings=SimpleNamespace(
            agent_loop_default_max_iterations=90,
            agent_loop_max_iterations=120,
        ),
    )
    runtime = RecordingRuntime()
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))

    outcome = _handler(provider, runtime, guard).execute(
        task=_task({"prompt": "run", "max_iterations": 20}),
        step=_step(),
    )

    assert outcome["task_status"] == TaskStatus.COMPLETED
    assert outcome["result_payload"]["text"] == "ITERATION_13_DONE"
    assert len(provider.calls) == 14
    assert len(runtime.calls) == 13


def test_agent_loop_fails_when_max_iterations_are_exhausted_without_final_answer():
    responses = [
        _response(tool_calls=[_tool_call(f"call_{index}", "terminal_run", {"argv": ["echo", str(index)]})])
        for index in range(2)
    ]
    provider = FakeProvider(responses)
    runtime = RecordingRuntime()
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))

    outcome = _handler(provider, runtime, guard).execute(
        task=_task({"prompt": "run", "max_iterations": 2}),
        step=_step(),
    )

    assert outcome["task_status"] == TaskStatus.FAILED
    assert outcome["step_status"] == StepStatus.FAILED
    assert outcome["result_payload"]["error"]["code"] == "max_iterations_exceeded"
    assert outcome["error_message"] == "작업 반복 한도(2)에 도달했습니다."
    assert len(provider.calls) == 2
    assert len(runtime.calls) == 2


def test_repeated_rate_limited_tool_call_is_blocked_with_synthetic_result():
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call("call_1", "terminal_run", {"argv": ["curl", "weather"]})]),
            _response(tool_calls=[_tool_call("call_2", "terminal_run", {"argv": ["curl", "weather"]})]),
            _response(text="BLOCK_OBSERVED"),
        ]
    )
    runtime = SequenceRuntime(
        [
            {
                "ok": False,
                "error": {
                    "code": "upstream_rate_limit",
                    "message": "HTTP 429 Too Many Requests",
                    "status_code": 429,
                    "retryable": True,
                },
                "content": '{"error":{"code":"upstream_rate_limit"}}',
            }
        ]
    )
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))

    outcome = _handler(provider, runtime, guard).execute(
        task=_task({"prompt": "run", "max_iterations": 5}),
        step=_step(),
    )

    assert outcome["task_status"] == TaskStatus.COMPLETED
    assert len(runtime.calls) == 1
    assert [item["tool_call_id"] for item in outcome["result_payload"]["tool_results"]] == ["call_1", "call_2"]
    blocked_result = outcome["result_payload"]["tool_results"][1]["result"]
    assert blocked_result["error"]["code"] == "tool_circuit_open"
    assert blocked_result["error"]["type"] == "rate_limited"
    replayed_tool_messages = [message for message in provider.calls[2]["messages"] if isinstance(message, ToolResultMessage)]
    assert [message.tool_call_id for message in replayed_tool_messages] == ["call_1", "call_2"]


def test_repeated_circuit_open_call_fails_without_waiting_for_max_iterations():
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call("call_1", "terminal_run", {"argv": ["curl", "weather"]})]),
            _response(tool_calls=[_tool_call("call_2", "terminal_run", {"argv": ["curl", "weather"]})]),
            _response(tool_calls=[_tool_call("call_3", "terminal_run", {"argv": ["curl", "weather"]})]),
        ]
    )
    runtime = SequenceRuntime(
        [
            {
                "ok": False,
                "error": {"code": "upstream_rate_limit", "message": "HTTP 429", "status_code": 429},
                "content": '{"error":{"code":"upstream_rate_limit"}}',
            }
        ]
    )
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))

    outcome = _handler(provider, runtime, guard).execute(
        task=_task({"prompt": "run", "max_iterations": 10}),
        step=_step(),
    )

    assert outcome["task_status"] == TaskStatus.FAILED
    assert outcome["result_payload"]["error"]["code"] == "rate_limited_blocked"
    assert outcome["result_payload"]["error"]["type"] == "rate_limited"
    assert len(provider.calls) == 3
    assert len(runtime.calls) == 1


def test_unavailable_tool_name_streak_blocks_even_when_args_change():
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call("call_1", "terminal_run", {"argv": ["missing", "one"]})]),
            _response(tool_calls=[_tool_call("call_2", "terminal_run", {"argv": ["missing", "two"]})]),
            _response(text="UNAVAILABLE_BLOCK_OBSERVED"),
        ]
    )
    runtime = SequenceRuntime(
        [
            {
                "ok": False,
                "error": {
                    "code": "tool_unavailable",
                    "message": "unknown or disabled runtime tool: terminal.run",
                    "tool_name": "terminal.run",
                },
                "content": '{"error":{"code":"tool_unavailable"}}',
            }
        ]
    )
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))

    outcome = _handler(provider, runtime, guard).execute(
        task=_task({"prompt": "run", "max_iterations": 5}),
        step=_step(),
    )

    assert outcome["task_status"] == TaskStatus.COMPLETED
    assert len(runtime.calls) == 1
    blocked_result = outcome["result_payload"]["tool_results"][1]["result"]
    assert blocked_result["error"]["code"] == "tool_circuit_open"
    assert blocked_result["error"]["type"] == "tool_unavailable"


def test_provider_rate_limit_failure_is_not_recorded_as_tool_result():
    provider = FakeProvider([])

    def raise_rate_limit(*args, **kwargs):
        raise ProviderRateLimitError("HTTP 429 Too Many Requests")

    provider.respond = raise_rate_limit
    runtime = RecordingRuntime()

    outcome = _handler(provider, runtime, StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))).execute(
        task=_task({"prompt": "run", "max_iterations": 5}),
        step=_step(),
    )

    assert outcome["task_status"] == TaskStatus.FAILED
    assert outcome["result_payload"]["error"]["code"] == "provider_rate_limited"
    assert outcome["result_payload"]["tool_results"] == []
    assert runtime.calls == []


def test_agent_loop_worker_payload_uses_worker_default_when_max_iterations_is_absent():
    responses = [
        _response(tool_calls=[_tool_call(f"call_worker_{index}", "terminal_run", {"argv": ["echo", str(index)]})])
        for index in range(13)
    ]
    responses.append(_response(text="WORKER_DEFAULT_DONE"))
    provider = FakeProvider(
        responses,
        settings=SimpleNamespace(
            agent_loop_default_max_iterations=90,
            agent_loop_worker_default_max_iterations=80,
            agent_loop_max_iterations=120,
        ),
    )
    runtime = RecordingRuntime()
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))

    outcome = _handler(provider, runtime, guard).execute(
        task=_task({"prompt": "worker", "worker": {"leaf": True}}),
        step=_step(),
    )

    assert outcome["task_status"] == TaskStatus.COMPLETED
    assert outcome["result_payload"]["text"] == "WORKER_DEFAULT_DONE"
    assert len(provider.calls) == 14
    assert len(runtime.calls) == 13


def test_resume_rejected_appends_blocked_pending_tool_result_and_recontinues_loop():
    provider = FakeProvider([_response(text="DENIED_CONTINUED")])
    runtime = RecordingRuntime()
    guard = StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW))
    step = _step(
        {
            "pending_tool_call_id": "call_pending",
            "pending_tool_name": "terminal.run",
            "pending_tool_arguments": {"argv": ["echo", "pending"]},
        }
    )

    outcome = _handler(provider, runtime, guard).execute(
        task=_task(),
        step=step,
        resume_payload={"approved": False, "reason": "user denied"},
    )

    assert runtime.calls == []
    assert outcome["task_status"] == TaskStatus.COMPLETED
    denied_result = outcome["result_payload"]["tool_results"][0]
    assert denied_result["tool_call_id"] == "call_pending"
    assert denied_result["result"]["ok"] is False
    assert denied_result["result"]["error"]["code"] == "tool_blocked"
    assert denied_result["result"]["guard"]["decision"] == "BLOCK"
    assert denied_result["result"]["guard"]["resume_decision"] == "rejected"

    replayed_tool_messages = [message for message in provider.calls[0]["messages"] if isinstance(message, ToolResultMessage)]
    assert len(replayed_tool_messages) == 1
    assert replayed_tool_messages[0].tool_call_id == "call_pending"


def test_approved_resume_context_allows_followup_tool_calls_after_global_approval():
    provider = FakeProvider(
        [
            _response(tool_calls=[_tool_call("call_followup", "terminal_run", {"argv": ["echo", "followup"]})]),
            _response(text="APPROVED_CONTINUED"),
        ]
    )
    runtime = RecordingRuntime()
    step = _step(
        {
            "pending_tool_call_id": "call_pending",
            "pending_tool_name": "terminal.run",
            "pending_tool_arguments": {"argv": ["echo", "pending"]},
            "approval_policy_result": {"decision": "NEEDS_APPROVAL", "source": "legacy_input_payload"},
        }
    )

    outcome = _handler(provider, runtime, guard=None).execute(
        task=_task({"prompt": "run", "approval_required": True}),
        step=step,
        resume_payload={"approved": True},
    )

    assert outcome["task_status"] == TaskStatus.COMPLETED
    assert [call["args"]["argv"] for call in runtime.calls] == [["echo", "pending"], ["echo", "followup"]]
    assert [item["tool_call_id"] for item in outcome["result_payload"]["tool_results"]] == ["call_pending", "call_followup"]


def test_resume_after_first_sibling_wait_replays_outputs_for_every_previous_tool_call():
    session_store = FakeSessionStore()
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    _tool_call("call_wait", "terminal_run", {"argv": ["echo", "wait"]}),
                    _tool_call("call_sibling", "terminal_run", {"argv": ["echo", "sibling"]}),
                ]
            ),
            _response(text="RESUMED"),
        ]
    )
    runtime = RecordingRuntime()
    guard = StaticGuard(
        ToolGuardResult(
            decision=ToolGuardDecision.NEEDS_APPROVAL,
            reason="approval needed",
            payload={"risk": "terminal_execution"},
        )
    )
    task = _session_task()

    waiting = _handler(provider, runtime, guard, session_store=session_store).execute(task=task, step=_step())
    assert waiting["task_status"] == TaskStatus.WAITING

    step = _step(waiting["wait_payload"])
    resume_provider = FakeProvider([_response(text="RESUMED")])
    resumed = _handler(
        resume_provider,
        runtime,
        StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW)),
        session_store=session_store,
    ).execute(task=task, step=step, resume_payload={"approved": True})

    replayed_tool_ids = [
        message.tool_call_id for message in resume_provider.calls[0]["messages"] if isinstance(message, ToolResultMessage)
    ]
    assert resumed["task_status"] == TaskStatus.COMPLETED
    assert replayed_tool_ids == ["call_wait", "call_sibling"]
    assert [call["args"]["argv"] for call in runtime.calls] == [["echo", "wait"]]


def test_rejected_resume_after_sibling_wait_replays_outputs_in_tool_call_order():
    session_store = FakeSessionStore()
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    _tool_call("call_wait", "terminal_run", {"argv": ["echo", "wait"]}),
                    _tool_call("call_sibling", "terminal_run", {"argv": ["echo", "sibling"]}),
                ]
            ),
            _response(text="REJECTED_CONTINUED"),
        ]
    )
    runtime = RecordingRuntime()
    guard = StaticGuard(
        ToolGuardResult(
            decision=ToolGuardDecision.NEEDS_APPROVAL,
            reason="approval needed",
            payload={"risk": "terminal_execution"},
        )
    )
    task = _session_task()

    waiting = _handler(provider, runtime, guard, session_store=session_store).execute(task=task, step=_step())

    step = _step(waiting["wait_payload"])
    resume_provider = FakeProvider([_response(text="REJECTED_CONTINUED")])
    resumed = _handler(
        resume_provider,
        runtime,
        StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW)),
        session_store=session_store,
    ).execute(task=task, step=step, resume_payload={"approved": False, "reason": "user denied"})

    replayed_tool_ids = [
        message.tool_call_id for message in resume_provider.calls[0]["messages"] if isinstance(message, ToolResultMessage)
    ]
    assert resumed["task_status"] == TaskStatus.COMPLETED
    assert runtime.calls == []
    assert replayed_tool_ids == ["call_wait", "call_sibling"]


def test_resume_after_second_sibling_wait_replays_outputs_for_every_previous_tool_call():
    session_store = FakeSessionStore()
    provider = FakeProvider(
        [
            _response(
                tool_calls=[
                    _tool_call("call_done", "terminal_run", {"argv": ["echo", "done"]}),
                    _tool_call("call_wait", "terminal_run", {"argv": ["echo", "wait"]}),
                    _tool_call("call_sibling", "terminal_run", {"argv": ["echo", "sibling"]}),
                ]
            ),
            _response(text="RESUMED"),
        ]
    )
    runtime = RecordingRuntime()

    class SecondCallWaitGuard:
        def evaluate(self, *, task_input, tool_call_id, tool_name, arguments):
            if tool_call_id == "call_wait":
                return ToolGuardResult(
                    decision=ToolGuardDecision.NEEDS_APPROVAL,
                    reason="approval needed",
                    payload={"risk": "terminal_execution"},
                )
            return ToolGuardResult(decision=ToolGuardDecision.ALLOW)

    task = _session_task()

    waiting = _handler(provider, runtime, SecondCallWaitGuard(), session_store=session_store).execute(task=task, step=_step())
    assert waiting["task_status"] == TaskStatus.WAITING

    step = _step(waiting["wait_payload"])
    resume_provider = FakeProvider([_response(text="RESUMED")])
    resumed = _handler(
        resume_provider,
        runtime,
        StaticGuard(ToolGuardResult(decision=ToolGuardDecision.ALLOW)),
        session_store=session_store,
    ).execute(task=task, step=step, resume_payload={"approved": True})

    replayed_tool_ids = [
        message.tool_call_id for message in resume_provider.calls[0]["messages"] if isinstance(message, ToolResultMessage)
    ]
    assert resumed["task_status"] == TaskStatus.COMPLETED
    assert replayed_tool_ids == ["call_done", "call_wait", "call_sibling"]
    assert [call["args"]["argv"] for call in runtime.calls] == [["echo", "done"], ["echo", "wait"]]


def test_guard_needs_approval_stores_pending_tool_snapshot_in_wait_and_approval_payload():
    provider = FakeProvider(
        [_response(tool_calls=[_tool_call("call_wait", "terminal_run", {"argv": ["echo", "wait"]})])]
    )
    runtime = RecordingRuntime()
    guard = StaticGuard(
        ToolGuardResult(
            decision=ToolGuardDecision.NEEDS_APPROVAL,
            reason="terminal requires approval",
            payload={"risk": "terminal_execution"},
        )
    )

    outcome = _handler(provider, runtime, guard).execute(task=_task(), step=_step())

    assert runtime.calls == []
    assert outcome["task_status"] == TaskStatus.WAITING
    assert outcome["step_status"] == StepStatus.WAITING
    assert outcome["wait_payload"]["pending_tool_call_id"] == "call_wait"
    assert outcome["wait_payload"]["pending_tool_name"] == "terminal.run"
    assert outcome["wait_payload"]["pending_tool_arguments"] == {"argv": ["echo", "wait"]}
    assert outcome["wait_payload"]["approval_policy_result"]["decision"] == "NEEDS_APPROVAL"
    assert outcome["wait_payload"]["approval_policy_result"]["risk"] == "terminal_execution"
    assert outcome["approval_payload"]["pending_tool_call_id"] == "call_wait"
    assert outcome["approval_payload"]["approval_policy_result"]["decision"] == "NEEDS_APPROVAL"
