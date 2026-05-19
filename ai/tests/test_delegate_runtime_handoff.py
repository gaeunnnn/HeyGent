from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.contracts.task.task_status import TaskStatus
from app.domain.orchestration.agent.runner import AgentLoopRunner
from app.domain.orchestration.delegation.delegate_runtime import DelegateRuntime
from app.domain.orchestration.delegation.launcher import ChildSessionLauncher
from app.domain.orchestration.delegation.spec import ChildSessionLaunchResult, ChildSessionSpec
from app.domain.orchestration.runtime_planning import Planner
from app.tools.contracts import HandlerSpec


class FakeChildSessionLauncher:
    def __init__(self, result: ChildSessionLaunchResult | Exception) -> None:
        self.result = result
        self.launched: list[dict] = []

    def build_pending_detail(self, spec):
        return {"agentDetail": {"status": "PENDING", "agentId": f"{spec.parent_step_run_id}:agent.loop"}}

    def build_failed_detail(self, spec, error_message: str):
        return {"agentDetail": {"status": "FAILED", "summary": error_message}}

    def build_result_detail(self, spec, result):
        return {
            "agentDetail": {
                "status": result.status,
                "summary": result.summary,
                "workerSessionId": spec.worker_session_id,
                "profileKey": (spec.metadata or {}).get("profile_key"),
                "agentId": result.agent_id,
            }
        }

    async def launch(self, **kwargs):
        self.launched.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeHandoffRepository:
    def __init__(self) -> None:
        self.steps: list[object] = []
        self.created_handoffs: list[dict] = []
        self.completed_handoffs: list[tuple[str, dict]] = []
        self.agent_profiles: dict[str, dict] = {}

    def update_step(self, step):
        self.steps.append(step)
        return step

    def create_worker_handoff(self, payload):
        self.created_handoffs.append(payload)
        return payload

    def complete_worker_handoff(self, handoff_id, payload):
        self.completed_handoffs.append((handoff_id, payload))
        return {"handoff_id": handoff_id, **payload}

    def get_agent_profile(self, profile_key, *, owner_key="system", profile_version=None):
        return self.agent_profiles.get(profile_key)


class FakeWorkerSessionStore:
    def __init__(self) -> None:
        self.sessions_by_key = {
            "session_1": {
                "id": "agent_session_parent",
                "session_key": "session_1",
                "metadata": {"task_run_id": "task_parent"},
            }
        }
        self.created_sessions: list[dict] = []
        self.ended_sessions: list[dict] = []

    def get_session(self, session_id):
        for session in self.sessions_by_key.values():
            if session.get("id") == session_id:
                return session
        for session in self.created_sessions:
            if session.get("session_id") == session_id:
                return {
                    "id": session["session_id"],
                    "session_key": session["session_key"],
                    "metadata": session.get("metadata") or {},
                    "parent_session_id": session.get("parent_session_id"),
                    "source": session.get("source"),
                }
        return None

    def get_latest_session_by_key(self, session_key):
        return self.sessions_by_key.get(session_key)

    def create_session(self, **payload):
        self.created_sessions.append(payload)
        session = {
            "id": payload["session_id"],
            "session_key": payload["session_key"],
            "metadata": payload.get("metadata") or {},
            "parent_session_id": payload.get("parent_session_id"),
        }
        self.sessions_by_key[payload["session_key"]] = session
        return payload["session_id"]

    def end_session(self, session_id, *, end_reason=None):
        self.ended_sessions.append({"session_id": session_id, "end_reason": end_reason})


class FakeWorkerHandler:
    spec = HandlerSpec(
        task_type="agent.loop",
        task_title="Agent Loop",
        step_type="agent.loop",
        step_title="Agent Loop",
    )

    def __init__(self) -> None:
        self.executed: list[dict] = []

    def execute(self, *, task, step, resume_payload=None):
        self.executed.append({"task": task, "step": step, "resume_payload": resume_payload})
        return {
            "task_status": TaskStatus.COMPLETED,
            "step_status": TaskStatus.COMPLETED,
            "result_payload": {"text": "worker result"},
            "output_payload": {"text": "worker result"},
            "summary_message": "worker result",
        }


