from datetime import timedelta
import json

from app.core.time import utc_now
from app.domain.tasks.repository import (
    ApprovalRepository,
    DurableRunAnchorRepository,
    ProviderCredentialRepository,
    TaskEventRepository,
    TaskRepository,
    TaskRunRepository,
)
from app.domain.tasks.models import TaskRun
from app.contracts.event.task_events import TaskEventEnvelope
from app.storage.queries.approval_queries import CREATE_APPROVAL_REQUESTS
from app.storage.queries.task_queries import CREATE_TASK_RUNS
from app.storage.postgres.schema import POSTGRES_SCHEMA_STATEMENTS, render_postgres_schema
from app.storage.postgres.connection import apply_configured_postgres_migrations
from app.storage.postgres.durable_repository import PostgresDurableRepository, PostgresTaskRepository
from app.storage.postgres.migrations import POSTGRES_MIGRATIONS, apply_postgres_migrations
from app.contracts.work.responses import WorkItemResponse
from app.domain.work.models import WorkItem
from tests.fakes import InMemoryTaskRepository
from app.storage.postgres.session_store import PostgresSessionStore, _owner_filter_params, _owner_filter_sql


def test_in_memory_repository_satisfies_task_boundary_protocols():
    repository = InMemoryTaskRepository()

    assert isinstance(repository, ApprovalRepository)
    assert isinstance(repository, TaskEventRepository)
    assert isinstance(repository, ProviderCredentialRepository)
    assert isinstance(repository, TaskRunRepository)
    assert isinstance(repository, TaskRepository)
    assert not isinstance(repository, DurableRunAnchorRepository)
    assert TaskRunRepository in TaskRepository.__mro__
    assert ApprovalRepository in TaskRepository.__mro__
    assert TaskEventRepository in TaskRepository.__mro__
    assert ProviderCredentialRepository in TaskRepository.__mro__


def test_postgres_task_repository_satisfies_runtime_repository_protocols():
    repository = PostgresTaskRepository(lambda: None)

    assert isinstance(repository, ApprovalRepository)
    assert isinstance(repository, TaskEventRepository)
    assert isinstance(repository, ProviderCredentialRepository)
    assert isinstance(repository, TaskRunRepository)
    assert isinstance(repository, DurableRunAnchorRepository)
    assert isinstance(repository, TaskRepository)


def test_in_memory_task_repository_claims_pending_tasks_atomically_by_state():
    repository = InMemoryTaskRepository()
    repository.create_pending_task(
        TaskRun(
            task_run_id="task-queue-1",
            task_type="agent.loop",
            owner_key="42",
            session_key="session-1",
            status="PENDING",
        )
    )

    claimed = repository.claim_next_task(claim_owner="worker-a", lease_seconds=30)
    claimed_again = repository.claim_next_task(claim_owner="worker-b", lease_seconds=30)

    assert claimed is not None
    assert claimed.task_run_id == "task-queue-1"
    assert claimed.status == "RUNNING"
    assert claimed.queue_status == "claimed"
    assert claimed.claim_owner == "worker-a"
    assert claimed.attempts == 1
    assert claimed.lease_expires_at is not None
    assert claimed_again is None


def test_in_memory_task_repository_does_not_claim_direct_tasks():
    repository = InMemoryTaskRepository()
    saved = repository.create_direct_task(
        TaskRun(
            task_run_id="task-direct-1",
            task_type="agent.loop",
            owner_key="42",
            session_key="session-1",
            status="PENDING",
        )
    )

    claimed = repository.claim_next_task(claim_owner="worker-a", lease_seconds=30)

    assert saved.queue_status == "running"
    assert saved.claim_owner is None
    assert saved.attempts == 0
    assert claimed is None


def test_in_memory_task_repository_does_not_recover_stale_direct_tasks():
    repository = InMemoryTaskRepository()
    saved = repository.create_direct_task(
        TaskRun(
            task_run_id="task-direct-stale",
            task_type="agent.loop",
            owner_key="42",
            session_key="session-1",
            status="PENDING",
        )
    )
    repository.tasks[saved.task_run_id].updated_at = utc_now() - timedelta(minutes=20)

    recovered = repository.recover_stale_task_runs(orphan_after_seconds=30)

    assert recovered == []
    direct = repository.get_task("task-direct-stale")
    assert direct is not None
    assert direct.status == "PENDING"
    assert direct.queue_status == "running"


