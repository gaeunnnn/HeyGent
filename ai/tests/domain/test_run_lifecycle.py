from __future__ import annotations

from datetime import timedelta

from app.core.time import utc_now
from app.domain.orchestration.run_lifecycle import classify_task_run_liveness
from app.domain.tasks.models import TaskRun


def test_liveness_marks_recent_claimed_running_task_as_blocking():
    now = utc_now()
    task = TaskRun(
        task_run_id="task_live_claim",
        task_type="agent.loop",
        owner_key="owner-1",
        status="RUNNING",
        queue_status="running",
        claim_owner="worker-a",
        lease_expires_at=now + timedelta(seconds=30),
        heartbeat_at=now - timedelta(seconds=5),
        updated_at=now - timedelta(seconds=5),
    )

    liveness = classify_task_run_liveness(task, now=now)

    assert liveness.state == "live"
    assert liveness.blocks_session is True
    assert liveness.should_recover is False


def test_liveness_keeps_direct_running_task_without_claim_owner_live():
    now = utc_now()
    task = TaskRun(
        task_run_id="task_direct_no_claim",
        task_type="agent.loop",
        owner_key="owner-1",
        status="RUNNING",
        queue_status="running",
        claim_owner=None,
        lease_expires_at=None,
        heartbeat_at=None,
        updated_at=now - timedelta(minutes=20),
    )

    liveness = classify_task_run_liveness(task, now=now, orphan_after_seconds=300)

    assert liveness.state == "live"
    assert liveness.blocks_session is True
    assert liveness.should_recover is False
    assert liveness.reason == "direct_run_without_supervisor_claim"


def test_liveness_marks_worker_running_task_without_claim_signal_as_orphaned_after_timeout():
    now = utc_now()
    task = TaskRun(
        task_run_id="task_orphan_worker_claim",
        task_type="agent.loop",
        owner_key="owner-1",
        status="RUNNING",
        queue_status="running",
        claim_owner="worker-a",
        lease_expires_at=None,
        heartbeat_at=None,
        updated_at=now - timedelta(minutes=20),
    )

    liveness = classify_task_run_liveness(task, now=now, orphan_after_seconds=300)

    assert liveness.state == "orphaned"
    assert liveness.blocks_session is False
    assert liveness.should_recover is True


def test_liveness_keeps_waiting_task_blocking_even_without_lease():
    now = utc_now()
    task = TaskRun(
        task_run_id="task_waiting_approval",
        task_type="agent.loop",
        owner_key="owner-1",
        status="WAITING",
        queue_status=None,
        lease_expires_at=None,
        heartbeat_at=None,
        updated_at=now - timedelta(hours=1),
    )

    liveness = classify_task_run_liveness(task, now=now)

    assert liveness.state == "waiting"
    assert liveness.blocks_session is True
    assert liveness.should_recover is False
