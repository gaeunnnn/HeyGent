from __future__ import annotations

import asyncio
from copy import deepcopy

from app.contracts.task.task_status import TaskStatus
from app.domain.orchestration.agent.loop import TaskEngine
from app.domain.orchestration.runtime_planning.planner import Planner
from app.domain.orchestration.prompts.skill_prompt import SkillLoader
from app.domain.tasks.models import TaskRun
from app.domain.work.models import WorkItem, WorkRelation, WorkRunLink
from app.tools.contracts import HandlerSpec
from tests.fakes import InMemoryAgentRepository, InMemorySkillRepository, InMemoryTaskRepository


class DummyBroadcaster:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> None:
        self.events.append(event)


class DummyToolRegistry:
    def resolve(self):
        return None


class FakeWorkRepository:
    def __init__(self) -> None:
        self.items: dict[str, WorkItem] = {}
        self.runs: dict[tuple[str, str], WorkRunLink] = {}
        self.relations: list[WorkRelation] = []
        self.client_requests: dict[tuple[str, str], str] = {}
        self.label_links: list[tuple[str, str, str, tuple[str, ...]]] = []
        self.next_number = 0

    def next_identifier(self, session_id: str) -> str:
        self.next_number += 1
        return f"TASK-{self.next_number}"

    def create_work(self, work: WorkItem, *, client_request_id: str | None = None) -> WorkItem:
        saved = deepcopy(work)
        self.items[saved.work_id] = saved
        if client_request_id:
            self.client_requests[(saved.session_id, client_request_id)] = saved.work_id
        return saved

    def get_work(self, work_id: str) -> WorkItem | None:
        return self.items.get(work_id)

    def get_work_by_client_request_id(self, session_id: str, client_request_id: str) -> WorkItem | None:
        work_id = self.client_requests.get((session_id, client_request_id))
        return self.items.get(work_id) if work_id else None

    def set_label_links_by_names(self, work_id: str, *, session_id: str, owner_key: str, label_names: list[str]) -> list[str]:
        self.label_links.append((work_id, session_id, owner_key, tuple(label_names)))
        return label_names

    def inherit_parent_labels(self, work_id: str, parent_id: str) -> list[str]:
        return []

    def link_run(self, work_id: str, task_run_id: str, *, run_kind: str, status: str) -> WorkRunLink:
        link = WorkRunLink(work_id=work_id, task_run_id=task_run_id, run_kind=run_kind, status=status)
        self.runs[(work_id, task_run_id)] = link
        work = self.items[work_id]
        self.items[work_id] = WorkItem(**{**_work_dict(work), "active_run_id": task_run_id, "latest_run_id": task_run_id})
        return link

    def context_preview(self, work_id: str) -> dict:
        work = self.items[work_id]
        return {"title": work.title, "labels": [], "commentsIncluded": 0, "recentRunsIncluded": 1, "promptPreview": work.execution_instruction or ""}

    def update_run_status(self, work_id: str, task_run_id: str, status: str) -> WorkRunLink | None:
        link = self.runs.get((work_id, task_run_id))
        if link is None:
            return None
        updated = WorkRunLink(work_id=work_id, task_run_id=task_run_id, run_kind=link.run_kind, status=status)
        self.runs[(work_id, task_run_id)] = updated
        return updated

    def update_status(self, work_id: str, status: str) -> WorkItem:
        work = self.items[work_id]
        updated = WorkItem(**{**_work_dict(work), "status": status})
        self.items[work_id] = updated
        return updated

    def add_comment(self, comment):
        return comment

    def add_relation(
        self,
        *,
        source_work_id: str,
        target_work_id: str,
        relation_type: str,
    ) -> WorkRelation:
        relation = WorkRelation(
            source_work_id=source_work_id,
            target_work_id=target_work_id,
            relation_type=relation_type,
        )
        self.relations.append(relation)
        return relation

    def list_relations(self, work_id: str) -> list[WorkRelation]:
        return [
            relation
            for relation in self.relations
            if relation.source_work_id == work_id or relation.target_work_id == work_id
        ]