def test_postgres_schema_contains_required_durable_tables():
    schema_sql = "\n".join(POSTGRES_SCHEMA_STATEMENTS)

    required_tables = {
        "agent_sessions",
        "agent_messages",
        "approval_requests",
        "session_command_receipts",
        "run_anchors",
        "step_anchors",
        "worker_handoffs",
        "ai_agent_profiles",
        "ai_agent_templates",
        "ai_agent_secret_values",
        "provider_oauth_states",
        "provider_tokens",
        "work_counters",
        "work_items",
        "work_labels",
        "work_label_links",
        "work_comments",
        "work_relations",
        "work_runs",
        "work_wake_requests",
        "work_recovery_actions",
        "work_read_states",
        "ai_skill_catalog",
        "ai_user_skill_settings",
        "ai_agent_skill_settings",
    }

    for table_name in required_tables:
        assert f"CREATE TABLE IF NOT EXISTS {table_name}" in schema_sql


def test_postgres_schema_keeps_token_plaintext_out_of_durable_tables():
    schema_sql = render_postgres_schema()

    assert "access_token" not in schema_sql
    assert "refresh_token" not in schema_sql
    assert "raw_payload" not in schema_sql
    assert "token_secret_ref TEXT NOT NULL" in schema_sql
    assert "refresh_secret_ref TEXT" in schema_sql
    assert "code_verifier_secret_ref TEXT" in schema_sql
    assert "encrypted_value TEXT NOT NULL" in schema_sql
    assert "UNIQUE (profile_id, document_key, section_key, secret_key)" in schema_sql


def test_postgres_schema_contains_anchor_profile_and_worker_linkage_columns():
    schema_sql = render_postgres_schema()

    for expected in [
        "anchor_generation BIGINT NOT NULL DEFAULT 1",
        "revision BIGINT NOT NULL DEFAULT 0",
        "event_epoch BIGINT NOT NULL DEFAULT 1",
        "last_durable_sequence BIGINT NOT NULL DEFAULT 0",
        "queue_status TEXT NOT NULL DEFAULT 'queued'",
        "claim_owner TEXT",
        "lease_expires_at TIMESTAMPTZ",
        "attempts INTEGER NOT NULL DEFAULT 0",
        "CREATE INDEX IF NOT EXISTS idx_run_anchors_queue_claim",
        "CREATE INDEX IF NOT EXISTS idx_run_anchors_active_owner_session",
        "parent_step_run_id TEXT",
        "worker_session_id TEXT",
        "agent_profile_version INTEGER",
        "agent_config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb",
        "profile_version INTEGER NOT NULL DEFAULT 1",
        "config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb",
        "template_version INTEGER NOT NULL DEFAULT 1",
        "PRIMARY KEY (provider_name, state)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_requests_one_pending_per_task",
        "WHERE status = 'PENDING'",
    ]:
        assert expected in schema_sql


def test_postgres_schema_contains_user_owner_and_session_lifecycle_columns():
    schema_sql = render_postgres_schema()
    migration_sql = "\n".join(statement for migration in POSTGRES_MIGRATIONS for statement in migration.statements)

    for expected in [
        "owner_user_id BIGINT REFERENCES users(id)",
        "archived_at TIMESTAMPTZ",
        "deleted_at TIMESTAMPTZ",
        "deleted_by BIGINT REFERENCES users(id)",
        "purge_after TIMESTAMPTZ",
        "settings JSONB NOT NULL DEFAULT '{}'::jsonb",
        "CONSTRAINT agent_sessions_public_owner_user_required",
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_owner_user_source_updated",
        "CREATE INDEX IF NOT EXISTS idx_agent_sessions_purge_after",
        "CREATE INDEX IF NOT EXISTS idx_session_command_receipts_owner",
    ]:
        assert expected in schema_sql

    for table_name in ("agent_sessions", "run_anchors", "approval_requests", "ai_agent_profiles"):
        table_start = schema_sql.index(f"CREATE TABLE IF NOT EXISTS {table_name}")
        table_end = schema_sql.index(");", table_start)
        table_sql = schema_sql[table_start:table_end]
        assert "owner_user_id BIGINT REFERENCES users(id)" in table_sql

    for table_name in ("ai_agent_templates", "provider_tokens", "provider_oauth_states"):
        table_start = schema_sql.index(f"CREATE TABLE IF NOT EXISTS {table_name}")
        table_end = schema_sql.index(");", table_start)
        table_sql = schema_sql[table_start:table_end]
        assert "owner_user_id" not in table_sql

    assert "0006_session_owner_lifecycle_settings" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "0007_session_command_receipts" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "0008_work_board_schema" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "ALTER TABLE agent_sessions" in migration_sql
    assert "ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id)" in migration_sql
    assert "ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb" in migration_sql
    assert "agent_sessions_public_owner_user_required" in migration_sql
    assert "CREATE TABLE IF NOT EXISTS session_command_receipts" in migration_sql
    assert "CREATE TABLE IF NOT EXISTS work_items" in migration_sql


