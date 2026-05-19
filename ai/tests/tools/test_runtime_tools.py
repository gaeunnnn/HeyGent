import json
import sys
from copy import deepcopy

from app.domain.work.models import WorkComment, WorkItem, WorkRelation, WorkRunLink
from app.domain.orchestration.prompts.skill_prompt import SkillLoader, SkillRegistry
from app.domain.orchestration.agent.tool_result_store import store_raw_tool_result
from app.domain.orchestration.runtime_planning.todo_state import (
    apply_tool_results_to_todo_state,
    build_task_todo_payload,
)
from app.tools.file import file_tools
from app.tools.runtime.local_tool_runtime import LocalToolRuntime
from app.tools.runtime.toolsets import list_runtime_toolsets, resolve_runtime_tool_names


class DummySessionStore:
    pass


class FakeRuntimeWorkRepository:
    def __init__(self) -> None:
        self.items: dict[str, WorkItem] = {}
        self.client_request_ids: dict[tuple[str, str], str] = {}
        self.comments: list[WorkComment] = []
        self.relations: list[WorkRelation] = []
        self.runs: dict[tuple[str, str], WorkRunLink] = {}
        self.next_number = 1

    def next_identifier(self, session_id: str) -> str:
        self.next_number += 1
        return f"TASK-{self.next_number}"

    def create_work(self, work: WorkItem, *, client_request_id: str | None = None) -> WorkItem:
        saved = deepcopy(work)
        self.items[saved.work_id] = saved
        if client_request_id:
            self.client_request_ids[(saved.session_id, client_request_id)] = saved.work_id
        return saved

    def get_work(self, work_id: str) -> WorkItem | None:
        return self.items.get(work_id)

    def get_work_by_client_request_id(
        self,
        session_id: str,
        client_request_id: str,
    ) -> WorkItem | None:
        work_id = self.client_request_ids.get((session_id, client_request_id))
        return self.items.get(work_id) if work_id else None

    def set_label_links_by_names(
        self,
        work_id: str,
        *,
        session_id: str,
        owner_key: str,
        label_names: list[str],
    ) -> list[str]:
        return label_names

    def inherit_parent_labels(self, work_id: str, parent_id: str) -> list[str]:
        return []

    def add_comment(self, comment: WorkComment) -> WorkComment:
        self.comments.append(comment)
        return comment

    def update_status(self, work_id: str, status: str) -> WorkItem:
        work = self.items[work_id]
        self.items[work_id] = WorkItem(**{**_work_dict(work), "status": status})
        return self.items[work_id]

    def link_run(self, work_id: str, task_run_id: str, *, run_kind: str, status: str) -> WorkRunLink:
        link = WorkRunLink(work_id=work_id, task_run_id=task_run_id, run_kind=run_kind, status=status)
        self.runs[(work_id, task_run_id)] = link
        active_run_id = None if status in {"COMPLETED", "FAILED", "CANCELED"} else task_run_id
        work = self.items[work_id]
        if work.active_run_id is None or work.active_run_id == task_run_id:
            self.items[work_id] = WorkItem(**{**_work_dict(work), "active_run_id": active_run_id, "latest_run_id": task_run_id})
        return link

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


class FakeRuntimeAgentRepository:
    def __init__(self, profile: dict) -> None:
        self.profile = profile

    def list_session_agents(self, *, session_id: str, owner_key: str) -> list[dict]:
        return [self.profile]

    def get_session_agent(self, *, profile_id: str, owner_key: str) -> dict | None:
        if profile_id == self.profile["profile_id"]:
            return self.profile
        return None


class SearchRecordingSessionStore:
    def __init__(self) -> None:
        self.calls = []

    def search_transcript_sessions(self, query, *, owner_key, limit=10):
        self.calls.append({"query": query, "owner_key": owner_key, "limit": limit})
        return [{"id": "session_match", "owner_key": owner_key}]


def _work_dict(work: WorkItem) -> dict:
    return {field: getattr(work, field) for field in WorkItem.__dataclass_fields__}