def test_successful_skill_execute_creates_work_and_links_current_task_run():
    task_repository = InMemoryTaskRepository()
    work_repository = FakeWorkRepository()
    broadcaster = DummyBroadcaster()
    engine = _engine(task_repository=task_repository, work_repository=work_repository, broadcaster=broadcaster)
    task = _task()
    task_repository.create_task(task)

    sink = engine._build_progress_sink(task=task, step=None)
    asyncio.run(
        sink(
            event_type="tool.completed",
            payload={
                "tool_name": "skill.execute",
                "input": {"skill_name": "korea-weather"},
                "result": {"ok": True, "skill_name": "korea-weather", "content": "# Weather"},
            },
        )
    )

    assert len(work_repository.items) == 1
    work = next(iter(work_repository.items.values()))
    assert work.source == "skill_use"
    assert work.title == "korea-weather 스킬 실행"
    assert work.metadata["triggerTool"] == "skill.execute"
    assert work_repository.runs[(work.work_id, task.task_run_id)].status == "RUNNING"
    saved_task = task_repository.get_task(task.task_run_id)
    assert saved_task is not None
    assert saved_task.input_payload["workId"] == work.work_id
    assert [event.event_type for event in broadcaster.events] == ["work.linked", "tool.completed"]


def test_skill_list_only_does_not_create_work():
    task_repository = InMemoryTaskRepository()
    work_repository = FakeWorkRepository()
    engine = _engine(task_repository=task_repository, work_repository=work_repository)
    task = _task()
    task_repository.create_task(task)

    sink = engine._build_progress_sink(task=task, step=None)
    asyncio.run(
        sink(
            event_type="tool.completed",
            payload={
                "tool_name": "skills.list",
                "result": {"count": 1, "items": ["korea-weather"]},
            },
        )
    )

    assert work_repository.items == {}
    assert "workId" not in task.input_payload


def test_existing_work_context_does_not_create_second_work():
    task_repository = InMemoryTaskRepository()
    work_repository = FakeWorkRepository()
    engine = _engine(task_repository=task_repository, work_repository=work_repository)
    task = _task(input_payload={"prompt": "날씨 알려줘", "workId": "work-existing"})
    task_repository.create_task(task)

    sink = engine._build_progress_sink(task=task, step=None)
    asyncio.run(
        sink(
            event_type="tool.completed",
            payload={
                "tool_name": "skill.execute",
                "input": {"skill_name": "korea-weather"},
                "result": {"ok": True, "skill_name": "korea-weather"},
            },
        )
    )

    assert work_repository.items == {}
    assert task.input_payload["workId"] == "work-existing"


def test_session_agent_child_input_includes_profile_skill_names():
    task_repository = InMemoryTaskRepository()
    work_repository = FakeWorkRepository()
    agent_repository = InMemoryAgentRepository()
    skill_repository = InMemorySkillRepository()
    skill_repository.sync_builtin_catalog(SkillLoader().load_builtin())
    profile = agent_repository.create_session_agent_from_template(
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        template_key="k_services",
    )
    engine = _engine(
        task_repository=task_repository,
        work_repository=work_repository,
        agent_repository=agent_repository,
        skill_repository=skill_repository,
    )
    work = WorkItem(
        work_id="work-k",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="분실물 확인",
        description="강남역 분실물 확인",
        status="in_progress",
        assignee_agent_id=profile["profile_id"],
        execution_instruction="강남역에서 잃어버린 카드지갑을 찾는 경로를 정리해줘.",
    )
    work_repository.create_work(work)
    child_input = engine._build_session_agent_work_input(
        parent_task=_task(input_payload={"model": "gpt-5.4"}),
        work=work,
    )

    assert child_input["targetAgentProfile"]["configSnapshot"]["name"] == "K-에이전트"
    assert "subway-lost-property" in child_input["targetAgentProfile"]["configSnapshot"]["skills"]
    assert "subway-lost-property" in child_input["enabledSkillNames"]
    assert set(child_input["enabledSkillNames"]).issubset(
        set(child_input["targetAgentProfile"]["configSnapshot"]["skills"])
    )