class SlowAsyncWorkerHandler(FakeWorkerHandler):
    async def execute_async(self, *, task, step, resume_payload=None, progress_sink=None):
        await asyncio.sleep(0.05)
        return {
            "task_status": TaskStatus.COMPLETED,
            "step_status": TaskStatus.COMPLETED,
            "result_payload": {"text": "slow worker"},
            "output_payload": {"text": "slow worker"},
            "summary_message": "slow worker",
        }


class FakeWorkerRegistry:
    def __init__(self, handler) -> None:
        self.handler = handler

    def resolve(self):
        return self.handler


class RepositoryThatFailsOnCreateTask:
    def create_task(self, task):
        raise AssertionError("worker 실행은 별도 TaskRun을 저장하면 안 됩니다")


def assert_legacy_task_run_id_not_exposed(value):
    if isinstance(value, dict):
        assert "childTaskRunId" not in value
        for child in value.values():
            assert_legacy_task_run_id_not_exposed(child)
    elif isinstance(value, list):
        for child in value:
            assert_legacy_task_run_id_not_exposed(child)


@pytest.mark.asyncio
async def test_child_session_launcher_uses_worker_callback_without_legacy_task_run_id():
    launched: list[dict] = []
    launcher = ChildSessionLauncher()

    async def start_worker(**kwargs):
        launched.append(kwargs)
        return ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="작업 완료",
            result_payload={"text": "작업 완료"},
        )

    launcher.bind_worker_start(start_worker)
    spec = ChildSessionSpec(
        parent_task_run_id="task_parent",
        parent_step_run_id="step_parent",
        metadata={"profile_key": "worker.default", "agent_id": "agent_worker"},
        worker_session_id="session_worker",
    )

    result = await launcher.launch(
        spec=spec,
        owner_key="user_1",
        session_key="session_1",
        input_payload={"transcript_session_id": "session_worker"},
    )

    assert launched[0]["input_payload"]["transcript_session_id"] == "session_worker"
    detail = launcher.build_result_detail(spec, result)
    assert detail["agentDetail"]["workerSessionId"] == "session_worker"
    assert detail["agentDetail"]["profileKey"] == "worker.default"
    assert_legacy_task_run_id_not_exposed(detail)


@pytest.mark.asyncio
async def test_agent_loop_runner_worker_session_does_not_create_task_run():
    handler = FakeWorkerHandler()
    runner = AgentLoopRunner(
        repository=RepositoryThatFailsOnCreateTask(),
        planner=Planner(),
        task_engine=SimpleNamespace(),
        tool_registry=FakeWorkerRegistry(handler),
    )
    spec = ChildSessionSpec(
        parent_task_run_id="task_parent",
        parent_step_run_id="step_parent",
        metadata={"agent_id": "agent_worker"},
        worker_session_id="session_worker",
    )

    result = await runner.start_worker_session(
        spec=spec,
        owner_key="user_1",
        session_key="session_1",
        input_payload={"prompt": "worker", "transcript_session_id": "session_worker"},
    )

    assert result.status == TaskStatus.COMPLETED
    assert result.summary == "worker result"
    assert handler.executed[0]["step"] is None


@pytest.mark.asyncio
async def test_agent_loop_runner_enforces_worker_hard_timeout():
    runner = AgentLoopRunner(
        repository=RepositoryThatFailsOnCreateTask(),
        planner=Planner(),
        task_engine=SimpleNamespace(),
        tool_registry=FakeWorkerRegistry(SlowAsyncWorkerHandler()),
    )
    spec = ChildSessionSpec(
        parent_task_run_id="task_parent",
        parent_step_run_id="step_parent",
        metadata={"agent_id": "agent_worker"},
        worker_session_id="session_worker",
    )

    with pytest.raises(TimeoutError, match="worker session exceeded hard timeout"):
        await runner.start_worker_session(
            spec=spec,
            owner_key="user_1",
            session_key="session_1",
            input_payload={
                "prompt": "worker",
                "transcript_session_id": "session_worker",
                "hard_timeout_seconds": 0.01,
            },
        )


