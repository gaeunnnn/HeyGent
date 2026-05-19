import asyncio
from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.core.time import utc_now
from app.domain.orchestration.agent.loop import TaskEngine
from app.domain.orchestration.contracts import OrchestrationRequest
from app.domain.orchestration.task_execution_supervisor import TaskExecutionSupervisor, TaskExecutionSupervisorConfig
from app.domain.tasks.models import TaskRun
from tests.fakes import InMemoryTaskRepository


@pytest.mark.asyncio
async def test_task_execution_supervisor_claims_and_executes_queued_task():
    repository = InMemoryTaskRepository()
    executed: list[str] = []
    completed: list[str] = []

    class FakeOrchestrator:
        async def enqueue_start(self, request: OrchestrationRequest):
            task = SimpleNamespace(
                task_run_id=request.task_run_id or "task-supervised",
                task_type="agent.loop",
                owner_key=request.owner_key,
                session_key=request.session_key,
                status="PENDING",
                input_payload=request.input_payload,
                result_payload={},
                todo_state={},
                wait_payload={},
                current_step_run_id=None,
                title="supervised",
                error_message=None,
                progress_summary=None,
                queue_status=None,
                claim_owner=None,
                queued_at=None,
                claimed_at=None,
                lease_expires_at=None,
                heartbeat_at=None,
                next_attempt_at=None,
                attempts=0,
                last_claim_error=None,
                revision=0,
                created_at=None,
                started_at=None,
                updated_at=None,
                ended_at=None,
            )
            return repository.create_pending_task(task)

        async def execute_claimed(self, task):
            executed.append(task.task_run_id)
            task.status = "COMPLETED"
            task.queue_status = "terminal"
            return repository.update_task(task)

    supervisor = TaskExecutionSupervisor(
        repository=repository,
        orchestrator=FakeOrchestrator(),
        config=TaskExecutionSupervisorConfig(worker_count=1, poll_interval_seconds=0.05),
        instance_id="test-supervisor",
    )
    await supervisor.start()
    try:
        await supervisor.submit(
            OrchestrationRequest(owner_key="42", session_key="session-1", input_payload={"prompt": "hi"}),
            on_complete=lambda task: _record_completion(completed, task.task_run_id),
        )
        for _ in range(20):
            if completed:
                break
            await asyncio.sleep(0.05)
    finally:
        await supervisor.stop()

    assert executed == ["task-supervised"]
    assert completed == ["task-supervised"]
    saved = repository.get_task("task-supervised")
    assert saved is not None
    assert saved.status == "COMPLETED"


async def _record_completion(target: list[str], task_run_id: str) -> None:
    target.append(task_run_id)


@pytest.mark.asyncio
async def test_task_engine_run_claimed_rejects_unclaimed_direct_task():
    repository = InMemoryTaskRepository()
    task = repository.create_direct_task(
        TaskRun(
            task_run_id="task-direct-ownership",
            task_type="agent.loop",
            owner_key="42",
            session_key="session-1",
            status="PENDING",
        )
    )
    engine = TaskEngine(
        repository=repository,
        broadcaster=None,
        approval_service=None,
        child_session_launcher=None,
        planner=None,
        tool_registry=None,
    )

    with pytest.raises(RuntimeError, match="not claimed"):
        await engine.run_claimed(task=task, handler=object())


@pytest.mark.asyncio
async def test_task_engine_run_claimed_allows_supervisor_claimed_task(monkeypatch):
    repository = InMemoryTaskRepository()
    repository.create_pending_task(
        TaskRun(
            task_run_id="task-claimed-ownership",
            task_type="agent.loop",
            owner_key="42",
            session_key="session-1",
            status="PENDING",
        )
    )
    task = repository.claim_next_task(claim_owner="worker-a", lease_seconds=30)
    assert task is not None
    engine = TaskEngine(
        repository=repository,
        broadcaster=None,
        approval_service=None,
        child_session_launcher=None,
        planner=None,
        tool_registry=None,
    )

    async def fake_execute_initial(*, task, handler, resume_payload):
        task.result_payload = {"ok": True}
        return task

    monkeypatch.setattr(engine, "_execute_initial", fake_execute_initial)

    result = await engine.run_claimed(task=task, handler=object())

    assert result.task_run_id == "task-claimed-ownership"
    assert result.result_payload == {"ok": True}