def test_session_agent_child_input_keeps_parent_prototype_session_binding():
    engine = _engine(
        task_repository=InMemoryTaskRepository(),
        work_repository=FakeWorkRepository(),
    )
    work = WorkItem(
        work_id="work-design",
        identifier="TASK-1",
        session_id="session-ui",
        owner_key="7",
        owner_user_id=7,
        title="날씨 화면 제작",
        description="부산 날씨 화면을 만든다.",
        status="in_progress",
        execution_instruction="부산 날씨 화면을 React 프로토타입으로 만들어줘.",
    )
    engine.work_repository.create_work(work)

    child_input = engine._build_session_agent_work_input(
        parent_task=_task(
            input_payload={
                "model": "gpt-5.4",
                "sessionId": "session-ui",
                "promptMessageId": "msg-user",
            }
        ),
        work=work,
    )

    assert child_input["sessionId"] == "session-ui"
    assert child_input["promptMessageId"] == "msg-user"


def test_workflow_child_input_includes_completed_blocker_result():
    task_repository = InMemoryTaskRepository()
    work_repository = FakeWorkRepository()
    engine = _engine(
        task_repository=task_repository,
        work_repository=work_repository,
    )
    parent_work = WorkItem(
        work_id="work-parent",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="부모 작업",
        description="첫 결과를 바탕으로 두 번째 결과를 만든다.",
        status="in_progress",
        assignee_agent_id="CEO",
    )
    research_work = WorkItem(
        work_id="work-research",
        identifier="TASK-2",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="짧은 조사 요약",
        description="삼성 AI 전략을 요약한다.",
        status="done",
        assignee_agent_id="agent-research",
        parent_id=parent_work.work_id,
        latest_run_id="task-research",
    )
    screen_work = WorkItem(
        work_id="work-screen",
        identifier="TASK-3",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="요약 기반 화면 구성",
        description="앞선 요약을 바탕으로 화면 섹션을 구성한다.",
        status="todo",
        assignee_agent_id="agent-ux",
        parent_id=parent_work.work_id,
        execution_instruction="앞선 요약을 바탕으로 간단한 화면 섹션 3개를 텍스트로 구성한다.",
    )
    work_repository.create_work(parent_work)
    work_repository.create_work(research_work)
    work_repository.create_work(screen_work)
    work_repository.add_relation(
        source_work_id=research_work.work_id,
        target_work_id=screen_work.work_id,
        relation_type="blocks",
    )
    task_repository.create_task(
        TaskRun(
            task_run_id="task-research",
            task_type="agent.loop",
            owner_key="7",
            session_key="session-1",
            status=TaskStatus.COMPLETED,
            result_payload={
                "text": "- 온디바이스 AI 확대\n- AI 반도체 인프라 강화\n- 연결된 AI 경험 확대",
            },
        )
    )

    child_input = engine._build_session_agent_work_input(
        parent_task=_task(
            input_payload={
                "workflowExecution": {
                    "mode": "strict_reuse_children",
                    "rootWorkId": parent_work.work_id,
                    "childWorkIds": [research_work.work_id, screen_work.work_id],
                    "childrenBySlotKey": {"research": research_work.work_id, "screen": screen_work.work_id},
                },
            }
        ),
        work=screen_work,
    )

    assert "## 선행 하위 작업 결과" in child_input["prompt"]
    assert "TASK-2 세션 에이전트 실행 결과(COMPLETED)" in child_input["prompt"]
    assert "온디바이스 AI 확대" in child_input["prompt"]
    assert child_input["workflowPredecessorResults"][0]["workId"] == research_work.work_id


