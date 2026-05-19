from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from app.storage.postgres.schema import POSTGRES_SCHEMA_STATEMENTS


@dataclass(frozen=True, slots=True)
class PostgresMigration:
    """Postgres forward-only migration 한 단위를 표현한다."""

    migration_id: str
    statements: Sequence[str]


POSTGRES_MIGRATIONS: tuple[PostgresMigration, ...] = (
    PostgresMigration(
        migration_id="0001_initial_durable_schema",
        statements=POSTGRES_SCHEMA_STATEMENTS,
    ),
    PostgresMigration(
        migration_id="0002_run_anchor_session_key",
        statements=(
            """
            CREATE INDEX IF NOT EXISTS idx_run_anchors_owner_session
            ON run_anchors(owner_key, session_key);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0003_refresh_builtin_agent_profiles",
        statements=(
            """
            UPDATE ai_agent_profiles
            SET
                config_snapshot = '{"promptRole":"main","toolsets":["skills","session","planning","terminal","file","web","delegation"]}'::jsonb,
                delegation_policy = '{"canDelegate":true,"maxWorkerDepth":1,"maxConcurrentWorkers":3}'::jsonb
            WHERE owner_key = 'system'
              AND profile_key = 'main.default'
              AND profile_version = 1;
            """,
            """
            UPDATE ai_agent_profiles
            SET
                config_snapshot = '{"promptRole":"worker","toolsets":["skills","terminal","file","web"]}'::jsonb,
                delegation_policy = '{"canDelegate":false,"maxWorkerDepth":0,"hardTimeoutSeconds":900,"maxIterations":80}'::jsonb
            WHERE owner_key = 'system'
              AND profile_key = 'worker.default'
              AND profile_version = 1;
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0004_remove_legacy_routing_columns",
        statements=(
            """
            ALTER TABLE run_anchors
            DROP COLUMN IF EXISTS entry_handler_key;
            """,
            """
            ALTER TABLE step_anchors
            DROP COLUMN IF EXISTS handler_key;
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0005_session_runtime_state",
        statements=(
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS session_source TEXT NOT NULL DEFAULT 'agent.loop';
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS history_version BIGINT NOT NULL DEFAULT 0;
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS running_task_run_id TEXT;
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS workspace_key TEXT;
            """,
            """
            UPDATE agent_sessions
            SET session_source = COALESCE(metadata->>'source', session_source, 'agent.loop')
            WHERE session_source = 'agent.loop'
               OR session_source IS NULL;
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_messages_public_client_id
            ON agent_messages (session_id, (metadata->>'client_message_id'))
            WHERE role = 'user' AND metadata ? 'client_message_id';
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_agent_sessions_owner_source_updated
            ON agent_sessions (owner_key, session_source, updated_at DESC);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_agent_messages_session_sequence
            ON agent_messages(session_id, message_sequence);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0006_session_owner_lifecycle_settings",
        statements=(
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id);
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS settings JSONB NOT NULL DEFAULT '{}'::jsonb;
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS deleted_by BIGINT REFERENCES users(id);
            """,
            """
            ALTER TABLE agent_sessions
            ADD COLUMN IF NOT EXISTS purge_after TIMESTAMPTZ;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id);
            """,
            """
            ALTER TABLE approval_requests
            ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id);
            """,
            """
            ALTER TABLE ai_agent_profiles
            ADD COLUMN IF NOT EXISTS owner_user_id BIGINT REFERENCES users(id);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_agent_sessions_owner_user_source_updated
            ON agent_sessions (owner_user_id, session_source, updated_at DESC)
            WHERE deleted_at IS NULL;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_agent_sessions_purge_after
            ON agent_sessions (purge_after)
            WHERE deleted_at IS NOT NULL AND purge_after IS NOT NULL;
            """,
            """
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_constraint
                    WHERE conname = 'agent_sessions_public_owner_user_required'
                ) THEN
                    ALTER TABLE agent_sessions
                    ADD CONSTRAINT agent_sessions_public_owner_user_required
                    CHECK (session_source <> 'api.session' OR owner_user_id IS NOT NULL)
                    NOT VALID;
                END IF;
            END $$;
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0007_session_command_receipts",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS session_command_receipts (
                session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                client_command_id TEXT NOT NULL,
                owner_key TEXT NOT NULL,
                owner_user_id BIGINT REFERENCES users(id),
                command_signature TEXT NOT NULL,
                response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (session_id, client_command_id)
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_session_command_receipts_owner
            ON session_command_receipts(owner_user_id, session_id, created_at DESC);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0008_work_board_schema",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS work_counters (
                session_id TEXT PRIMARY KEY REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                next_number BIGINT NOT NULL DEFAULT 1
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_items (
                work_id TEXT PRIMARY KEY,
                identifier TEXT NOT NULL,
                session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                owner_key TEXT NOT NULL,
                owner_user_id BIGINT REFERENCES users(id),
                title TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL CHECK (status IN ('backlog', 'todo', 'in_progress', 'in_review', 'blocked', 'done', 'cancelled')),
                assignee_agent_id TEXT,
                parent_id TEXT REFERENCES work_items(work_id) ON DELETE SET NULL,
                source TEXT NOT NULL DEFAULT 'work_mode',
                raw_user_input TEXT,
                execution_instruction TEXT,
                expected_deliverable TEXT,
                acceptance_criteria JSONB NOT NULL DEFAULT '[]'::jsonb,
                constraints_payload JSONB NOT NULL DEFAULT '[]'::jsonb,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                client_request_id TEXT,
                active_run_id TEXT,
                latest_run_id TEXT,
                archived_at TIMESTAMPTZ,
                deleted_at TIMESTAMPTZ,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                started_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ,
                UNIQUE (session_id, identifier)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_labels (
                label_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                owner_key TEXT NOT NULL,
                name TEXT NOT NULL,
                color TEXT NOT NULL DEFAULT '#64748b',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (session_id, owner_key, name)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_label_links (
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                label_id TEXT NOT NULL REFERENCES work_labels(label_id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (work_id, label_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_comments (
                comment_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                author_type TEXT NOT NULL CHECK (author_type IN ('user', 'agent', 'system')),
                author_id TEXT,
                task_run_id TEXT,
                body TEXT NOT NULL,
                resume_requested BOOLEAN NOT NULL DEFAULT false,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_relations (
                source_work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                target_work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL CHECK (relation_type IN ('blocks', 'related')),
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (source_work_id, target_work_id, relation_type)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_runs (
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                task_run_id TEXT NOT NULL,
                run_kind TEXT NOT NULL DEFAULT 'initial',
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (work_id, task_run_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_read_states (
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                owner_user_id BIGINT NOT NULL REFERENCES users(id),
                last_read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                archived_at TIMESTAMPTZ,
                PRIMARY KEY (work_id, owner_user_id)
            );
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_work_items_session_client_request
            ON work_items(session_id, client_request_id)
            WHERE client_request_id IS NOT NULL;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_items_session_status_updated
            ON work_items(session_id, status, updated_at DESC)
            WHERE deleted_at IS NULL;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_items_parent
            ON work_items(parent_id, updated_at DESC)
            WHERE deleted_at IS NULL;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_comments_work_created
            ON work_comments(work_id, created_at);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_runs_work_created
            ON work_runs(work_id, created_at DESC);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0009_agent_instruction_documents",
        statements=(
            """
            ALTER TABLE ai_agent_profiles
            ADD COLUMN IF NOT EXISTS session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE CASCADE;
            """,
            """
            ALTER TABLE ai_agent_profiles
            ADD COLUMN IF NOT EXISTS template_key TEXT;
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_agent_instruction_bundles (
                bundle_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL REFERENCES ai_agent_profiles(profile_id) ON DELETE CASCADE,
                owner_key TEXT NOT NULL,
                owner_user_id BIGINT REFERENCES users(id),
                session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                mode TEXT NOT NULL DEFAULT 'managed' CHECK (mode IN ('managed', 'external')),
                entry_document_key TEXT NOT NULL DEFAULT 'AGENTS.md',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (profile_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_agent_instruction_documents (
                document_id TEXT PRIMARY KEY,
                bundle_id TEXT NOT NULL REFERENCES ai_agent_instruction_bundles(bundle_id) ON DELETE CASCADE,
                document_key TEXT NOT NULL,
                display_name TEXT NOT NULL,
                content_format TEXT NOT NULL DEFAULT 'markdown',
                content TEXT NOT NULL DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (bundle_id, document_key)
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_agent_profiles_session
            ON ai_agent_profiles(session_id, agent_type, updated_at DESC);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_agent_instruction_documents_bundle
            ON ai_agent_instruction_documents(bundle_id, document_key);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0010_work_collaboration_surfaces",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS work_documents (
                document_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                document_key TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                format TEXT NOT NULL DEFAULT 'markdown',
                revision_number INTEGER NOT NULL DEFAULT 1,
                created_by TEXT,
                updated_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (work_id, document_key)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_document_revisions (
                revision_id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL REFERENCES work_documents(document_id) ON DELETE CASCADE,
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                document_key TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                format TEXT NOT NULL DEFAULT 'markdown',
                revision_number INTEGER NOT NULL,
                created_by TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_products (
                product_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                summary TEXT,
                product_type TEXT NOT NULL DEFAULT 'note',
                status TEXT NOT NULL DEFAULT 'draft',
                review_state TEXT NOT NULL DEFAULT 'none',
                uri TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS work_thread_interactions (
                interaction_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                kind TEXT NOT NULL CHECK (kind IN ('suggest_tasks', 'ask_user_questions', 'request_confirmation')),
                status TEXT NOT NULL DEFAULT 'pending',
                title TEXT,
                body TEXT,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                response JSONB NOT NULL DEFAULT '{}'::jsonb,
                continuation_policy TEXT NOT NULL DEFAULT 'none',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_documents_work_updated
            ON work_documents(work_id, updated_at DESC);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_document_revisions_document
            ON work_document_revisions(document_id, revision_number DESC);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_products_work_updated
            ON work_products(work_id, updated_at DESC);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_thread_interactions_work_updated
            ON work_thread_interactions(work_id, updated_at DESC);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0011_work_flow_order",
        statements=(
            """
            ALTER TABLE work_items
            ADD COLUMN IF NOT EXISTS flow_order INTEGER;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_items_parent_flow_order
            ON work_items(parent_id, flow_order ASC, created_at ASC)
            WHERE deleted_at IS NULL;
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0012_work_wake_requests",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS work_wake_requests (
                wake_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                root_work_id TEXT REFERENCES work_items(work_id) ON DELETE SET NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'dispatching', 'dispatched', 'completed', 'skipped', 'failed')),
                requested_by_task_run_id TEXT,
                task_run_id TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                claimed_at TIMESTAMPTZ,
                completed_at TIMESTAMPTZ
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_wake_requests_status_created
            ON work_wake_requests(status, created_at ASC);
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_work_wake_requests_work_active
            ON work_wake_requests(work_id)
            WHERE status IN ('queued', 'claimed', 'dispatching');
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0013_work_recovery_actions",
        statements=(
            """
            ALTER TABLE work_wake_requests
            ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE work_wake_requests
            DROP CONSTRAINT IF EXISTS work_wake_requests_status_check;
            """,
            """
            ALTER TABLE work_wake_requests
            ADD CONSTRAINT work_wake_requests_status_check
            CHECK (status IN ('queued', 'claimed', 'dispatching', 'scheduled_retry', 'dispatched', 'completed', 'skipped', 'failed'));
            """,
            """
            DROP INDEX IF EXISTS idx_work_wake_requests_work_active;
            """,
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_work_wake_requests_work_active
            ON work_wake_requests(work_id)
            WHERE status IN ('queued', 'claimed', 'dispatching', 'scheduled_retry');
            """,
            """
            CREATE TABLE IF NOT EXISTS work_recovery_actions (
                action_id TEXT PRIMARY KEY,
                work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
                action_type TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'ignored')),
                reason TEXT NOT NULL,
                idempotency_key TEXT NOT NULL UNIQUE,
                task_run_id TEXT,
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                resolved_at TIMESTAMPTZ
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_work_recovery_actions_work_created
            ON work_recovery_actions(work_id, created_at DESC);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0014_task_run_queue_claims",
        statements=(
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS queue_status TEXT;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS claim_owner TEXT;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS queued_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS attempts INTEGER;
            """,
            """
            ALTER TABLE run_anchors
            ADD COLUMN IF NOT EXISTS last_claim_error TEXT;
            """,
            """
            UPDATE run_anchors
            SET queue_status = CASE
                    WHEN anchor_payload->'task'->>'status' = 'PENDING' THEN 'queued'
                    WHEN anchor_payload->'task'->>'status' = 'RUNNING' THEN 'running'
                    WHEN anchor_payload->'task'->>'status' = 'WAITING' THEN 'waiting'
                    WHEN anchor_payload->'task'->>'status' = 'CANCELED' THEN 'canceled'
                    WHEN anchor_payload->'task'->>'status' IN ('COMPLETED', 'FAILED') THEN 'terminal'
                    ELSE 'terminal'
                END,
                queued_at = COALESCE(queued_at, created_at),
                attempts = COALESCE(attempts, 0)
            WHERE queue_status IS NULL OR queued_at IS NULL OR attempts IS NULL;
            """,
            """
            ALTER TABLE run_anchors
            ALTER COLUMN queue_status SET DEFAULT 'queued';
            """,
            """
            ALTER TABLE run_anchors
            ALTER COLUMN queue_status SET NOT NULL;
            """,
            """
            ALTER TABLE run_anchors
            ALTER COLUMN queued_at SET DEFAULT now();
            """,
            """
            ALTER TABLE run_anchors
            ALTER COLUMN queued_at SET NOT NULL;
            """,
            """
            ALTER TABLE run_anchors
            ALTER COLUMN attempts SET DEFAULT 0;
            """,
            """
            ALTER TABLE run_anchors
            ALTER COLUMN attempts SET NOT NULL;
            """,
            """
            ALTER TABLE run_anchors
            DROP CONSTRAINT IF EXISTS run_anchors_queue_status_check;
            """,
            """
            ALTER TABLE run_anchors
            ADD CONSTRAINT run_anchors_queue_status_check
            CHECK (queue_status IN ('queued', 'claimed', 'running', 'waiting', 'terminal', 'failed_retry', 'canceled'));
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_anchors_queue_claim
            ON run_anchors(queue_status, next_attempt_at, queued_at ASC)
            WHERE queue_status IN ('queued', 'failed_retry');
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_anchors_lease_expiry
            ON run_anchors(lease_expires_at)
            WHERE queue_status IN ('claimed', 'running') AND lease_expires_at IS NOT NULL;
            """,
            """
            DROP INDEX IF EXISTS idx_run_anchors_one_active_per_owner_session;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_anchors_active_owner_session
            ON run_anchors(owner_key, session_key)
            WHERE session_key IS NOT NULL AND queue_status IN ('queued', 'claimed', 'running', 'waiting', 'failed_retry');
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0015_allow_nested_session_agent_runs",
        statements=(
            """
            DROP INDEX IF EXISTS idx_run_anchors_one_active_per_owner_session;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_run_anchors_active_owner_session
            ON run_anchors(owner_key, session_key)
            WHERE session_key IS NOT NULL AND queue_status IN ('queued', 'claimed', 'running', 'waiting', 'failed_retry');
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0016_user_skill_settings",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS ai_skill_catalog (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL UNIQUE,
                display_name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT 'builtin' CHECK (source_type IN ('builtin', 'custom')),
                source_path TEXT,
                version INTEGER NOT NULL DEFAULT 1,
                default_enabled BOOLEAN NOT NULL DEFAULT true,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_user_skill_settings (
                owner_key TEXT NOT NULL,
                owner_user_id BIGINT REFERENCES users(id),
                skill_id TEXT NOT NULL REFERENCES ai_skill_catalog(skill_id) ON DELETE CASCADE,
                enabled BOOLEAN NOT NULL,
                config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (owner_key, skill_id)
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS ai_agent_skill_settings (
                profile_id TEXT NOT NULL REFERENCES ai_agent_profiles(profile_id) ON DELETE CASCADE,
                skill_id TEXT NOT NULL REFERENCES ai_skill_catalog(skill_id) ON DELETE CASCADE,
                enabled BOOLEAN NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                PRIMARY KEY (profile_id, skill_id)
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_skill_catalog_source
            ON ai_skill_catalog(source_type, name);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_user_skill_settings_owner_enabled
            ON ai_user_skill_settings(owner_key, enabled);
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_agent_skill_settings_profile_enabled
            ON ai_agent_skill_settings(profile_id, enabled);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0017_workflow_templates",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS workflow_templates (
                template_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                owner_user_id BIGINT REFERENCES users(id),
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                graph JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_templates_owner
            ON workflow_templates(owner_key, updated_at DESC);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0018_session_prototype_artifacts",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS session_prototype_artifacts (
                artifact_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                owner_key TEXT NOT NULL,
                title TEXT NOT NULL,
                framework TEXT NOT NULL DEFAULT 'react' CHECK (framework IN ('react', 'html')),
                styling TEXT NOT NULL DEFAULT 'css' CHECK (styling IN ('css', 'tailwind', 'mixed')),
                design_preset_id TEXT,
                active_version_id TEXT,
                status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'archived')),
                is_active BOOLEAN NOT NULL DEFAULT true,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """,
            """
            CREATE TABLE IF NOT EXISTS session_prototype_artifact_versions (
                version_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL REFERENCES session_prototype_artifacts(artifact_id) ON DELETE CASCADE,
                session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
                owner_key TEXT NOT NULL,
                version_number INTEGER NOT NULL,
                prompt_message_id TEXT,
                task_run_id TEXT,
                files_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                entry_file TEXT NOT NULL DEFAULT '/src/App.tsx',
                summary TEXT NOT NULL DEFAULT '',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (artifact_id, version_number)
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_session_prototype_artifacts_active
            ON session_prototype_artifacts(session_id, owner_key, updated_at DESC)
            WHERE is_active = true;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_session_prototype_artifact_versions_artifact
            ON session_prototype_artifact_versions(artifact_id, version_number DESC);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0018_workflow_templates_session_scope",
        statements=(
            """
            ALTER TABLE workflow_templates
            ADD COLUMN IF NOT EXISTS session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE CASCADE;
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_workflow_templates_session
            ON workflow_templates(session_id, updated_at DESC);
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0019_remove_removed_browser_toolset",
        statements=(
            """
            UPDATE ai_agent_profiles
            SET config_snapshot = jsonb_set(
                config_snapshot,
                '{toolsets}',
                COALESCE(
                    (
                        SELECT jsonb_agg(toolset_name)
                        FROM jsonb_array_elements(config_snapshot->'toolsets') AS toolset_name
                        WHERE toolset_name <> to_jsonb('browser'::text)
                    ),
                    '[]'::jsonb
                ),
                true
            )
            WHERE config_snapshot ? 'toolsets'
              AND config_snapshot->'toolsets' @> '["browser"]'::jsonb;
            """,
            """
            UPDATE agent_sessions
            SET settings = jsonb_set(
                settings,
                '{toolsets}',
                COALESCE(
                    (
                        SELECT jsonb_agg(toolset_name)
                        FROM jsonb_array_elements(settings->'toolsets') AS toolset_name
                        WHERE toolset_name <> to_jsonb('browser'::text)
                    ),
                    '[]'::jsonb
                ),
                true
            )
            WHERE settings ? 'toolsets'
              AND settings->'toolsets' @> '["browser"]'::jsonb;
            """,
        ),
    ),
    PostgresMigration(
        migration_id="0020_agent_secret_values",
        statements=(
            """
            CREATE TABLE IF NOT EXISTS ai_agent_secret_values (
                secret_value_id TEXT PRIMARY KEY,
                owner_key TEXT NOT NULL,
                owner_user_id BIGINT REFERENCES users(id),
                profile_id TEXT NOT NULL REFERENCES ai_agent_profiles(profile_id) ON DELETE CASCADE,
                document_key TEXT NOT NULL,
                section_key TEXT NOT NULL,
                secret_key TEXT NOT NULL,
                encrypted_value TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (profile_id, document_key, section_key, secret_key)
            );
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_ai_agent_secret_values_profile
            ON ai_agent_secret_values(profile_id, document_key, section_key);
            """,
        ),
    ),
)


SCHEMA_MIGRATIONS_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    migration_id TEXT PRIMARY KEY,
    applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def apply_postgres_migrations(
    connection: Any,
    *,
    migrations: Sequence[PostgresMigration] = POSTGRES_MIGRATIONS,
) -> list[str]:
    """아직 적용되지 않은 Postgres migration을 순서대로 실행한다."""

    connection.execute(SCHEMA_MIGRATIONS_SQL)
    rows = connection.execute("SELECT migration_id FROM schema_migrations").fetchall()
    applied_migration_ids = {_first_column(row) for row in rows}
    newly_applied: list[str] = []

    for migration in migrations:
        if migration.migration_id in applied_migration_ids:
            continue
        for statement in migration.statements:
            connection.execute(statement)
        connection.execute(
            "INSERT INTO schema_migrations (migration_id) VALUES (%s)",
            (migration.migration_id,),
        )
        newly_applied.append(migration.migration_id)

    connection.commit()
    return newly_applied


def _first_column(row: Any) -> str:
    if isinstance(row, dict):
        return str(row["migration_id"])
    return str(row[0])