@pytest.mark.asyncio
async def test_delegate_runtime_records_worker_handoff_when_repository_supports_it():
    launcher = FakeChildSessionLauncher(
        ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="작업 완료",
        )
    )
    runtime = DelegateRuntime(launcher)
    repository = FakeHandoffRepository()
    task = SimpleNamespace(task_run_id="task_parent", owner_key="user_1", session_key="session_1")
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    outcome = {
        "child_session": {
            "input_payload": {"prompt": "하위 작업"},
            "metadata": {"profile_key": "worker.default"},
        }
    }

    result = await runtime.apply(task=task, step=step, outcome=outcome, repository=repository)

    assert repository.created_handoffs[0]["task_run_id"] == "task_parent"
    assert repository.created_handoffs[0]["parent_step_run_id"] == "step_parent"
    assert repository.created_handoffs[0]["worker_profile_id"] == "worker.default"
    completed_id, completed_payload = repository.completed_handoffs[0]
    assert completed_id == repository.created_handoffs[0]["handoff_id"]
    assert completed_payload["status"] == "COMPLETED"
    assert completed_payload["result_summary"]["workerSessionId"] is None
    assert completed_payload["result_summary"]["profileKey"] == "worker.default"
    assert result["result_payload"]["delegate"]["workerSessionId"] is None
    assert result["result_payload"]["delegate"]["profileKey"] == "worker.default"
    assert_legacy_task_run_id_not_exposed(completed_payload["result_summary"])
    assert_legacy_task_run_id_not_exposed(result["result_payload"])
    assert_legacy_task_run_id_not_exposed(result["output_payload"])


@pytest.mark.asyncio
async def test_delegate_runtime_creates_worker_session_and_normalizes_contract_payload():
    launcher = FakeChildSessionLauncher(
        ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="worker summary",
        )
    )
    session_store = FakeWorkerSessionStore()
    runtime = DelegateRuntime(launcher, session_store=session_store)
    repository = FakeHandoffRepository()
    task = SimpleNamespace(task_run_id="task_parent", owner_key="user_1", session_key="session_1")
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    result = await runtime.apply(
        task=task,
        step=step,
        outcome={
            "child_session": {
                "goal": "문서 갭 줄이기",
                "context": {"branch": "AI-feat/Subagent_구조화"},
                "toolsets": ["file", "delegation", "terminal", "file"],
                "max_iterations": 15,
                "role": "worker",
                "acp_command": "run",
                "acp_args": {"target": "delegate"},
                "tasks": [{"summary": "계약 보강"}],
                "metadata": {"profile_key": "worker.docs", "agent_id": "agent_worker"},
            }
        },
        repository=repository,
    )

    created_session = session_store.created_sessions[0]
    worker_session_id = created_session["session_id"]
    assert created_session["source"] == "worker"
    assert created_session["parent_session_id"] == "agent_session_parent"
    assert created_session["metadata"]["parent_step_run_id"] == "step_parent"
    assert created_session["metadata"]["profile_key"] == "worker.docs"
    assert created_session["metadata"]["delegation_policy"]["leaf"] is True

    handoff = repository.created_handoffs[0]
    assert handoff["status"] == "RUNNING"
    assert handoff["worker_session_id"] == worker_session_id
    assert handoff["input_payload"]["profile_key"] == "worker.docs"
    assert handoff["input_payload"]["agent_id"] == "agent_worker"
    assert handoff["input_payload"]["toolsets"] == ["file", "terminal"]
    assert handoff["input_payload"]["blocked_toolsets"] == ["delegate", "delegation"]

    launched_payload = launcher.launched[0]["input_payload"]
    assert launched_payload["transcript_session_id"] == worker_session_id
    assert launched_payload["enabled_toolsets"] == ["file", "terminal"]
    assert launched_payload["worker"]["leaf"] is True
    assert launched_payload["tasks"] == [{"summary": "계약 보강"}]
    assert launched_payload["hard_timeout_seconds"] == 900
    assert launched_payload["worker"]["hard_timeout_seconds"] == 900

    delegate_result = result["output_payload"]["delegate"]
    assert delegate_result["profile_key"] == "worker.docs"
    assert delegate_result["profileKey"] == "worker.docs"
    assert delegate_result["agent_id"] == "agent_worker"
    assert delegate_result["workerSessionId"] == worker_session_id
    assert delegate_result["total_duration_seconds"] is not None
    assert delegate_result["results"][0]["task_index"] == 0
    assert delegate_result["results"][0]["status"] == TaskStatus.COMPLETED
    assert result["output_payload"]["workerSessionId"] == worker_session_id
    assert result["output_payload"]["profileKey"] == "worker.docs"
    assert result["result_payload"]["workerSessionId"] == worker_session_id
    assert result["result_payload"]["profileKey"] == "worker.docs"
    assert session_store.ended_sessions == [{"session_id": worker_session_id, "end_reason": TaskStatus.COMPLETED}]
    assert_legacy_task_run_id_not_exposed(result["output_payload"])
    assert_legacy_task_run_id_not_exposed(result["result_payload"])
    assert set(delegate_result["results"][0]) >= {
        "summary",
        "api_calls",
        "duration_seconds",
        "model",
        "exit_reason",
        "tokens",
        "tool_trace",
        "error",
    }


