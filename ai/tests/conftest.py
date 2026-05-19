from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.clients.backend_auth import BackendAuthVerifyResult
from app.clients.backend_memory import BackendMemoryClientError
from app.domain.tasks.models import StepRun, TaskRun
from tests.fakes import InMemoryAgentRepository, InMemorySkillRepository, InMemoryTaskRepository, InMemoryTranscriptStore


class NoopWorkRepository:
    def release_stale_active_work_runs(self, *, stale_after_seconds: int, limit: int = 50) -> list:
        return []

    def claim_work_wakes(self, *, limit: int = 10) -> list:
        return []

    def close(self) -> None:
        return None


class InMemoryPrototypeArtifactRepository:
    def __init__(self) -> None:
        self.active_by_session: dict[tuple[str, str], dict] = {}

    def create_artifact_version(self, **kwargs):
        key = (kwargs["session_id"], kwargs["owner_key"])
        previous = self.active_by_session.get(key)
        version_number = int(previous.get("version_number", 0)) + 1 if previous else 1
        artifact_id = previous["artifact_id"] if previous else f"artifact_{len(self.active_by_session) + 1}"
        version_id = f"version_{artifact_id}_{version_number}"
        record = {
            "artifact_id": artifact_id,
            "version_id": version_id,
            "session_id": kwargs["session_id"],
            "owner_key": kwargs["owner_key"],
            "title": kwargs["title"],
            "framework": kwargs["framework"],
            "styling": kwargs["styling"],
            "design_preset_id": kwargs["design_preset_id"],
            "entry_file": kwargs["entry_file"],
            "files": kwargs["files"],
            "version_number": version_number,
            "summary": kwargs["summary"],
            "created_at": "2026-05-15T00:00:00Z",
            "updated_at": "2026-05-15T00:00:00Z",
        }
        self.active_by_session[key] = record
        return record

    def get_active_artifact(self, *, session_id: str, owner_key: str):
        return self.active_by_session.get((session_id, owner_key))

    def get_version_code(self, *, session_id: str, owner_key: str, artifact_id: str, version_id: str):
        record = self.active_by_session.get((session_id, owner_key))
        if record and record["artifact_id"] == artifact_id and record["version_id"] == version_id:
            return record
        return None


class FakeBackendAuthClient:
    async def verify_access_token(self, access_token: str, *, workspace_key: str | None = None) -> BackendAuthVerifyResult:
        return BackendAuthVerifyResult(user_id=access_token, workspace_key=workspace_key)

    async def aclose(self) -> None:
        return None


