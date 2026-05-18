from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from app.api.http.work import (
    _enqueue_comment_followup_wake,
    _effective_comment_resume_requested,
    _list_descendant_works,
    _should_reopen_blocked_work_from_comment,
    _unresolved_blocker_work_ids,
)
from app.api.http.sessions import _dispatch_work_wake


class FakeWorkRepository:
    def __init__(self, *, relations, works):
        self._relations = relations
        self._works = works

    def list_relations(self, work_id: str):
        return [
            relation
            for relation in self._relations
            if relation.source_work_id == work_id or relation.target_work_id == work_id
        ]

    def get_work(self, work_id: str):
        return self._works.get(work_id)


class FakeWakeRepository:
    def __init__(self, work_item=None):
        self.work_item = work_item
        self.wakes = []
        self.completed = []

    def get_work(self, work_id: str):
        return self.work_item

    def enqueue_work_wake(self, wake):
        self.wakes.append(wake)
        return wake

    def complete_work_wake(self, wake_id: str, **kwargs):
        self.completed.append((wake_id, kwargs))
        return SimpleNamespace(wake_id=wake_id, **kwargs)


class FakeTreeRepository:
    def __init__(self, works):
        self.works = works

    def list_children(self, parent_id: str):
        return [work for work in self.works if work.parent_id == parent_id]


def relation(source: str, target: str, relation_type: str = "blocks"):
    return SimpleNamespace(source_work_id=source, target_work_id=target, relation_type=relation_type)


def work(status: str):
    return SimpleNamespace(status=status)


def test_unresolved_blocker_work_ids_ignores_done_blockers_only():
    repository = FakeWorkRepository(
        relations=[relation("blocker-1", "target-1"), relation("blocker-2", "target-1"), relation("target-1", "related-1", "related")],
        works={"blocker-1": work("done"), "blocker-2": work("cancelled")},
    )

    assert _unresolved_blocker_work_ids(repository, "target-1") == ["blocker-2"]


def test_unresolved_blocker_work_ids_returns_non_done_blockers():
    repository = FakeWorkRepository(
        relations=[
            relation("blocker-1", "target-1"),
            relation("blocker-2", "target-1"),
            relation("target-1", "other-1"),
        ],
        works={"blocker-1": work("todo")},
    )

    assert _unresolved_blocker_work_ids(repository, "target-1") == ["blocker-1", "blocker-2"]


def test_comment_resume_keeps_dependency_blocked_work_blocked():
    blocked = work("blocked")

    assert (
        _effective_comment_resume_requested(
            work=blocked,
            payload_resume=True,
            unresolved_blocker_ids=["blocker-1"],
        )
        is False
    )
    assert (
        _should_reopen_blocked_work_from_comment(
            work=blocked,
            unresolved_blocker_ids=["blocker-1"],
        )
        is False
    )


def test_comment_reopens_unblocked_blocked_work():
    blocked = work("blocked")

    assert (
        _effective_comment_resume_requested(
            work=blocked,
            payload_resume=True,
            unresolved_blocker_ids=[],
        )
        is True
    )
    assert (
        _should_reopen_blocked_work_from_comment(
            work=blocked,
            unresolved_blocker_ids=[],
        )
        is True
    )


def test_active_work_comment_queues_followup_wake():
    repository = FakeWakeRepository()
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(work_repository=repository)))

    _enqueue_comment_followup_wake(
        request,
        work=SimpleNamespace(work_id="work-1", active_run_id="task-active"),
        comment=SimpleNamespace(resume_requested=False),
    )

    assert len(repository.wakes) == 1
    assert repository.wakes[0].work_id == "work-1"
    assert repository.wakes[0].reason == "issue_commented"
    assert repository.wakes[0].status == "scheduled_retry"
    assert repository.wakes[0].requested_by_task_run_id == "task-active"


async def test_active_work_wake_retries_instead_of_skipping_immediately():
    repository = FakeWakeRepository(work_item=SimpleNamespace(active_run_id="task-active"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(work_repository=repository)))
    wake = SimpleNamespace(wake_id="wake-1", work_id="work-1", attempts=1)

    result = await _dispatch_work_wake(request, user=None, wake=wake)

    assert result.status == "scheduled_retry"
    assert repository.completed == [
        (
            "wake-1",
            {
                "status": "scheduled_retry",
                "last_error": "work already has an active run",
                "retry_delay_seconds": 30,
            },
        )
    ]


async def test_blocker_resolved_wake_coalesces_when_work_is_already_running():
    repository = FakeWakeRepository(work_item=SimpleNamespace(active_run_id="task-active"))
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(work_repository=repository)))
    wake = SimpleNamespace(wake_id="wake-1", work_id="work-1", attempts=1, reason="blockers_resolved")

    result = await _dispatch_work_wake(request, user=None, wake=wake)

    assert result.status == "skipped"
    assert repository.completed == [
        (
            "wake-1",
            {
                "status": "skipped",
                "last_error": "work already has an active run; wake coalesced",
            },
        )
    ]


async def test_blocker_resolved_wake_skips_when_work_advanced_after_wake_was_queued():
    wake_created_at = datetime(2026, 5, 18, 6, 17, tzinfo=timezone.utc)
    repository = FakeWakeRepository(
        work_item=SimpleNamespace(
            active_run_id=None,
            latest_run_id="task-parent-after-wake",
            updated_at=wake_created_at + timedelta(seconds=10),
            status="in_review",
            work_id="work-1",
        )
    )
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(work_repository=repository)))
    wake = SimpleNamespace(
        wake_id="wake-1",
        work_id="work-1",
        attempts=2,
        reason="blockers_resolved",
        requested_by_task_run_id="task-child",
        created_at=wake_created_at,
    )

    result = await _dispatch_work_wake(request, user=None, wake=wake)

    assert result.status == "skipped"
    assert repository.completed == [
        (
            "wake-1",
            {
                "status": "skipped",
                "last_error": "work already advanced after wake was queued",
            },
        )
    ]


def test_list_descendant_works_returns_nested_children_in_delete_order_base():
    parent = SimpleNamespace(work_id="parent", parent_id=None)
    first = SimpleNamespace(work_id="first", parent_id="parent")
    second = SimpleNamespace(work_id="second", parent_id="parent")
    grandchild = SimpleNamespace(work_id="grandchild", parent_id="first")
    repository = FakeTreeRepository([parent, first, second, grandchild])

    assert [work.work_id for work in _list_descendant_works(repository, "parent")] == [
        "first",
        "second",
        "grandchild",
    ]