def test_runtime_exposes_todo_schema_without_legacy_write_name():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("planning",))

    schema_by_name = {definition["name"]: definition["schema"] for definition in definitions}
    assert [definition["name"] for definition in definitions] == ["todo"]
    assert schema_by_name["todo"]["name"] == "todo"
    assert "todos" in schema_by_name["todo"]["parameters"]["properties"]


def test_runtime_exposes_terminal_argument_schema():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("terminal",))
    terminal_schema = next(item["schema"] for item in definitions if item["name"] == "terminal.run")

    properties = terminal_schema["parameters"]["properties"]
    assert "command" in properties
    assert "argv" in properties
    assert "Provide at least one" in terminal_schema["description"]


def test_runtime_exposes_file_tool_definitions_from_file_tool_module():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("file",))

    assert [definition["name"] for definition in definitions] == [
        "patch",
        "read_file",
        "search_files",
        "write_file",
    ]
    schema_by_name = {definition["name"]: definition["schema"] for definition in definitions}
    assert schema_by_name["read_file"]["parameters"]["properties"]["path"]["type"] == "string"
    assert schema_by_name["write_file"]["parameters"]["properties"]["content"]["type"] == "string"
    assert schema_by_name["search_files"]["parameters"]["properties"]["query"]["type"] == "string"


def test_session_search_requires_bound_owner_and_scopes_query():
    store = SearchRecordingSessionStore()
    unbound = LocalToolRuntime(skill_registry=object(), session_store=store)
    bound = unbound.bind_request_context(owner_key="owner-a")

    denied = unbound.run_call(name="session.search", args={"query": "검색"}, enabled_toolsets=("session",))
    result = bound.run_call(name="session.search", args={"query": "검색", "owner_key": "spoof"}, enabled_toolsets=("session",))

    assert denied["ok"] is False
    assert denied["error"]["code"] == "owner_required"
    assert result["count"] == 1
    assert store.calls == [{"query": "검색", "owner_key": "owner-a", "limit": 5}]


def test_file_toolset_is_available_for_coding_and_local_core_but_not_safe():
    file_tool_names = {"read_file", "write_file", "patch", "search_files"}

    assert file_tool_names <= resolve_runtime_tool_names(("file",))
    assert file_tool_names <= resolve_runtime_tool_names(("coding",))
    assert file_tool_names <= resolve_runtime_tool_names(("local-core",))
    assert "delegate_task" not in resolve_runtime_tool_names(("local-core",))
    assert file_tool_names.isdisjoint(resolve_runtime_tool_names(("safe",)))


def test_runtime_exposes_heygent_web_tool_definitions(monkeypatch):
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("web",))

    assert [definition["name"] for definition in definitions] == ["http_get"]
    schema_by_name = {definition["name"]: definition["schema"] for definition in definitions}
    assert schema_by_name["http_get"]["parameters"]["properties"]["url"]["type"] == "string"


def test_runtime_exposes_tool_result_reader_only_for_tool_result_toolset():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("tool-result",))

    assert [definition["name"] for definition in definitions] == ["tool_result.read"]
    assert resolve_runtime_tool_names(("tool-result",)) == {"tool_result.read"}
    assert "tool_result.read" not in resolve_runtime_tool_names(("web",))
    assert "tool_result.read" not in resolve_runtime_tool_names(("local-core",))


def test_runtime_executes_tool_result_reader(monkeypatch, tmp_path):
    monkeypatch.setenv("HEYGENT_TOOL_RESULT_STORE_DIR", str(tmp_path / "tool-results"))
    raw_meta = store_raw_tool_result(
        tool_name="http_get",
        tool_call_id="call_raw",
        task_run_id="task_raw",
        result={"ok": True, "content": "x" * 25_000},
    )
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="tool_result.read",
        args={"raw_ref": raw_meta["raw_ref"], "offset": 0, "limit": 600},
        enabled_toolsets=("tool-result",),
    )

    assert result["ok"] is True
    assert result["raw_ref"] == raw_meta["raw_ref"]
    assert result["returned_chars"] == 600
    assert result["has_more"] is True
    assert len(result["content"]) == 600


