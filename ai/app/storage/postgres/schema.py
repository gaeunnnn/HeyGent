from __future__ import annotations

# Postgres durable 저장소는 재시작 뒤에도 잃으면 안 되는 anchor와 감사 기록만 맡는다.
# TaskRun/StepRun 전체 progress의 canonical은 여기로 옮기지 않고, Redis projection은 빠른 화면 조회와 fan-out을 담당한다.
POSTGRES_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS agent_sessions (
        session_id TEXT PRIMARY KEY,
        owner_key TEXT NOT NULL,
        owner_user_id BIGINT REFERENCES users(id),
        session_key TEXT NOT NULL,
        task_run_id TEXT,
        parent_session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE SET NULL,
        parent_step_run_id TEXT,
        agent_profile_id TEXT,
        agent_profile_version INTEGER NOT NULL DEFAULT 1,
        agent_config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        session_role TEXT NOT NULL DEFAULT 'main' CHECK (session_role IN ('main', 'user_subagent', 'worker', 'domain')),
        session_source TEXT NOT NULL DEFAULT 'agent.loop',
        history_version BIGINT NOT NULL DEFAULT 0,
        running_task_run_id TEXT,
        workspace_key TEXT,
        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE', 'WAITING', 'COMPLETED', 'FAILED', 'CANCELED')),
        title TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        settings JSONB NOT NULL DEFAULT '{}'::jsonb,
        archived_at TIMESTAMPTZ,
        deleted_at TIMESTAMPTZ,
        deleted_by BIGINT REFERENCES users(id),
        purge_after TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        ended_at TIMESTAMPTZ,
        CONSTRAINT agent_sessions_public_owner_user_required
            CHECK (session_source <> 'api.session' OR owner_user_id IS NOT NULL)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS agent_messages (
        message_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
        task_run_id TEXT,
        step_run_id TEXT,
        event_id TEXT,
        event_type TEXT,
        message_sequence BIGINT NOT NULL,
        role TEXT NOT NULL,
        content JSONB NOT NULL DEFAULT '{}'::jsonb,
        provider_name TEXT,
        model_name TEXT,
        metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (session_id, message_sequence)
    );
    """,
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
    CREATE TABLE IF NOT EXISTS approval_requests (
        approval_id TEXT PRIMARY KEY,
        owner_user_id BIGINT REFERENCES users(id),
        task_run_id TEXT NOT NULL,
        step_run_id TEXT NOT NULL,
        tool_call_id TEXT,
        status TEXT NOT NULL CHECK (status IN ('PENDING', 'RESOLVED', 'CANCELED', 'EXPIRED')),
        request_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        response_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        resolved_at TIMESTAMPTZ
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS run_anchors (
        task_run_id TEXT PRIMARY KEY,
        session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE SET NULL,
        owner_key TEXT NOT NULL,
        owner_user_id BIGINT REFERENCES users(id),
        session_key TEXT,
        current_step_run_id TEXT,
        durable_status TEXT NOT NULL DEFAULT 'OPEN' CHECK (durable_status IN ('OPEN', 'WAITING', 'TERMINAL')),
        queue_status TEXT NOT NULL DEFAULT 'queued' CHECK (queue_status IN ('queued', 'claimed', 'running', 'waiting', 'terminal', 'failed_retry', 'canceled')),
        claim_owner TEXT,
        queued_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        claimed_at TIMESTAMPTZ,
        lease_expires_at TIMESTAMPTZ,
        heartbeat_at TIMESTAMPTZ,
        next_attempt_at TIMESTAMPTZ,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_claim_error TEXT,
        anchor_generation BIGINT NOT NULL DEFAULT 1,
        revision BIGINT NOT NULL DEFAULT 0,
        event_epoch BIGINT NOT NULL DEFAULT 1,
        last_durable_sequence BIGINT NOT NULL DEFAULT 0,
        agent_profile_id TEXT,
        agent_profile_version INTEGER,
        agent_config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        anchor_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS step_anchors (
        step_run_id TEXT PRIMARY KEY,
        task_run_id TEXT NOT NULL REFERENCES run_anchors(task_run_id) ON DELETE CASCADE,
        parent_step_run_id TEXT REFERENCES step_anchors(step_run_id) ON DELETE SET NULL,
        worker_session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE SET NULL,
        step_order INTEGER NOT NULL,
        step_type TEXT NOT NULL,
        durable_status TEXT NOT NULL DEFAULT 'OPEN' CHECK (durable_status IN ('OPEN', 'WAITING', 'TERMINAL')),
        anchor_generation BIGINT NOT NULL DEFAULT 1,
        revision BIGINT NOT NULL DEFAULT 0,
        anchor_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS worker_handoffs (
        handoff_id TEXT PRIMARY KEY,
        task_run_id TEXT NOT NULL REFERENCES run_anchors(task_run_id) ON DELETE CASCADE,
        parent_step_run_id TEXT NOT NULL REFERENCES step_anchors(step_run_id) ON DELETE CASCADE,
        parent_session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE SET NULL,
        worker_session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE SET NULL,
        worker_profile_id TEXT,
        worker_profile_version INTEGER,
        status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELED')),
        input_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
        result_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        accepted_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_agent_profiles (
        profile_id TEXT PRIMARY KEY,
        owner_key TEXT NOT NULL,
        owner_user_id BIGINT REFERENCES users(id),
        session_id TEXT REFERENCES agent_sessions(session_id) ON DELETE CASCADE,
        profile_key TEXT NOT NULL,
        profile_version INTEGER NOT NULL DEFAULT 1,
        agent_type TEXT NOT NULL CHECK (agent_type IN ('main', 'user_subagent', 'worker', 'domain')),
        provider_name TEXT,
        model_name TEXT,
        config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        delegation_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        template_key TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (owner_key, profile_key, profile_version)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS ai_agent_templates (
        template_id TEXT PRIMARY KEY,
        owner_key TEXT NOT NULL,
        template_key TEXT NOT NULL,
        template_version INTEGER NOT NULL DEFAULT 1,
        default_agent_type TEXT NOT NULL,
        default_config_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
        default_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (owner_key, template_key, template_version)
    );
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
    CREATE TABLE IF NOT EXISTS provider_oauth_states (
        provider_name TEXT NOT NULL,
        state TEXT NOT NULL,
        redirect_uri TEXT NOT NULL,
        code_verifier_secret_ref TEXT,
        status TEXT NOT NULL CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED', 'CANCELED')),
        expires_at TIMESTAMPTZ NOT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        consumed_at TIMESTAMPTZ,
        PRIMARY KEY (provider_name, state)
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS provider_tokens (
        provider_name TEXT PRIMARY KEY,
        token_secret_ref TEXT NOT NULL,
        refresh_secret_ref TEXT,
        token_type TEXT,
        scope_text TEXT NOT NULL DEFAULT '',
        expires_at TIMESTAMPTZ,
        token_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
    );
    """,
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
        flow_order INTEGER,
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
    CREATE TABLE IF NOT EXISTS work_wake_requests (
        wake_id TEXT PRIMARY KEY,
        work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
        root_work_id TEXT REFERENCES work_items(work_id) ON DELETE SET NULL,
        reason TEXT NOT NULL,
        status TEXT NOT NULL CHECK (status IN ('queued', 'claimed', 'dispatching', 'scheduled_retry', 'dispatched', 'completed', 'skipped', 'failed')),
        requested_by_task_run_id TEXT,
        task_run_id TEXT,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        claimed_at TIMESTAMPTZ,
        next_attempt_at TIMESTAMPTZ,
        completed_at TIMESTAMPTZ
    );
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
    CREATE TABLE IF NOT EXISTS work_read_states (
        work_id TEXT NOT NULL REFERENCES work_items(work_id) ON DELETE CASCADE,
        owner_user_id BIGINT NOT NULL REFERENCES users(id),
        last_read_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        archived_at TIMESTAMPTZ,
        PRIMARY KEY (work_id, owner_user_id)
    );
    """,
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
    CREATE UNIQUE INDEX IF NOT EXISTS idx_approval_requests_one_pending_per_task
    ON approval_requests(task_run_id)
    WHERE status = 'PENDING';
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_messages_session_created
    ON agent_messages(session_id, created_at);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_agent_messages_session_sequence
    ON agent_messages(session_id, message_sequence);
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
    CREATE INDEX IF NOT EXISTS idx_session_command_receipts_owner
    ON session_command_receipts(owner_user_id, session_id, created_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_run_anchors_owner_session
    ON run_anchors(owner_key, session_key);
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
    """
    CREATE INDEX IF NOT EXISTS idx_approval_requests_task_pending
    ON approval_requests(task_run_id, created_at)
    WHERE status = 'PENDING';
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_step_anchors_task_order
    ON step_anchors(task_run_id, step_order);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_worker_handoffs_parent_step
    ON worker_handoffs(parent_step_run_id, created_at);
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
    CREATE INDEX IF NOT EXISTS idx_work_items_parent_flow_order
    ON work_items(parent_id, flow_order ASC, created_at ASC)
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
    """
    CREATE INDEX IF NOT EXISTS idx_work_wake_requests_status_created
    ON work_wake_requests(status, created_at ASC);
    """,
    """
    CREATE UNIQUE INDEX IF NOT EXISTS idx_work_wake_requests_work_active
    ON work_wake_requests(work_id)
    WHERE status IN ('queued', 'claimed', 'dispatching', 'scheduled_retry');
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_work_recovery_actions_work_created
    ON work_recovery_actions(work_id, created_at DESC);
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
    """
    CREATE INDEX IF NOT EXISTS idx_ai_agent_profiles_session
    ON ai_agent_profiles(session_id, agent_type, updated_at DESC);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_agent_instruction_documents_bundle
    ON ai_agent_instruction_documents(bundle_id, document_key);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ai_agent_secret_values_profile
    ON ai_agent_secret_values(profile_id, document_key, section_key);
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
    """
    CREATE INDEX IF NOT EXISTS idx_session_prototype_artifacts_active
    ON session_prototype_artifacts(session_id, owner_key, updated_at DESC)
    WHERE is_active = true;
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_session_prototype_artifact_versions_artifact
    ON session_prototype_artifact_versions(artifact_id, version_number DESC);
    """,
    """
    INSERT INTO ai_agent_profiles (
        profile_id,
        owner_key,
        profile_key,
        profile_version,
        agent_type,
        config_snapshot,
        delegation_policy
    )
    VALUES
        (
            'system:main.default:1',
            'system',
            'main.default',
            1,
            'main',
            '{"promptRole":"main","toolsets":["skills","session","planning","terminal","file","web","delegation"]}'::jsonb,
            '{"canDelegate":true,"maxWorkerDepth":1,"maxConcurrentWorkers":3}'::jsonb
        ),
        (
            'system:worker.default:1',
            'system',
            'worker.default',
            1,
            'worker',
            '{"promptRole":"worker","toolsets":["skills","terminal","file","web"]}'::jsonb,
            '{"canDelegate":false,"maxWorkerDepth":0,"hardTimeoutSeconds":900,"maxIterations":80}'::jsonb
        )
    ON CONFLICT (owner_key, profile_key, profile_version) DO UPDATE
    SET
        config_snapshot = EXCLUDED.config_snapshot,
        delegation_policy = EXCLUDED.delegation_policy;
    """,
]


def render_postgres_schema() -> str:
    """마이그레이션 도구가 실행 단위로 넘길 수 있도록 DDL 문자열을 합친다."""

    return "\n".join(statement.strip() for statement in POSTGRES_SCHEMA_STATEMENTS)