def test_postgres_work_schema_contains_board_execution_fields():
    schema_sql = render_postgres_schema()

    for expected in [
        "identifier TEXT NOT NULL",
        "status TEXT NOT NULL",
        "assignee_agent_id TEXT",
        "parent_id TEXT REFERENCES work_items(work_id) ON DELETE SET NULL",
        "raw_user_input TEXT",
        "execution_instruction TEXT",
        "expected_deliverable TEXT",
        "acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb",
        "constraints_payload JSONB NOT NULL DEFAULT '[]'::jsonb",
        "client_request_id TEXT",
        "active_run_id TEXT",
        "latest_run_id TEXT",
        "UNIQUE (session_id, identifier)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_work_items_session_client_request",
        "CREATE INDEX IF NOT EXISTS idx_work_items_session_status_updated",
    ]:
        assert expected in schema_sql


def test_postgres_work_schema_contains_flow_order_contract():
    schema_sql = render_postgres_schema()
    migration_sql = "\n".join(statement for migration in POSTGRES_MIGRATIONS for statement in migration.statements)

    assert "flow_order INTEGER" in schema_sql
    assert "CREATE INDEX IF NOT EXISTS idx_work_items_parent_flow_order" in schema_sql
    assert "0011_work_flow_order" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "ADD COLUMN IF NOT EXISTS flow_order INTEGER" in migration_sql
    assert "idx_work_items_parent_flow_order" in migration_sql


def test_postgres_work_schema_contains_wake_recovery_contract():
    schema_sql = render_postgres_schema()
    migration_sql = "\n".join(statement for migration in POSTGRES_MIGRATIONS for statement in migration.statements)

    for expected in [
        "CREATE TABLE IF NOT EXISTS work_wake_requests",
        "scheduled_retry",
        "next_attempt_at TIMESTAMPTZ",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_work_wake_requests_work_active",
        "CREATE TABLE IF NOT EXISTS work_recovery_actions",
        "idempotency_key TEXT NOT NULL UNIQUE",
        "payload JSONB NOT NULL DEFAULT '{}'::jsonb",
        "CREATE INDEX IF NOT EXISTS idx_work_recovery_actions_work_created",
    ]:
        assert expected in schema_sql

    assert "0013_work_recovery_actions" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "0014_task_run_queue_claims" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "0015_allow_nested_session_agent_runs" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "DROP CONSTRAINT IF EXISTS work_wake_requests_status_check" in migration_sql
    assert "DROP INDEX IF EXISTS idx_run_anchors_one_active_per_owner_session" in migration_sql