def test_runtime_does_not_expose_removed_web_search_tool(monkeypatch):
    for key in ("EXA_API_KEY", "PARALLEL_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY", "HEYGENT_OPENAI_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("web",))

    assert [definition["name"] for definition in definitions] == ["http_get"]


def test_runtime_exposes_notion_execute_only_for_notion_toolset():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("notion",))

    assert [definition["name"] for definition in definitions] == ["notion.execute"]
    schema = definitions[0]["schema"]
    assert "commands" in schema["parameters"]["properties"]
    assert "notion.execute" not in resolve_runtime_tool_names(("local-core",))


def test_runtime_exposes_health_execute_only_for_health_toolset():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("health",))

    assert [definition["name"] for definition in definitions] == ["health.execute"]
    schema = definitions[0]["schema"]
    assert "commands" in schema["parameters"]["properties"]
    assert "health.execute" not in resolve_runtime_tool_names(("local-core",))


def test_notion_runtime_binds_owner_user_id_and_ignores_model_user_id(monkeypatch):
    captured = {}

    def fake_execute_notion_handler(args):
        captured.update(args)
        return {"ok": True, "results": []}

    from app.tools.notion import notion_tool

    monkeypatch.setattr(notion_tool, "execute_notion_handler", fake_execute_notion_handler)
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore()).bind_request_context(owner_key="7")

    result = runtime.run_call(
        name="notion.execute",
        args={
            "userId": 999,
            "commands": [
                {
                    "method": "POST",
                    "endpoint": "/v1/search",
                    "params": {"query": "테스트용입니다"},
                }
            ],
        },
        enabled_toolsets=("notion",),
    )

    assert result["ok"] is True
    assert captured["_trusted_user_id"] == "7"
    assert "userId" not in captured


def test_health_runtime_binds_owner_user_id_and_ignores_model_user_id(monkeypatch):
    captured = {}

    def fake_execute_health_handler(args):
        captured.update(args)
        return {"ok": True, "results": []}

    from app.tools.health import health_tool

    monkeypatch.setattr(health_tool, "execute_health_handler", fake_execute_health_handler)
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore()).bind_request_context(owner_key="7")

    result = runtime.run_call(
        name="health.execute",
        args={
            "userId": 999,
            "commands": [
                {
                    "method": "GET",
                    "endpoint": "/api/v1/health/me/latest",
                }
            ],
        },
        enabled_toolsets=("health",),
    )

    assert result["ok"] is True
    assert captured["_trusted_user_id"] == "7"
    assert "userId" not in captured


def test_skill_catalog_descriptions_remain_available_to_prompt_builder():
    registry = SkillRegistry()
    registry.register_many(SkillLoader().load_builtin())

    descriptions = {item["name"]: item["description"] for item in registry.catalog_items()}

    assert "korea-weather" in descriptions
    assert "한국 날씨를 기상청 단기예보 조회서비스" in descriptions["korea-weather"]


def test_skills_toolset_exposes_runtime_skill_readers():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("skills",))

    names = {definition["name"] for definition in definitions}
    assert {"skills.list", "skills.read", "skills.read_file", "skill.execute"}.issubset(names)


def test_disabled_skill_readers_are_unavailable_even_with_enabled_skill_context():
    registry = SkillRegistry()
    registry.register_many(
        [
            {"name": "korea-weather", "description": "한국 날씨 조회", "body": "# Weather"},
            {"name": "zipcode-search", "description": "우편번호 조회", "body": "# Zipcode"},
        ]
    )
    runtime = LocalToolRuntime(
        skill_registry=registry,
        session_store=DummySessionStore(),
        runtime_context={"enabledSkillNames": ["korea-weather"]},
    )

    listed = runtime.run_call(name="skills.list", args={}, enabled_toolsets=("skills",))
    read_result = runtime.run_call(
        name="skills.read",
        args={"skill_name": "korea-weather"},
        enabled_toolsets=("skills",),
    )
    file_result = runtime.run_call(
        name="skills.read",
        args={"skill_name": "zipcode-search"},
        enabled_toolsets=("skills",),
    )

    assert listed["count"] == 1
    assert listed["items"] == ["korea-weather"]
    assert read_result["name"] == "korea-weather"
    assert read_result["body"] == "# Weather"
    assert file_result["ok"] is False
    assert file_result["error"]["code"] == "skill_disabled"