@pytest.mark.asyncio
async def test_delegate_runtime_keeps_sibling_workers_under_main_parent_session():
    launcher = FakeChildSessionLauncher(
        ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="worker summary",
        )
    )
    session_store = FakeWorkerSessionStore()
    runtime = DelegateRuntime(launcher, session_store=session_store)
    repository = FakeHandoffRepository()
    task = SimpleNamespace(
        task_run_id="task_parent",
        owner_key="user_1",
        session_key="session_1",
        input_payload={"transcript_session_id": "agent_session_parent"},
    )
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    for index in range(2):
        await runtime.apply(
            task=task,
            step=step,
            outcome={
                "child_session": {
                    "goal": f"관점 {index + 1} 검토",
                    "metadata": {"profile_key": "worker.default"},
                }
            },
            repository=repository,
        )

    assert [session["parent_session_id"] for session in session_store.created_sessions] == [
        "agent_session_parent",
        "agent_session_parent",
    ]


@pytest.mark.asyncio
async def test_delegate_runtime_applies_profile_defaults_and_toolset_intersection():
    launcher = FakeChildSessionLauncher(
        ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="worker summary",
        )
    )
    runtime = DelegateRuntime(launcher, session_store=FakeWorkerSessionStore())
    repository = FakeHandoffRepository()
    repository.agent_profiles["worker.profiled"] = {
        "profile_key": "worker.profiled",
        "profile_id": "profile_worker_profiled",
        "profile_version": 3,
        "agent_type": "worker",
        "config_snapshot": {
            "model": "gpt-profile",
            "toolsets": ["skills", "terminal"],
        },
        "delegation_policy": {
            "maxIterations": 22,
            "canDelegate": False,
        },
    }
    task = SimpleNamespace(task_run_id="task_parent", owner_key="user_1", session_key="session_1")
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    await runtime.apply(
        task=task,
        step=step,
        outcome={
            "child_session": {
                "goal": "profile 적용",
                "toolsets": ["terminal", "file", "delegation"],
                "metadata": {"profile_key": "worker.profiled"},
            }
        },
        repository=repository,
    )

    handoff = repository.created_handoffs[0]
    launched_payload = launcher.launched[0]["input_payload"]
    assert handoff["worker_profile_id"] == "profile_worker_profiled"
    assert handoff["worker_profile_version"] == 3
    assert handoff["input_payload"]["toolsets"] == ["terminal"]
    assert launched_payload["enabled_toolsets"] == ["terminal"]
    assert launched_payload["model"] == "gpt-profile"
    assert launched_payload["max_iterations"] == 22
    assert launched_payload["hard_timeout_seconds"] == 900