def test_postgres_schema_contains_user_skill_settings_contract():
    schema_sql = render_postgres_schema()
    migration_sql = "\n".join(statement for migration in POSTGRES_MIGRATIONS for statement in migration.statements)

    for expected in [
        "CREATE TABLE IF NOT EXISTS ai_skill_catalog",
        "CREATE TABLE IF NOT EXISTS ai_user_skill_settings",
        "CREATE TABLE IF NOT EXISTS ai_agent_skill_settings",
        "source_type TEXT NOT NULL DEFAULT 'builtin'",
        "enabled BOOLEAN NOT NULL",
        "PRIMARY KEY (owner_key, skill_id)",
        "PRIMARY KEY (profile_id, skill_id)",
        "CREATE INDEX IF NOT EXISTS idx_ai_user_skill_settings_owner_enabled",
        "CREATE INDEX IF NOT EXISTS idx_ai_agent_skill_settings_profile_enabled",
    ]:
        assert expected in schema_sql

    assert "0016_user_skill_settings" in [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert "CREATE TABLE IF NOT EXISTS ai_skill_catalog" in migration_sql


def test_work_item_response_exposes_flow_order_for_diagram_layout():
    response = WorkItemResponse.model_validate(
        WorkItem(
            work_id="work-flow-child",
            identifier="TASK-2",
            session_id="session-flow",
            owner_key="user-flow",
            owner_user_id=7,
            title="시장 분석",
            description=None,
            status="todo",
            parent_id="work-flow-root",
            flow_order=2,
        ),
        from_attributes=True,
    )

    assert response.model_dump(by_alias=True)["flowOrder"] == 2


def test_sqlite_task_and_approval_contracts_keep_owner_user_columns():
    assert "owner_user_id INTEGER REFERENCES users(id)" in CREATE_TASK_RUNS
    assert "owner_user_id INTEGER REFERENCES users(id)" in CREATE_APPROVAL_REQUESTS


def test_postgres_session_owner_filter_prefers_user_fk_when_user_id_is_numeric():
    assert _owner_filter_sql("42") == "owner_user_id = %s"
    assert _owner_filter_params("42") == [42]
    assert _owner_filter_sql("local-user") == "owner_key = %s"
    assert _owner_filter_params("local-user") == ["local-user"]


def test_postgres_schema_seeds_builtin_agent_profiles():
    schema_sql = render_postgres_schema()

    assert "main.default" in schema_sql
    assert "worker.default" in schema_sql
    assert "'worker'" in schema_sql
    assert "ON CONFLICT (owner_key, profile_key, profile_version) DO UPDATE" in schema_sql
    assert '"web"' in schema_sql
    assert '"browser"' not in schema_sql
    assert '"hardTimeoutSeconds":900' in schema_sql


def test_postgres_migrations_refresh_existing_builtin_agent_profiles():
    migration_ids = [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    refresh_migration = POSTGRES_MIGRATIONS[migration_ids.index("0003_refresh_builtin_agent_profiles")]
    migration_sql = "\n".join(refresh_migration.statements)

    assert "UPDATE ai_agent_profiles" in migration_sql
    assert "main.default" in migration_sql
    assert "worker.default" in migration_sql
    assert '"web"' in migration_sql
    assert '"browser"' not in migration_sql
    assert '"maxIterations":80' in migration_sql
    assert '"hardTimeoutSeconds":900' in migration_sql


def test_postgres_migrations_scrub_removed_browser_toolset_from_stored_settings():
    migration_ids = [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    cleanup_migration = POSTGRES_MIGRATIONS[migration_ids.index("0019_remove_removed_browser_toolset")]
    migration_sql = "\n".join(cleanup_migration.statements)

    assert "UPDATE ai_agent_profiles" in migration_sql
    assert "UPDATE agent_sessions" in migration_sql
    assert "to_jsonb('browser'::text)" in migration_sql
    assert "config_snapshot->'toolsets' @> '[\"browser\"]'::jsonb" in migration_sql
    assert "settings->'toolsets' @> '[\"browser\"]'::jsonb" in migration_sql


class _FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakePostgresConnection:
    def __init__(self, *, applied=None):
        self.applied = set(applied or [])
        self.executed: list[tuple[str, tuple | None]] = []
        self.committed = False

    def execute(self, sql: str, params: tuple | None = None):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if normalized.startswith("SELECT migration_id FROM schema_migrations"):
            return _FakeCursor([(migration_id,) for migration_id in sorted(self.applied)])
        if normalized.startswith("INSERT INTO schema_migrations") and params:
            self.applied.add(params[0])
        return _FakeCursor()

    def commit(self):
        self.committed = True


class _FakeSessionConnection:
    def __init__(self):
        self.session = {
            "session_id": "pg_message_session",
            "owner_key": "owner-a",
            "owner_user_id": None,
            "session_source": "api.session",
            "session_role": "api.session",
            "metadata": {"source": "api.session", "message_count": 0},
            "history_version": 0,
            "running_task_run_id": None,
            "deleted_at": None,
        }
        self.messages: list[dict] = []
        self.commits = 0

    def execute(self, sql: str, params: tuple | None = None):
        normalized = " ".join(sql.split())
        if normalized.startswith("SELECT * FROM agent_sessions"):
            return _FakeCursor([self.session])
        if normalized.startswith("SELECT * FROM agent_messages") and "metadata->>'client_message_id'" in normalized:
            return _FakeCursor([])
        if normalized.startswith("SELECT COALESCE(MAX(message_sequence), 0) + 1"):
            return _FakeCursor([{"next_sequence": len(self.messages) + 1}])
        if normalized.startswith("INSERT INTO agent_messages"):
            message_id, session_id, sequence, content, metadata = params
            role = "assistant" if "'assistant'" in normalized else "user"
            self.messages.append(
                {
                    "message_id": message_id,
                    "session_id": session_id,
                    "message_sequence": sequence,
                    "role": role,
                    "content": content,
                    "metadata": metadata,
                }
            )
            return _FakeCursor()
        if (
            normalized.startswith("UPDATE agent_sessions SET history_version")
            and "running_task_run_id = NULL" in normalized
        ):
            history_version, session_id, owner_key = params
            assert session_id == self.session["session_id"]
            assert owner_key == self.session["owner_key"]
            self.session["history_version"] = history_version
            self.session["running_task_run_id"] = None
            self.session["metadata"]["message_count"] += 1
            return _FakeCursor()
        if normalized.startswith("UPDATE agent_sessions SET history_version"):
            history_version, task_run_id, session_id, owner_key = params
            assert session_id == self.session["session_id"]
            assert owner_key == self.session["owner_key"]
            self.session["history_version"] = history_version
            self.session["running_task_run_id"] = task_run_id
            self.session["metadata"]["message_count"] += 1
            return _FakeCursor()
        return _FakeCursor()

    def commit(self):
        self.commits += 1


def test_postgres_session_store_starts_task_and_updates_message_count():
    connection = _FakeSessionConnection()
    store = PostgresSessionStore(lambda: connection)

    result = store.append_user_message_and_start_task(
        owner_key="owner-a",
        session_id="pg_message_session",
        content="실제 전송 경로 확인",
        client_message_id="client-pg-message-1",
        task_run_id="task_pg_message_1",
        base_history_version=0,
    )

    assert result["duplicate"] is False
    assert result["message_id"] == 1
    assert result["after_user_message_version"] == 1
    assert connection.session["metadata"]["message_count"] == 1
    assert connection.session["running_task_run_id"] == "task_pg_message_1"
    assert connection.commits == 1


def test_postgres_session_store_finishes_task_and_clears_running_guard():
    connection = _FakeSessionConnection()
    store = PostgresSessionStore(lambda: connection)
    started = store.append_user_message_and_start_task(
        owner_key="owner-a",
        session_id="pg_message_session",
        content="질문",
        client_message_id="client-pg-message-2",
        task_run_id="task_pg_message_2",
        base_history_version=0,
    )

    result = store.append_assistant_message_and_finish_task(
        owner_key="owner-a",
        session_id="pg_message_session",
        task_run_id="task_pg_message_2",
        content="답변",
        completion_expected_version=started["completion_expected_version"],
        status="COMPLETED",
    )

    assert result["message_id"] == 2
    assert result["completion_result_version"] == 2
    assert [message["role"] for message in connection.messages] == ["user", "assistant"]
    assert connection.session["metadata"]["message_count"] == 2
    assert connection.session["running_task_run_id"] is None
    assert connection.commits == 2


def test_postgres_migration_runner_applies_unapplied_migrations_once():
    connection = _FakePostgresConnection()

    applied = apply_postgres_migrations(connection)

    assert applied == [migration.migration_id for migration in POSTGRES_MIGRATIONS]
    assert connection.committed is True
    assert any("CREATE TABLE IF NOT EXISTS schema_migrations" in sql for sql, _ in connection.executed)
    assert any("CREATE TABLE IF NOT EXISTS agent_sessions" in sql for sql, _ in connection.executed)
    for migration in POSTGRES_MIGRATIONS:
        assert any(params == (migration.migration_id,) for _sql, params in connection.executed)


def test_postgres_migration_runner_skips_already_applied_migrations():
    connection = _FakePostgresConnection(applied={migration.migration_id for migration in POSTGRES_MIGRATIONS})

    applied = apply_postgres_migrations(connection)

    assert applied == []
    assert not any("CREATE TABLE IF NOT EXISTS agent_sessions" in sql for sql, _ in connection.executed)
    assert connection.committed is True


def test_configured_postgres_migration_runner_skips_when_disabled_or_missing_dsn():
    assert apply_configured_postgres_migrations(dsn=None, enabled=True) == []
    assert apply_configured_postgres_migrations(dsn="postgresql://example", enabled=False) == []


class _FakeDurableConnection:
    def __init__(self):
        self.run_anchors: dict[str, dict] = {}
        self.step_anchors: dict[str, dict] = {}
        self.worker_handoffs: dict[str, dict] = {}
        self.agent_profiles: dict[tuple[str, str, int], dict] = {}
        self.executed: list[tuple[str, tuple | None]] = []
        self.commits = 0

    def execute(self, sql: str, params: tuple | None = None):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if normalized.startswith("INSERT INTO run_anchors"):
            (
                task_run_id,
                session_id,
                owner_key,
                owner_user_id,
                session_key,
                current_step_run_id,
                durable_status,
                queue_status,
                claim_owner,
                queued_at,
                claimed_at,
                lease_expires_at,
                heartbeat_at,
                next_attempt_at,
                attempts,
                last_claim_error,
                agent_profile_id,
                agent_profile_version,
                agent_config_snapshot,
                anchor_payload,
            ) = params
            self.run_anchors[task_run_id] = {
                "task_run_id": task_run_id,
                "session_id": session_id,
                "owner_key": owner_key,
                "owner_user_id": owner_user_id,
                "session_key": session_key,
                "current_step_run_id": current_step_run_id,
                "durable_status": durable_status,
                "queue_status": queue_status,
                "claim_owner": claim_owner,
                "queued_at": queued_at,
                "claimed_at": claimed_at,
                "lease_expires_at": lease_expires_at,
                "heartbeat_at": heartbeat_at,
                "next_attempt_at": next_attempt_at,
                "attempts": attempts,
                "last_claim_error": last_claim_error,
                "agent_profile_id": agent_profile_id,
                "agent_profile_version": agent_profile_version,
                "agent_config_snapshot": agent_config_snapshot,
                "anchor_payload": anchor_payload,
            }
        elif normalized.startswith("SELECT * FROM run_anchors WHERE"):
            return _FakeCursor([self.run_anchors[params[0]]] if params[0] in self.run_anchors else [])
        elif normalized.startswith("SELECT * FROM run_anchors ORDER"):
            return _FakeCursor(list(self.run_anchors.values()))
        elif normalized.startswith("SELECT COUNT(*) FROM run_anchors"):
            return _FakeCursor([{"count": len(self._filtered_run_anchor_rows(normalized, params or ()))}])
        elif normalized.startswith("SELECT task_run_id, owner_key, session_key"):
            return _FakeCursor(self._filtered_run_anchor_rows(normalized, params or ()))
        elif normalized.startswith("INSERT INTO step_anchors"):
            step_run_id, task_run_id, parent_step_run_id, worker_session_id, step_order, step_type, durable_status, anchor_payload = params
            self.step_anchors[step_run_id] = {
                "step_run_id": step_run_id,
                "task_run_id": task_run_id,
                "parent_step_run_id": parent_step_run_id,
                "worker_session_id": worker_session_id,
                "step_order": step_order,
                "step_type": step_type,
                "durable_status": durable_status,
                "anchor_payload": anchor_payload,
            }
        elif normalized.startswith("SELECT * FROM step_anchors"):
            return _FakeCursor([self.step_anchors[params[0]]] if params[0] in self.step_anchors else [])
        elif normalized.startswith("SELECT * FROM ai_agent_profiles"):
            owner_key, profile_key, profile_version = params
            key = (owner_key, profile_key, profile_version)
            return _FakeCursor([self.agent_profiles[key]] if key in self.agent_profiles else [])
        return _FakeCursor()

    def commit(self):
        self.commits += 1

    def _filtered_run_anchor_rows(self, normalized_sql: str, params: tuple) -> list[dict]:
        filter_params = params[:-2] if "LIMIT %s OFFSET %s" in normalized_sql else params
        task_statuses = {"PENDING", "RUNNING", "WAITING", "BLOCKED", "COMPLETED", "FAILED", "CANCELED"}
        statuses = {value for value in filter_params if value in task_statuses}
        owner_key = None
        session_key = None
        if "owner_key = %s" in normalized_sql and "session_key = %s" in normalized_sql:
            owner_key = filter_params[-2]
            session_key = filter_params[-1]
        elif "owner_key = %s" in normalized_sql:
            owner_key = filter_params[-1]
        elif "session_key = %s" in normalized_sql:
            session_key = filter_params[-1]
        rows = []
        for row in self.run_anchors.values():
            payload = json.loads(row["anchor_payload"]) if isinstance(row.get("anchor_payload"), str) else row.get("anchor_payload", {})
            task_payload = payload.get("task") or {}
            if statuses and task_payload.get("status") not in statuses:
                continue
            if owner_key is not None and str(row.get("owner_key")) != str(owner_key):
                continue
            if session_key is not None and row.get("session_key") != session_key:
                continue
            rows.append(row)
        return rows


def test_postgres_durable_repository_upserts_run_and_step_anchors():
    connection = _FakeDurableConnection()
    repository = PostgresDurableRepository(lambda: connection)

    run_anchor = repository.upsert_run_anchor(
        "task_pg_anchor",
        {
            "owner_key": "user_pg",
            "session_id": "agent_session_pg",
            "session_key": "session_pg",
            "current_step_run_id": "step_pg_anchor",
            "durable_status": "WAITING",
            "agent_profile_id": "agent_profile_pg",
            "agent_profile_version": 3,
            "agent_config_snapshot": {"model": "gpt-session", "enabled_toolsets": ["session"]},
            "anchor_payload": {"reason": "approval"},
        },
    )
    step_anchor = repository.upsert_step_anchor(
        "step_pg_anchor",
        {
            "task_run_id": "task_pg_anchor",
            "step_order": 3,
            "step_type": "agent.loop.execute",
            "durable_status": "WAITING",
            "anchor_payload": {"tool": "terminal.run"},
        },
    )

    assert run_anchor["owner_key"] == "user_pg"
    assert run_anchor["agent_profile_id"] == "agent_profile_pg"
    assert run_anchor["agent_profile_version"] == 3
    assert run_anchor["agent_config_snapshot"] == {"model": "gpt-session", "enabled_toolsets": ["session"]}
    assert run_anchor["anchor_payload"] == {"reason": "approval"}
    assert step_anchor["step_order"] == 3
    assert step_anchor["anchor_payload"] == {"tool": "terminal.run"}
    assert connection.commits == 2


def test_postgres_durable_repository_preserves_agent_profile_columns_when_appending_events():
    connection = _FakeDurableConnection()
    repository = PostgresTaskRepository(lambda: connection)

    repository.upsert_run_anchor(
        "task_pg_agent_anchor",
        {
            "owner_key": "user_pg",
            "session_key": "session_pg",
            "agent_profile_id": "agent_profile_pg",
            "agent_profile_version": 2,
            "agent_config_snapshot": {"model": "gpt-session"},
            "anchor_payload": {"task": {"task_run_id": "task_pg_agent_anchor"}},
        },
    )

    repository.append_event(
        TaskEventEnvelope(
            event_id="event-1",
            event_type="task.started",
            task_run_id="task_pg_agent_anchor",
            producer="test",
            occurred_at="2026-05-11T00:00:00+00:00",
            status="RUNNING",
        )
    )

    anchor = repository.get_run_anchor("task_pg_agent_anchor")
    assert anchor is not None
    assert anchor["agent_profile_id"] == "agent_profile_pg"
    assert anchor["agent_profile_version"] == 2
    assert anchor["agent_config_snapshot"] == {"model": "gpt-session"}


def test_postgres_task_repository_copies_task_settings_to_run_anchor_config_snapshot():
    connection = _FakeDurableConnection()
    repository = PostgresTaskRepository(lambda: connection)

    repository.create_task(
        TaskRun(
            task_run_id="task_pg_settings_anchor",
            task_type="agent.loop",
            owner_key="42",
            status="RUNNING",
            input_payload={
                "settings_snapshot": {"model": "gpt-session", "systemPrompt": "세션 프롬프트"},
                "enabled_toolsets": ["session", "planning"],
                "delegation_policy": {"canDelegate": False},
                "targetAgentProfile": {"profileId": "agent_profile_42", "profileVersion": 2},
            },
        )
    )

    anchor = repository.get_run_anchor("task_pg_settings_anchor")
    assert anchor is not None
    assert anchor["agent_profile_id"] == "agent_profile_42"
    assert anchor["agent_profile_version"] == 2
    assert anchor["agent_config_snapshot"] == {
        "model": "gpt-session",
        "systemPrompt": "세션 프롬프트",
        "toolsets": ["session", "planning"],
        "delegationPolicy": {"canDelegate": False},
    }


def test_postgres_task_repository_marks_direct_pending_task_as_non_claimable_running_anchor():
    connection = _FakeDurableConnection()
    repository = PostgresTaskRepository(lambda: connection)

    repository.create_direct_task(
        TaskRun(
            task_run_id="task_pg_direct_anchor",
            task_type="agent.loop",
            owner_key="42",
            session_key="session_pg_direct",
            status="PENDING",
        )
    )

    anchor = repository.get_run_anchor("task_pg_direct_anchor")
    assert anchor is not None
    assert anchor["queue_status"] == "running"
    assert anchor["claim_owner"] is None
    assert anchor["attempts"] == 0
    assert anchor["anchor_payload"]["task"]["status"] == "PENDING"
    assert anchor["anchor_payload"]["task"]["queue_status"] == "running"


def test_postgres_task_repository_marks_completed_claim_as_terminal():
    connection = _FakeDurableConnection()
    repository = PostgresTaskRepository(lambda: connection)
    task = TaskRun(
        task_run_id="task_pg_claim_complete",
        task_type="agent.loop",
        owner_key="42",
        session_key="session_pg_claim",
        status="RUNNING",
        queue_status="claimed",
        claim_owner="worker-a",
    )
    repository.create_task(task)

    task.status = "COMPLETED"
    repository.update_task(task)

    anchor = repository.get_run_anchor("task_pg_claim_complete")
    assert anchor is not None
    assert anchor["queue_status"] == "terminal"
    assert anchor["claim_owner"] is None
    assert anchor["lease_expires_at"] is None
    assert anchor["heartbeat_at"] is None
    assert anchor["anchor_payload"]["task"]["queue_status"] == "terminal"


def test_postgres_task_repository_filters_statuses_in_sql_without_loading_all_run_anchors():
    connection = _FakeDurableConnection()
    repository = PostgresTaskRepository(lambda: connection)
    repository.create_task(
        TaskRun(
            task_run_id="task_pg_active_owner",
            task_type="agent.loop",
            owner_key="42",
            session_key="session_pg_active",
            status="RUNNING",
        )
    )
    repository.create_task(
        TaskRun(
            task_run_id="task_pg_active_other_owner",
            task_type="agent.loop",
            owner_key="43",
            session_key="session_pg_active",
            status="RUNNING",
        )
    )
    repository.create_task(
        TaskRun(
            task_run_id="task_pg_terminal_owner",
            task_type="agent.loop",
            owner_key="42",
            session_key="session_pg_active",
            status="COMPLETED",
        )
    )
    connection.executed.clear()

    total = repository.count_tasks_by_statuses(
        ["PENDING", "RUNNING", "WAITING", "BLOCKED"],
        owner_key="42",
        session_key="session_pg_active",
    )
    tasks = repository.list_tasks_by_statuses(
        ["PENDING", "RUNNING", "WAITING", "BLOCKED"],
        owner_key="42",
        session_key="session_pg_active",
        limit=10,
        offset=0,
    )

    assert total == 1
    assert [task.task_run_id for task in tasks] == ["task_pg_active_owner"]
    assert any(sql.startswith("SELECT COUNT(*) FROM run_anchors") for sql, _ in connection.executed)
    assert any("anchor_payload" in sql and "FROM run_anchors" in sql for sql, _ in connection.executed)
    assert not any(sql.startswith("SELECT * FROM run_anchors ORDER") for sql, _ in connection.executed)


def test_postgres_task_repository_recovers_stale_running_task_as_terminal():
    connection = _FakeDurableConnection()
    repository = PostgresTaskRepository(lambda: connection)
    task = TaskRun(
        task_run_id="task_pg_stale_recover",
        task_type="agent.loop",
        owner_key="42",
        session_key="session_pg_stale",
        status="RUNNING",
        queue_status="running",
        claim_owner="worker-a",
    )
    repository.create_task(task)
    old_updated_at = utc_now() - timedelta(minutes=20)
    connection.run_anchors["task_pg_stale_recover"]["updated_at"] = old_updated_at
    payload = json.loads(connection.run_anchors["task_pg_stale_recover"]["anchor_payload"])
    payload["task"]["updated_at"] = old_updated_at.isoformat()
    connection.run_anchors["task_pg_stale_recover"]["anchor_payload"] = payload

    recovered = repository.recover_stale_task_run("task_pg_stale_recover", reason="claim_signal_stale")

    assert recovered is not None
    assert recovered.status == "FAILED"
    assert recovered.queue_status == "terminal"
    assert recovered.error_message == "실행 상태가 만료되어 자동 복구되었습니다."
    anchor = repository.get_run_anchor("task_pg_stale_recover")
    assert anchor is not None
    assert anchor["queue_status"] == "terminal"
    assert anchor["anchor_payload"]["task"]["status"] == "FAILED"
    assert anchor["anchor_payload"]["task"]["queue_status"] == "terminal"


def test_postgres_task_repository_does_not_recover_refreshed_running_task():
    connection = _FakeDurableConnection()
    repository = PostgresTaskRepository(lambda: connection)
    task = TaskRun(
        task_run_id="task_pg_refreshed_recover",
        task_type="agent.loop",
        owner_key="42",
        session_key="session_pg_refreshed",
        status="RUNNING",
        queue_status="running",
        lease_expires_at=utc_now() + timedelta(minutes=5),
        heartbeat_at=utc_now(),
    )
    repository.create_task(task)

    recovered = repository.recover_stale_task_run("task_pg_refreshed_recover", reason="claim_signal_stale")

    assert recovered is None
    saved = repository.get_task("task_pg_refreshed_recover")
    assert saved is not None
    assert saved.status == "RUNNING"
    assert saved.queue_status == "running"


def test_postgres_task_repository_reads_agent_profile_by_key():
    connection = _FakeDurableConnection()
    connection.agent_profiles[("system", "worker.default", 1)] = {
        "profile_id": "system:worker.default:1",
        "owner_key": "system",
        "profile_key": "worker.default",
        "profile_version": 1,
        "agent_type": "worker",
        "config_snapshot": '{"toolsets":["terminal"]}',
        "delegation_policy": '{"canDelegate":false}',
    }
    repository = PostgresTaskRepository(lambda: connection)

    profile = repository.get_agent_profile("worker.default")

    assert profile["profile_id"] == "system:worker.default:1"
    assert profile["config_snapshot"] == {"toolsets": ["terminal"]}
    assert profile["delegation_policy"] == {"canDelegate": False}