def test_web_is_available_in_local_core_and_safe_without_removed_extract_or_browser_tools():
    assert resolve_runtime_tool_names(("web",)) == {"http_get"}
    assert "http_get" in resolve_runtime_tool_names(("local-core",))
    assert "http_get" in resolve_runtime_tool_names(("safe",))
    assert "web_search" not in resolve_runtime_tool_names(("web",))
    assert "web_search" not in resolve_runtime_tool_names(("local-core",))
    assert "web_search" not in resolve_runtime_tool_names(("safe",))
    assert "web_extract" not in resolve_runtime_tool_names(("web",))
    assert "web_crawl" not in resolve_runtime_tool_names(("web",))
    assert "browser" not in list_runtime_toolsets()
    assert "browser_navigate" not in resolve_runtime_tool_names(("local-core",))
    assert "browser_navigate" not in resolve_runtime_tool_names(("safe",))


def test_runtime_ignores_stale_or_unknown_toolsets():
    resolved = resolve_runtime_tool_names(("web", "browser", "unknown-toolset", ""))

    assert "http_get" in resolved
    assert "web_search" not in resolved
    assert "browser_navigate" not in resolved


def test_runtime_tool_availability_omits_removed_search_tool(monkeypatch):
    for key in ("EXA_API_KEY", "PARALLEL_API_KEY", "TAVILY_API_KEY", "OPENAI_API_KEY", "HEYGENT_OPENAI_API_KEY"):
        monkeypatch.setenv(key, "test-key")
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    availability = {item["name"]: item for item in runtime.list_tool_availability(enabled_toolsets=("web", "browser"))}

    assert availability["http_get"]["available"] is True
    assert "web_search" not in availability
    assert "browser_navigate" not in availability


def test_http_get_runtime_fetches_json(monkeypatch):
    class FakeHeaders:
        def get_content_charset(self):
            return "utf-8"

        def get(self, name, default=None):
            return "application/json" if name == "content-type" else default

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, limit):
            return b'{"ok": true, "weather": "clear"}'

    def fake_urlopen(request, timeout=15):
        assert request.full_url == "https://k-skill-proxy.example/v1/korea-weather/forecast?lat=37.5172&lon=127.0473"
        return FakeResponse()

    from app.tools.web import web_tools

    monkeypatch.setattr(web_tools, "urlopen", fake_urlopen)
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="http_get",
        args={
            "url": "https://k-skill-proxy.example/v1/korea-weather/forecast",
            "params": {"lat": 37.5172, "lon": 127.0473},
        },
        enabled_toolsets=("web",),
    )

    assert result["ok"] is True
    assert result["json"] == {"ok": True, "weather": "clear"}


def test_delegation_toolset_exposes_delegate_task_contract():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    definitions = runtime.list_tool_definitions(enabled_toolsets=("delegation",))

    assert [definition["name"] for definition in definitions] == ["delegate_task"]
    schema = definitions[0]["schema"]
    assert "goal" in schema["parameters"]["properties"]
    assert "tasks" in schema["parameters"]["properties"]


def test_delegate_task_runtime_returns_worker_handoff_request():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="delegate_task",
        args={
            "goal": "문서 구현 여부 검증",
            "context": "Postgres/Redis orchestration 구현을 검토한다.",
            "toolsets": ["file", "terminal"],
            "profile_key": "worker.default",
            "max_iterations": 2,
        },
        enabled_toolsets=("delegation",),
    )

    assert result["ok"] is True
    assert result["child_session"]["goal"] == "문서 구현 여부 검증"
    assert result["child_session"]["toolsets"] == ["file", "terminal"]
    assert result["child_session"]["metadata"]["profile_key"] == "worker.default"