def test_session_agent_parent_update_exposes_materialized_child_task_run():
    task_repository = InMemoryTaskRepository()
    work_repository = FakeWorkRepository()
    agent_repository = InMemoryAgentRepository()
    profile = agent_repository.create_session_agent_from_template(
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        template_key="k_services",
    )
    broadcaster = DummyBroadcaster()
    engine = _engine(
        task_repository=task_repository,
        work_repository=work_repository,
        broadcaster=broadcaster,
        agent_repository=agent_repository,
        planner=Planner(),
    )
    parent_task = _task(input_payload={"prompt": "지갑 잃어버렸어", "model": "gpt-5.4"})
    parent_task.status = TaskStatus.RUNNING
    task_repository.create_task(parent_task)
    step = engine.planner.materialize_runtime_step(
        task=parent_task,
        handler=_CompletingHandler(),
        input_payload=parent_task.input_payload,
        step_order=1,
    )
    step.title = "분실물 대응 배정"
    step.status = "RUNNING"
    task_repository.create_step(step)
    parent_task.current_step_run_id = step.step_run_id
    task_repository.update_task(parent_task)

    child_work = WorkItem(
        work_id="work-child",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="강남역 분실 지갑 대응",
        description="강남역에서 잃어버린 지갑 대응",
        status="todo",
        assignee_agent_id=profile["profile_id"],
        parent_id="work-parent",
        execution_instruction="강남역 지갑 분실 대응 순서를 정리해줘.",
    )
    work_repository.create_work(child_work)
    progress_sink = engine._build_progress_sink(task=parent_task, step=step)
    executor = engine._build_session_agent_work_executor(
        task=parent_task,
        handler=_CompletingHandler(),
        progress_sink=progress_sink,
    )

    result = asyncio.run(
        executor(
            child_work={"workId": child_work.work_id},
            tool_call_id="tool-call-1",
            args={},
            accepted_result={"ok": True},
        )
    )

    started_event = next(
        event
        for event in broadcaster.events
        if event.task_run_id == parent_task.task_run_id
        and event.event_type == "step.updated"
        and event.payload.get("reason") == "session_agent_work.started"
    )
    child_task_run_id = started_event.payload["childTaskRunId"]

    assert result["taskRunId"] == child_task_run_id
    assert started_event.payload["childWorkId"] == child_work.work_id
    assert started_event.payload["profileId"] == profile["profile_id"]
    assert task_repository.get_task(child_task_run_id) is not None
    event_order = [(event.task_run_id, event.event_type) for event in broadcaster.events]
    assert event_order.index((child_task_run_id, "task.created")) < event_order.index((parent_task.task_run_id, "step.updated"))


def _engine(
    *,
    task_repository: InMemoryTaskRepository,
    work_repository: FakeWorkRepository,
    broadcaster: DummyBroadcaster | None = None,
    agent_repository: InMemoryAgentRepository | None = None,
    skill_repository: InMemorySkillRepository | None = None,
    planner: Planner | None = None,
) -> TaskEngine:
    return TaskEngine(
        task_repository,
        broadcaster or DummyBroadcaster(),
        approval_service=None,
        child_session_launcher=None,
        planner=planner,
        tool_registry=DummyToolRegistry(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        skill_repository=skill_repository,
    )


class _CompletingHandler:
    spec = HandlerSpec(
        task_type="agent.loop",
        task_title="에이전트 실행",
        step_type="agent.loop.execute",
        step_title="에이전트 실행",
    )

    async def execute_async(self, **kwargs):
        return {
            "task_status": "COMPLETED",
            "step_status": "COMPLETED",
            "result_payload": {
                "workDisposition": {
                    "status": "done",
                    "summary": "분실 대응 순서를 정리했습니다.",
                }
            },
            "summary_message": "분실 대응 순서를 정리했습니다.",
        }


def _task(input_payload: dict | None = None) -> TaskRun:
    return TaskRun(
        task_run_id="task-skill",
        task_type="agent.loop",
        owner_key="7",
        session_key="session-1",
        status="RUNNING",
        title="날씨 질문",
        input_payload=input_payload or {"prompt": "서울 날씨 알려줘"},
    )


def _work_dict(work: WorkItem) -> dict:
    return {field: getattr(work, field) for field in work.__dataclass_fields__}