@pytest.mark.asyncio
async def test_task_execution_supervisor_does_not_fail_task_when_completion_callback_fails():
    repository = InMemoryTaskRepository()

    class FakeOrchestrator:
        async def enqueue_start(self, request: OrchestrationRequest):
            task = SimpleNamespace(
                task_run_id=request.task_run_id or "task-callback-fails",
                task_type="agent.loop",
                owner_key=request.owner_key,
                session_key=request.session_key,
                status="PENDING",
                input_payload=request.input_payload,
                result_payload={},
                todo_state={},
                wait_payload={},
                current_step_run_id=None,
                title="supervised",
                error_message=None,
                progress_summary=None,
                queue_status=None,
                claim_owner=None,
                queued_at=None,
                claimed_at=None,
                lease_expires_at=None,
                heartbeat_at=None,
                next_attempt_at=None,
                attempts=0,
                last_claim_error=None,
                revision=0,
                created_at=None,
                started_at=None,
                updated_at=None,
                ended_at=None,
            )
            return repository.create_pending_task(task)

        async def execute_claimed(self, task):
            task.status = "COMPLETED"
            task.queue_status = "terminal"
            return repository.update_task(task)

    supervisor = TaskExecutionSupervisor(
        repository=repository,
        orchestrator=FakeOrchestrator(),
        config=TaskExecutionSupervisorConfig(worker_count=1, poll_interval_seconds=0.05),
        instance_id="test-supervisor",
    )
    await supervisor.start()
    try:
        await supervisor.submit(
            OrchestrationRequest(owner_key="42", session_key="session-1", input_payload={"prompt": "hi"}),
            on_complete=_raise_completion_error,
        )
        for _ in range(20):
            saved = repository.get_task("task-callback-fails")
            if saved is not None and saved.status == "COMPLETED":
                break
            await asyncio.sleep(0.05)
    finally:
        await supervisor.stop()

    saved = repository.get_task("task-callback-fails")
    assert saved is not None
    assert saved.status == "COMPLETED"
    assert saved.queue_status == "terminal"
    assert saved.last_claim_error is None


async def _raise_completion_error(task) -> None:
    raise RuntimeError("websocket is already gone")


@pytest.mark.asyncio
async def test_task_execution_supervisor_recovers_stale_running_tasks_before_claiming():
    repository = InMemoryTaskRepository()
    repository.create_task(
        TaskRun(
            task_run_id="task-supervisor-stale",
            task_type="agent.loop",
            owner_key="42",
            session_key="session-1",
            status="RUNNING",
            queue_status="running",
            claim_owner="worker-a",
            updated_at=utc_now() - timedelta(minutes=20),
        )
    )
    repository.tasks["task-supervisor-stale"].updated_at = utc_now() - timedelta(minutes=20)

    class FakeOrchestrator:
        async def enqueue_start(self, request: OrchestrationRequest):
            raise AssertionError("not used")

        async def execute_claimed(self, task):
            raise AssertionError("stale task must not be executed")

    supervisor = TaskExecutionSupervisor(
        repository=repository,
        orchestrator=FakeOrchestrator(),
        config=TaskExecutionSupervisorConfig(worker_count=1, poll_interval_seconds=0.05),
        instance_id="test-supervisor",
    )
    await supervisor.start()
    try:
        for _ in range(20):
            saved = repository.get_task("task-supervisor-stale")
            if saved is not None and saved.status == "FAILED":
                break
            await asyncio.sleep(0.05)
    finally:
        await supervisor.stop()

    saved = repository.get_task("task-supervisor-stale")
    assert saved is not None
    assert saved.status == "FAILED"
    assert saved.queue_status == "terminal"


@pytest.mark.asyncio
async def test_task_execution_supervisor_throttles_stale_recovery_when_idle():
    class CountingRepository(InMemoryTaskRepository):
        def __init__(self) -> None:
            super().__init__()
            self.recover_calls = 0

        def recover_stale_task_runs(self, *, orphan_after_seconds: int = 300, limit: int = 100):
            self.recover_calls += 1
            return super().recover_stale_task_runs(orphan_after_seconds=orphan_after_seconds, limit=limit)

    repository = CountingRepository()

    class FakeOrchestrator:
        async def enqueue_start(self, request: OrchestrationRequest):
            raise AssertionError("not used")

        async def execute_claimed(self, task):
            raise AssertionError("not used")

    supervisor = TaskExecutionSupervisor(
        repository=repository,
        orchestrator=FakeOrchestrator(),
        config=TaskExecutionSupervisorConfig(worker_count=1, poll_interval_seconds=0.05, recovery_interval_seconds=60),
        instance_id="test-supervisor",
    )
    await supervisor.start()
    try:
        await asyncio.sleep(0.22)
    finally:
        await supervisor.stop()

    assert repository.recover_calls == 1