def test_session_agent_task_leaves_parent_waiting_by_default():
    work_repository = FakeRuntimeWorkRepository()
    parent = WorkItem(
        work_id="work-parent",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="부모 작업",
        description="부모",
        status="in_progress",
        assignee_agent_id="CEO",
    )
    work_repository.items[parent.work_id] = parent
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-research",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.agent",
            "config_snapshot": {"name": "Research", "role": "research"},
        }
    )
    runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context={"workId": parent.work_id},
    )

    result = runtime.run_call(
        name="session_agent_task",
        args={"title": "자료 조사", "instruction": "자료를 조사해줘"},
        enabled_toolsets=("work",),
    )

    child_id = result["child_work"]["workId"]
    assert result["ok"] is True
    assert work_repository.items[parent.work_id].status == "in_progress"
    assert work_repository.items[child_id].assignee_agent_id == "agent-research"
    assert work_repository.relations == []


def test_session_agent_task_reuses_child_work_for_same_turn_and_payload():
    work_repository = FakeRuntimeWorkRepository()
    parent = WorkItem(
        work_id="work-parent",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="부모 작업",
        description="부모",
        status="in_progress",
        assignee_agent_id="CEO",
    )
    work_repository.items[parent.work_id] = parent
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-research",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.agent",
            "config_snapshot": {"name": "Research", "role": "research"},
        }
    )
    runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context={"workId": parent.work_id, "promptMessageId": "msg-1", "taskRunId": "task-root"},
    )
    args = {"title": "자료 조사", "instruction": "자료를 조사해줘"}

    first = runtime.run_call(name="session_agent_task", args=args, enabled_toolsets=("work",))
    second = runtime.run_call(name="session_agent_task", args=args, enabled_toolsets=("work",))

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["child_work"]["workId"] == second["child_work"]["workId"]
    assert first["startExecution"] is True
    assert second["startExecution"] is False
    assert second["reused"] is True
    assert len(work_repository.items) == 2
    assert len(work_repository.comments) == 1


def test_session_agent_task_reuses_root_and_child_work_for_same_prompt_message():
    work_repository = FakeRuntimeWorkRepository()
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-weather",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.weather",
            "config_snapshot": {"name": "Weather", "role": "research"},
        }
    )
    context = {
        "sessionId": "session-1",
        "ownerKey": "7",
        "ownerUserId": 7,
        "prompt": "부산 기상 관련 일주일 소식을 조사하고 나한테 말해줘",
        "promptMessageId": "msg-1",
        "taskRunId": "task-root",
        "allowSessionAgentRootWork": True,
    }
    args = {
        "title": "부산 기상 조사",
        "instruction": "부산 기상 관련 일주일 소식을 조사하고 요약해줘.",
    }

    first_runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context=dict(context),
    )
    second_runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context=dict(context),
    )

    first = first_runtime.run_call(name="session_agent_task", args=args, enabled_toolsets=("work",))
    second = second_runtime.run_call(name="session_agent_task", args=args, enabled_toolsets=("work",))

    assert first["ok"] is True
    assert second["ok"] is True
    assert first["parent_work"]["workId"] == second["parent_work"]["workId"]
    assert first["child_work"]["workId"] == second["child_work"]["workId"]
    assert first["startExecution"] is True
    assert second["startExecution"] is False
    assert second["reused"] is True
    assert len(work_repository.items) == 2
    assert len(work_repository.comments) == 1
    assert work_repository.items[first["parent_work"]["workId"]].active_run_id == "task-root"