class FakeBackendMemoryClient:
    def __init__(self) -> None:
        self.calls = []
        self.created_candidates = []
        self.memories = []
        self.fail = False

    async def recall(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise BackendMemoryClientError("test memory recall failure")
        return list(self.memories)

    async def create_candidates(self, **kwargs):
        self.created_candidates.append(kwargs)
        if self.fail:
            raise BackendMemoryClientError("test memory writeback failure")
        return []

    async def mark_used(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise BackendMemoryClientError("test memory mark used failure")
        return None

    async def aclose(self) -> None:
        return None


class FakeBackendIotDisplayClient:
    enabled = False

    def __init__(self) -> None:
        self.calls = []

    async def publish(self, payload) -> None:
        self.calls.append(payload)

    async def aclose(self) -> None:
        return None


class FakeMemoryExtractor:
    def __init__(self) -> None:
        self.calls = []
        self.candidates = []
        self.fail = False

    async def extract_candidates(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("test memory extraction failure")
        return list(self.candidates)


@pytest.fixture(autouse=True)
def configure_test_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HEYGENT_OPENAI_AUTH_FILE", str(tmp_path / "missing-auth.json"))
    monkeypatch.setenv("HEYGENT_OPENAI_API_KEY", "")
    monkeypatch.setenv("HEYGENT_POSTGRES_DSN", "postgresql://test")
    monkeypatch.setenv("HEYGENT_REDIS_URL", "redis://test")
    monkeypatch.setenv("HEYGENT_BRIDGE_TOKEN", "")
    monkeypatch.setenv("HEYGENT_TASK_EXECUTION_QUEUE_ENABLED", "false")
    # 로컬 AI/.env의 WebSocket Origin 제한이 TestClient 기본 Origin을 막지 않도록
    # 테스트 런타임에서는 각 테스트가 필요한 경우에만 허용 목록을 직접 설정한다.
    monkeypatch.setenv("HEYGENT_WS_ALLOWED_ORIGINS", "")
    monkeypatch.setenv("HEYGENT_CORS_ALLOWED_ORIGINS", "")

    import app.api.http.sessions as session_routes
    import app.api.http.agent_sessions as agent_session_routes
    import app.api.http.tasks as task_routes
    import app.main as app_main

    _patch_app_runtime(app_main, monkeypatch)

    async def optional_task_user(request):
        authorization = str(request.headers.get("authorization") or "").strip()
        if not authorization:
            return None
        _scheme, _separator, token = authorization.partition(" ")
        return await request.app.state.backend_auth_client.verify_access_token(
            token.strip(),
            workspace_key=str(request.headers.get("x-workspace-key") or request.query_params.get("workspaceKey") or "").strip() or None,
        )

    async def local_session_user(request):
        authorization = str(request.headers.get("authorization") or "").strip()
        if authorization:
            _scheme, _separator, token = authorization.partition(" ")
            return await request.app.state.backend_auth_client.verify_access_token(
                token.strip(),
                workspace_key=str(request.headers.get("x-workspace-key") or request.query_params.get("workspaceKey") or "").strip() or None,
            )
        return BackendAuthVerifyResult(user_id="local-user")

    def optional_ensure_owner(user, owner_key: str | None) -> None:
        if user is None:
            return None
        if str(owner_key or "") != str(user.user_id):
            from fastapi import HTTPException

            raise HTTPException(status_code=403, detail="forbidden")
        return None

    monkeypatch.setattr(task_routes, "authenticate_http_user", optional_task_user)
    monkeypatch.setattr(task_routes, "ensure_owner", optional_ensure_owner)
    monkeypatch.setattr(session_routes, "authenticate_http_user", local_session_user)
    monkeypatch.setattr(agent_session_routes, "authenticate_http_user", optional_task_user)
    monkeypatch.setattr(agent_session_routes, "ensure_owner", optional_ensure_owner)

    def list_public_sessions(store, *, owner_key: str | None, limit: int, offset: int, include_archived: bool = False):
        sessions = [
            session
            for session in store.list_sessions(limit=10_000)
            if session.get("source") == "api.session"
            and (owner_key is None or session.get("user_id") == owner_key)
            and session.get("deleted_at") is None
            and (include_archived or session.get("archived_at") is None)
        ]
        sessions.sort(
            key=lambda session: (
                session.get("updated_at") or session.get("started_at"),
                session.get("archived_at") is not None,
            ),
            reverse=True,
        )
        return sessions[offset : offset + limit], len(sessions)

    monkeypatch.setattr(session_routes, "_list_public_sessions", list_public_sessions)


@pytest.fixture()
def client() -> TestClient:
    import app.main as app_main

    with TestClient(app_main.app) as test_client:
        yield test_client


def _patch_app_runtime(app_main, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.storage.redis import FakeRedis, RedisTaskProjectionStore

    real_local_tool_runtime = app_main.LocalToolRuntime

    def local_tool_runtime_without_bridge(*args, **kwargs):
        kwargs["bridge_session_manager"] = None
        return real_local_tool_runtime(*args, **kwargs)

    monkeypatch.setattr(app_main, "apply_configured_postgres_migrations", lambda **_kwargs: [])
    monkeypatch.setattr(app_main, "connect_postgres", lambda _dsn: None)
    monkeypatch.setattr(app_main, "PostgresTaskRepository", lambda _connection_factory: InMemoryTaskRepository())
    monkeypatch.setattr(app_main, "PostgresSessionStore", lambda _connection_factory: InMemoryTranscriptStore())
    monkeypatch.setattr(app_main, "PostgresAgentRepository", lambda _connection_factory, **_kwargs: InMemoryAgentRepository())
    monkeypatch.setattr(app_main, "PostgresPrototypeArtifactRepository", lambda _connection_factory: InMemoryPrototypeArtifactRepository())
    monkeypatch.setattr(app_main, "PostgresWorkRepository", lambda _connection_factory: NoopWorkRepository())
    monkeypatch.setattr(app_main, "PostgresSkillRepository", lambda _connection_factory: InMemorySkillRepository())
    monkeypatch.setattr(app_main, "build_task_projection_store", lambda **_kwargs: RedisTaskProjectionStore(FakeRedis(), ttl_seconds=60))
    monkeypatch.setattr(app_main, "BackendAuthClient", lambda settings: FakeBackendAuthClient())
    monkeypatch.setattr(app_main, "BackendIotDisplayClient", lambda settings: FakeBackendIotDisplayClient())
    monkeypatch.setattr(app_main, "BackendMemoryClient", lambda settings: FakeBackendMemoryClient())
    monkeypatch.setattr(app_main, "ProviderMemoryExtractionClient", lambda **_kwargs: object())
    monkeypatch.setattr(app_main, "LlmMemoryExtractor", lambda **_kwargs: FakeMemoryExtractor())
    monkeypatch.setattr(app_main, "ProviderMemoryUsageAttributionClient", lambda **_kwargs: object())
    monkeypatch.setattr(app_main, "LlmMemoryUsageAttributionVerifier", lambda **_kwargs: None)
    monkeypatch.setattr(app_main, "LocalToolRuntime", local_tool_runtime_without_bridge)
    build_memory_connection_registry = app_main.build_connection_registry
    monkeypatch.setattr(app_main, "build_connection_registry", lambda **_kwargs: build_memory_connection_registry(redis_url=None, ttl_seconds=60))


@pytest.fixture()
def task_run() -> TaskRun:
    return TaskRun(
        task_run_id="task_test",
        task_type="agent.loop",
        owner_key="tester",
        status="PENDING",
        title="모델 생성 요청",
        input_payload={"prompt": "hello"},
    )


@pytest.fixture()
def step_run() -> StepRun:
    return StepRun(
        step_run_id="step_test",
        task_run_id="task_test",
        step_order=1,
        step_type="agent.loop.execute",
        status="PENDING",
        title="모델 응답 생성",
        input_payload={"prompt": "hello"},
    )