@pytest.mark.asyncio
async def test_delegate_runtime_propagates_gemini_provider_to_worker_payload():
    launcher = FakeChildSessionLauncher(
        ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="worker summary",
        )
    )
    session_store = FakeWorkerSessionStore()
    runtime = DelegateRuntime(launcher, session_store=session_store)
    repository = FakeHandoffRepository()
    repository.agent_profiles["worker.gemini"] = {
        "profile_key": "worker.gemini",
        "profile_id": "profile_worker_gemini",
        "profile_version": 2,
        "agent_type": "worker",
        "config_snapshot": {
            "model": "gemini-2.5-flash",
            "providerName": "gemini_api_key",
            "toolsets": ["terminal"],
        },
        "delegation_policy": {
            "maxIterations": 12,
        },
    }
    task = SimpleNamespace(task_run_id="task_parent", owner_key="user_1", session_key="session_1")
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    await runtime.apply(
        task=task,
        step=step,
        outcome={
            "child_session": {
                "goal": "Gemini worker 실행",
                "metadata": {"profile_key": "worker.gemini"},
            }
        },
        repository=repository,
    )

    created_session = session_store.created_sessions[0]
    assert created_session["model"] == "gemini-2.5-flash"
    assert created_session["metadata"]["provider_name"] == "gemini_api_key"

    handoff = repository.created_handoffs[0]
    assert handoff["input_payload"]["model"] == "gemini-2.5-flash"
    assert handoff["input_payload"]["provider_name"] == "gemini_api_key"

    launched_payload = launcher.launched[0]["input_payload"]
    assert launched_payload["model"] == "gemini-2.5-flash"
    assert launched_payload["provider_name"] == "gemini_api_key"
    assert launched_payload["providerName"] == "gemini_api_key"


@pytest.mark.asyncio
async def test_delegate_runtime_infers_gemini_provider_from_worker_model():
    launcher = FakeChildSessionLauncher(
        ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="worker summary",
        )
    )
    runtime = DelegateRuntime(launcher, session_store=FakeWorkerSessionStore())
    repository = FakeHandoffRepository()
    task = SimpleNamespace(task_run_id="task_parent", owner_key="user_1", session_key="session_1")
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    await runtime.apply(
        task=task,
        step=step,
        outcome={
            "child_session": {
                "goal": "Gemini 추론 worker",
                "model": "gemini-2.5-pro",
                "metadata": {"profile_key": "worker.default"},
            }
        },
        repository=repository,
    )

    launched_payload = launcher.launched[0]["input_payload"]
    assert launched_payload["model"] == "gemini-2.5-pro"
    assert launched_payload["provider_name"] == "gemini_api_key"


@pytest.mark.asyncio
async def test_delegate_runtime_applies_profile_hard_timeout_default():
    launcher = FakeChildSessionLauncher(
        ChildSessionLaunchResult(
            agent_id="agent_worker",
            status=TaskStatus.COMPLETED,
            summary="worker summary",
        )
    )
    runtime = DelegateRuntime(launcher, session_store=FakeWorkerSessionStore())
    repository = FakeHandoffRepository()
    repository.agent_profiles["worker.timeout"] = {
        "profile_key": "worker.timeout",
        "profile_id": "profile_worker_timeout",
        "profile_version": 2,
        "agent_type": "worker",
        "config_snapshot": {
            "toolsets": ["skills", "terminal", "file", "web"],
        },
        "delegation_policy": {
            "hardTimeoutSeconds": 1200,
            "maxIterations": 80,
        },
    }
    task = SimpleNamespace(task_run_id="task_parent", owner_key="user_1", session_key="session_1")
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    await runtime.apply(
        task=task,
        step=step,
        outcome={
            "child_session": {
                "goal": "profile timeout 적용",
                "toolsets": ["web"],
                "metadata": {"profile_key": "worker.timeout"},
            }
        },
        repository=repository,
    )

    handoff = repository.created_handoffs[0]
    launched_payload = launcher.launched[0]["input_payload"]
    assert handoff["input_payload"]["hard_timeout_seconds"] == 1200
    assert launched_payload["hardTimeoutSeconds"] == 1200
    assert launched_payload["enabled_toolsets"] == ["web"]


@pytest.mark.asyncio
async def test_delegate_runtime_completes_handoff_as_failed_when_launch_fails():
    launcher = FakeChildSessionLauncher(RuntimeError("launch unavailable"))
    runtime = DelegateRuntime(launcher)
    repository = FakeHandoffRepository()
    task = SimpleNamespace(task_run_id="task_parent", owner_key="user_1", session_key=None)
    step = SimpleNamespace(step_run_id="step_parent", detail_json={})

    result = await runtime.apply(
        task=task,
        step=step,
        outcome={
            "child_session": {
                "input_payload": {"prompt": "하위 작업"},
            }
        },
        repository=repository,
    )

    assert result["task_status"] == TaskStatus.FAILED
    assert repository.completed_handoffs[0][1]["status"] == "FAILED"
    assert "launch unavailable" in repository.completed_handoffs[0][1]["result_summary"]["error"]