def test_session_agent_task_rejects_agent_without_explicit_required_skill():
    work_repository = FakeRuntimeWorkRepository()
    parent = WorkItem(
        work_id="work-parent",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="부모 작업",
        description="부모",
        status="in_progress",
        assignee_agent_id="CEO",
    )
    work_repository.items[parent.work_id] = parent
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-dev",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.dev",
            "config_snapshot": {
                "name": "개발 에이전트",
                "role": "engineer",
                "skills": ["writing-plans"],
            },
        }
    )
    runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context={"workId": parent.work_id, "enabledSkillNames": ["mattermost-send"]},
    )

    result = runtime.run_call(
        name="session_agent_task",
        args={
            "title": "Mattermost 전송",
            "instruction": "mattermost-send 스킬 문서 절차를 따라 기본 채널로 실제 전송하라.",
            "assigneeAgentId": "agent-dev",
        },
        enabled_toolsets=("work",),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "session_agent_capability_mismatch"
    assert result["error"]["recoverable"] is True
    assert result["error"]["requiredSkillNames"] == ["mattermost-send"]
    assert result["error"]["missingSkillNames"] == ["mattermost-send"]
    assert result["error"]["agent"] == {
        "profileId": "agent-dev",
        "name": "개발 에이전트",
        "skills": ["writing-plans"],
    }
    assert len(work_repository.items) == 1


def test_session_agent_task_merges_explicit_and_parent_design_skill_requirements():
    work_repository = FakeRuntimeWorkRepository()
    parent = WorkItem(
        work_id="work-parent",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="부모 작업",
        description="부모",
        status="in_progress",
        assignee_agent_id="CEO",
    )
    work_repository.items[parent.work_id] = parent
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-dev",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.dev",
            "config_snapshot": {
                "name": "개발 에이전트",
                "role": "engineer",
                "skills": ["subagent-driven-development"],
            },
        }
    )
    runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context={"workId": parent.work_id, "enabledSkillNames": ["awesome-design"]},
    )

    result = runtime.run_call(
        name="session_agent_task",
        args={
            "title": "대시보드 UI 구현",
            "instruction": "awesome-design 지침을 우선 적용해 프로토타입 UI 코드를 구현하라.",
            "assigneeAgentId": "agent-dev",
            "requiredSkillNames": ["subagent-driven-development"],
        },
        enabled_toolsets=("work",),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "session_agent_capability_mismatch"
    assert result["error"]["requiredSkillNames"] == ["subagent-driven-development", "awesome-design"]
    assert result["error"]["missingSkillNames"] == ["awesome-design"]
    assert len(work_repository.items) == 1


def test_session_agent_task_does_not_infer_parent_skill_from_exclusion_text():
    work_repository = FakeRuntimeWorkRepository()
    parent = WorkItem(
        work_id="work-parent",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="부모 작업",
        description="부모",
        status="in_progress",
        assignee_agent_id="CEO",
    )
    work_repository.items[parent.work_id] = parent
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-k",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.k",
            "config_snapshot": {
                "name": "K-에이전트",
                "role": "k-services",
                "skills": ["srt-booking"],
            },
        }
    )
    runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context={"workId": parent.work_id, "enabledSkillNames": ["mattermost-send", "notion"]},
    )

    result = runtime.run_call(
        name="session_agent_task",
        args={
            "title": "SRT 실제 예약",
            "description": "SRT 예약만 담당합니다. Mattermost 공유와 Notion 일정 등록은 팀장이 직접 처리하므로 수행하지 마세요.",
            "instruction": "srt-booking 스킬로 부산에서 수서로 가는 SRT를 예약하세요. Mattermost/Notion 작업은 수행하지 않음.",
            "assigneeAgentId": "agent-k",
            "requiredSkillNames": ["srt-booking"],
        },
        enabled_toolsets=("work",),
    )

    assert result["ok"] is True
    assert result["child_work"]["assigneeAgentId"] == "agent-k"


def test_session_agent_task_can_create_root_work_when_default_agent_session_allows_it():
    work_repository = FakeRuntimeWorkRepository()
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-travel",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.travel",
            "config_snapshot": {"name": "Travel", "role": "travel"},
        }
    )
    runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context={
            "sessionId": "session-1",
            "ownerKey": "7",
            "ownerUserId": 7,
            "prompt": "SRT 예약 가능 여부를 확인해줘.",
            "taskRunId": "task-root",
            "allowSessionAgentRootWork": True,
        },
    )

    result = runtime.run_call(
        name="session_agent_task",
        args={"title": "SRT 예약 확인", "instruction": "부산에서 수서까지 SRT 예약 가능 여부를 확인해줘."},
        enabled_toolsets=("work",),
    )

    child_id = result["child_work"]["workId"]
    parent_id = result["parent_work"]["workId"]
    assert result["ok"] is True
    assert result["child_work"]["parentId"] == parent_id
    assert work_repository.items[parent_id].assignee_agent_id == "CEO"
    assert work_repository.items[parent_id].source == "session_agent_task"
    assert work_repository.items[parent_id].active_run_id == "task-root"
    assert work_repository.items[child_id].assignee_agent_id == "agent-travel"
    assert runtime.runtime_context["workId"] == parent_id


def test_session_agent_task_can_record_parent_dependency_without_changing_status():
    work_repository = FakeRuntimeWorkRepository()
    parent = WorkItem(
        work_id="work-parent",
        identifier="TASK-1",
        session_id="session-1",
        owner_key="7",
        owner_user_id=7,
        title="부모 작업",
        description="부모",
        status="todo",
        assignee_agent_id="CEO",
    )
    work_repository.items[parent.work_id] = parent
    agent_repository = FakeRuntimeAgentRepository(
        {
            "profile_id": "agent-research",
            "session_id": "session-1",
            "agent_type": "user_subagent",
            "profile_key": "session.agent",
            "config_snapshot": {"name": "Research", "role": "research"},
        }
    )
    runtime = LocalToolRuntime(
        skill_registry=object(),
        session_store=DummySessionStore(),
        work_repository=work_repository,
        agent_repository=agent_repository,
        runtime_context={"workId": parent.work_id},
    )

    result = runtime.run_call(
        name="session_agent_task",
        args={"title": "자료 조사", "instruction": "자료를 조사해줘", "blockParentUntilDone": True},
        enabled_toolsets=("work",),
    )

    child_id = result["child_work"]["workId"]
    assert result["ok"] is True
    assert work_repository.items[parent.work_id].status == "todo"
    assert work_repository.relations == [
        WorkRelation(source_work_id=child_id, target_work_id=parent.work_id, relation_type="blocks")
    ]


def test_delegate_task_normalizes_tool_names_to_worker_toolsets():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="delegate_task",
        args={
            "goal": "웹 자료 조사",
            "toolsets": ["http_get", "read_file", "terminal.run"],
        },
        enabled_toolsets=("delegation",),
    )

    assert result["child_session"]["toolsets"] == ["web", "file", "terminal"]
    assert result["child_session"]["input_payload"]["enabled_toolsets"] == ["web", "file", "terminal"]


def test_todo_writes_and_reads_full_json_ready_result():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    written = runtime.run_call(
        name="todo",
        args={
            "todos": [
                {"id": "plan", "content": "계획 정리", "status": "completed"},
                {"id": "ship", "content": "배포 점검", "status": "pending"},
            ]
        },
    )
    read = runtime.run_call(name="todo", args={})

    assert written == read
    assert written["todos"] == [
        {"id": "plan", "content": "계획 정리", "status": "completed"},
        {"id": "ship", "content": "배포 점검", "status": "pending"},
    ]
    assert written["summary"] == {
        "total": 2,
        "pending": 1,
        "in_progress": 0,
        "completed": 1,
        "cancelled": 0,
    }
    json.dumps(written, ensure_ascii=False)


def test_todo_projection_accepts_json_string_tool_content():
    state = apply_tool_results_to_todo_state(
        {},
        [
            {
                "name": "todo",
                "args": {},
                "result": json.dumps(
                    {
                        "todos": [{"id": "ship", "content": "배포 점검", "status": "pending"}],
                        "summary": {"total": 1, "pending": 1},
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    )

    assert build_task_todo_payload(state)["items"] == [
        {
            "id": "ship",
            "key": "ship",
            "content": "배포 점검",
            "title": "배포 점검",
            "kind": "todo",
            "status": "pending",
        }
    ]


def test_runtime_rejects_unknown_or_disabled_tool_before_execution():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    unknown = runtime.run_call(name="missing.tool", args={})
    disabled = runtime.run_call(
        name="terminal.run",
        args={"command": "exit 13"},
        enabled_toolsets=("planning",),
    )

    assert unknown["ok"] is False
    assert unknown["error"]["code"] == "tool_unavailable"
    assert disabled["ok"] is False
    assert disabled["error"]["code"] == "tool_unavailable"
    assert json.loads(disabled["content"])["error"]["tool_name"] == "terminal.run"


def test_runtime_rejects_invalid_arguments_as_tool_result():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(name="todo", args={"todos": [{"id": "plan"}]})

    assert result["ok"] is False
    assert result["error"]["code"] == "invalid_tool_arguments"
    assert "todos.0.content" in result["error"]["message"]


def test_file_runtime_calls_file_module_handler(monkeypatch):
    def fake_read_file_handler(args):
        return {"ok": True, "path": args["path"], "content": "runtime file content"}

    monkeypatch.setattr(file_tools, "read_file_handler", fake_read_file_handler, raising=False)
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="read_file",
        args={"path": "README.md"},
        enabled_toolsets=("file",),
    )

    assert result == {"ok": True, "path": "README.md", "content": "runtime file content"}


def test_file_runtime_blocks_write_when_only_safe_toolset_enabled(monkeypatch):
    called = False

    def fake_write_file_handler(args):
        nonlocal called
        called = True
        return {"ok": True}

    monkeypatch.setattr(file_tools, "write_file_handler", fake_write_file_handler, raising=False)
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="write_file",
        args={"path": "README.md", "content": "blocked"},
        enabled_toolsets=("safe",),
    )

    assert called is False
    assert result["ok"] is False
    assert result["error"]["code"] == "tool_unavailable"
    assert result["error"]["tool_name"] == "write_file"


def test_terminal_runtime_treats_empty_cwd_as_current_directory():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(name="terminal.run", args={"command": "echo RUNTIME_OK", "cwd": ""})

    assert result["returncode"] == 0
    assert "RUNTIME_OK" in result["stdout"]


def test_runtime_file_tool_ignores_model_supplied_workspace_root(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside"
    workspace.mkdir()
    outside.mkdir()
    (outside / "secret.txt").write_text("outside-secret", encoding="utf-8")
    monkeypatch.chdir(workspace)
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="read_file",
        args={"workspace_root": str(outside), "path": str(outside / "secret.txt")},
        enabled_toolsets=("file",),
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "tool_execution_failed"
    assert "PermissionError" in result["error"]["message"]
    assert "outside-secret" not in json.dumps(result, ensure_ascii=False)


def test_terminal_runtime_caps_large_stdout():
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    result = runtime.run_call(
        name="terminal.run",
        args={"argv": [sys.executable, "-c", "print('x' * 20000)"]},
        enabled_toolsets=("terminal",),
    )

    assert result["returncode"] == 0
    assert result["stdout_truncated"] is True
    assert "[truncated" in result["stdout"]
    assert len(result["stdout"]) < 20000


def test_terminal_runtime_blocks_dangerous_shell_command_before_execution(tmp_path):
    runtime = LocalToolRuntime(skill_registry=object(), session_store=DummySessionStore())

    blocked_commands = [
        "git reset --hard",
        "rm -rf .",
        "Remove-Item . -Force -Recurse",
        "Remove-Item . -Recurse -Force",
    ]

    for command in blocked_commands:
        result = runtime.run_call(
            name="terminal.run",
            args={"command": command, "cwd": str(tmp_path)},
            enabled_toolsets=("terminal",),
        )

        assert result["ok"] is False
        assert result["error"]["code"] == "blocked_command"
        assert result["returncode"] is None
