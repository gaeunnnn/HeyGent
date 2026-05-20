from __future__ import annotations

import json
from typing import Any, Callable

from app.core.time import utc_now
from app.core.utils.ids import new_id


class PostgresSessionStore:
    """agent transcript를 Postgres agent_sessions/agent_messages에 저장한다.

    TranscriptStore 호출부와 같은 응답 형태를 유지해 agent.loop replay 코드를 크게 흔들지 않는다.
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self.connection_factory = connection_factory

    def create_session(
        self,
        *,
        session_id: str,
        session_key: str,
        source: str,
        user_id: str | None = None,
        model: str | None = None,
        system_prompt: str | None = None,
        parent_session_id: str | None = None,
        title: str | None = None,
        metadata: dict[str, Any] | None = None,
        settings: dict[str, Any] | None = None,
    ) -> str:
        metadata_payload = dict(metadata or {})
        if system_prompt and not metadata_payload.get("system_prompt_snapshot"):
            metadata_payload["system_prompt_snapshot"] = system_prompt
        metadata_payload.update(
            {
                "source": source,
                "user_id": user_id,
                "model": model,
                "system_prompt": system_prompt,
                "message_count": 0,
            }
        )
        owner_key = user_id or str(metadata_payload.get("owner_key") or "local")
        owner_user_id = _owner_user_id(owner_key)
        connection = self.connection_factory()
        connection.execute(
            f"""
            INSERT INTO agent_sessions (
                session_id, owner_key, owner_user_id, session_key, parent_session_id,
                parent_step_run_id, agent_profile_id, agent_profile_version, agent_config_snapshot,
                session_role, session_source, history_version, running_task_run_id, workspace_key,
                status, title, metadata, settings, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, 0, NULL, %s, 'ACTIVE', %s, %s::jsonb, %s::jsonb, now(), now())
            ON CONFLICT (session_id) DO NOTHING
            """,
            (
                session_id,
                owner_key,
                owner_user_id,
                session_key,
                parent_session_id,
                metadata_payload.get("parent_step_run_id"),
                metadata_payload.get("agent_profile_id"),
                int(metadata_payload.get("agent_profile_version") or 1),
                _json(metadata_payload.get("agent_config_snapshot") or {}),
                _session_role(source, metadata_payload),
                source,
                metadata_payload.get("workspace_key"),
                title,
                _json(metadata_payload),
                _json(settings or {}),
            ),
        )
        connection.commit()
        return session_id

    def end_session(self, session_id: str, *, end_reason: str | None = None) -> None:
        connection = self.connection_factory()
        connection.execute(
            """
            UPDATE agent_sessions
            SET status = 'COMPLETED',
                ended_at = COALESCE(ended_at, now()),
                updated_at = now(),
                metadata = jsonb_set(metadata, '{end_reason}', to_jsonb(%s::text), true)
            WHERE session_id = %s AND ended_at IS NULL
            """,
            (end_reason, session_id),
        )
        connection.commit()

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute("SELECT * FROM agent_sessions WHERE session_id = %s", (session_id,)).fetchone()
        return _session_from_row(row)

    def list_sessions(
        self,
        owner: str | None = None,
        *,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        include_archived: bool = False,
        include_deleted: bool = False,
        source: str | None = None,
    ) -> list[dict[str, Any]]:
        connection = self.connection_factory()
        sql = "SELECT * FROM agent_sessions"
        effective_owner = owner if owner is not None else user_id
        where: list[str] = []
        if not include_deleted:
            where.append("deleted_at IS NULL")
        if not include_archived:
            where.append("archived_at IS NULL")
        params_list: list[Any] = []
        params: tuple[Any, ...]
        if effective_owner is not None:
            owner_sql, owner_params = _owner_filter(effective_owner)
            where.append(owner_sql)
            params_list.extend(owner_params)
        if source is not None:
            where.append("COALESCE(session_source, metadata->>'source') = %s")
            params_list.append(source)
        if where:
            sql += " WHERE " + " AND ".join(where)
        params = tuple([*params_list, limit, offset])
        sql += " ORDER BY updated_at DESC, created_at DESC LIMIT %s OFFSET %s"
        rows = connection.execute(sql, params).fetchall()
        return [record for row in rows if (record := _session_from_row(row)) is not None]

    def count_sessions(
        self,
        owner: str | None = None,
        *,
        user_id: str | None = None,
        include_archived: bool = False,
        include_deleted: bool = False,
        source: str | None = None,
    ) -> int:
        connection = self.connection_factory()
        sql = "SELECT COUNT(*) AS count FROM agent_sessions"
        effective_owner = owner if owner is not None else user_id
        where: list[str] = []
        if not include_deleted:
            where.append("deleted_at IS NULL")
        if not include_archived:
            where.append("archived_at IS NULL")
        params_list: list[Any] = []
        if effective_owner is not None:
            owner_sql, owner_params = _owner_filter(effective_owner)
            where.append(owner_sql)
            params_list.extend(owner_params)
        if source is not None:
            where.append("COALESCE(session_source, metadata->>'source') = %s")
            params_list.append(source)
        if where:
            sql += " WHERE " + " AND ".join(where)
        row = connection.execute(sql, tuple(params_list)).fetchone()
        return int((row or {}).get("count") or 0)

    def get_latest_session_by_key(self, session_key: str, *, owner: str | None = None) -> dict[str, Any] | None:
        connection = self.connection_factory()
        sql = "SELECT * FROM agent_sessions WHERE session_key = %s"
        params: tuple[Any, ...] = (session_key,)
        if owner is not None:
            owner_sql, owner_params = _owner_filter(owner)
            sql += f" AND {owner_sql}"
            params = tuple([session_key, *owner_params])
        sql += " ORDER BY created_at DESC LIMIT 1"
        row = connection.execute(sql, params).fetchone()
        return _session_from_row(row)

    def append_message(
        self,
        *,
        session_id: str,
        role: str,
        content: str | None,
        tool_name: str | None = None,
        tool_call_id: str | None = None,
        tool_calls: list[dict[str, Any]] | None = None,
        finish_reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        connection = self.connection_factory()
        sequence_row = connection.execute(
            "SELECT COALESCE(MAX(message_sequence), 0) + 1 AS next_sequence FROM agent_messages WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        sequence = int((sequence_row or {}).get("next_sequence") or 1)
        metadata_payload = dict(metadata or {})
        metadata_payload.update(
            {
                "tool_name": tool_name,
                "tool_call_id": tool_call_id,
                "tool_calls": tool_calls or [],
                "finish_reason": finish_reason,
            }
        )
        connection.execute(
            """
            INSERT INTO agent_messages (
                message_id, session_id, message_sequence, role, content, metadata, created_at
            )
            VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, now())
            """,
            (
                new_id("msg"),
                session_id,
                sequence,
                role,
                _json({"text": content}),
                _json(metadata_payload),
            ),
        )
        connection.execute(
            """
            UPDATE agent_sessions
            SET updated_at = now(),
                metadata = jsonb_set(
                    metadata,
                    '{message_count}',
                    to_jsonb(COALESCE((metadata->>'message_count')::int, 0) + 1),
                    true
                )
            WHERE session_id = %s
            """,
            (session_id,),
        )
        connection.commit()
        return sequence

    def list_messages(self, session_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
        connection = self.connection_factory()
        sql = "SELECT * FROM agent_messages WHERE session_id = %s ORDER BY message_sequence ASC"
        params: tuple[Any, ...] = (session_id,)
        if limit is not None:
            sql += " LIMIT %s"
            params = (session_id, limit)
        rows = connection.execute(sql, params).fetchall()
        return [_message_from_row(row) for row in rows]

    def search_sessions(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        raise ValueError("owner_key is required")

    def append_user_message_and_start_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        content: str,
        client_message_id: str,
        task_run_id: str,
        base_history_version: int,
        metadata_patch: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        connection = self.connection_factory()
        session_row = connection.execute(
            f"""
            SELECT * FROM agent_sessions
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)}
              AND deleted_at IS NULL
            FOR UPDATE
            """,
            tuple([session_id, *_owner_filter_params(owner_key)]),
        ).fetchone()
        self._ensure_product_session_row(session_row, session_id=session_id)

        duplicate_row = connection.execute(
            """
            SELECT * FROM agent_messages
            WHERE session_id = %s
              AND role = 'user'
              AND metadata->>'client_message_id' = %s
            ORDER BY message_sequence ASC
            LIMIT 1
            """,
            (session_id, client_message_id),
        ).fetchone()
        if duplicate_row is not None:
            metadata = _json_load(duplicate_row.get("metadata"), {})
            current_version = int(session_row.get("history_version") or 0)
            connection.commit()
            return {
                "duplicate": True,
                "session_id": session_id,
                "message_id": duplicate_row.get("message_sequence"),
                "message_uuid": duplicate_row.get("message_id"),
                "task_run_id": metadata.get("task_run_id") or task_run_id,
                "base_history_version": max(0, current_version - 1),
                "after_user_message_version": current_version,
                "completion_expected_version": current_version,
                "running_task_run_id": session_row.get("running_task_run_id"),
            }

        current_version = int(session_row.get("history_version") or 0)
        if current_version != int(base_history_version):
            raise ValueError("history version mismatch")
        if session_row.get("running_task_run_id"):
            raise ValueError("session already has a running task")

        sequence = self._next_message_sequence(connection, session_id)
        message_id = new_id("msg")
        metadata_payload = {
            "source": "api.session",
            "client_message_id": client_message_id,
            "task_run_id": task_run_id,
        }
        if metadata_patch:
            metadata_payload.update(metadata_patch)
        # product session row lock은 Redis projection보다 영속 기준에 가깝다.
        # 프로세스가 죽어도 running_task_run_id가 남아 중복 append를 막고,
        # 다음 명령은 TaskRun 상태를 확인한 뒤 stale guard만 정리한다.
        connection.execute(
            f"""
            INSERT INTO agent_messages (
                message_id, session_id, message_sequence, role, content, metadata, created_at
            )
            VALUES (%s, %s, %s, 'user', %s::jsonb, %s::jsonb, now())
            """,
            (message_id, session_id, sequence, _json({"text": content}), _json(metadata_payload)),
        )
        after_version = current_version + 1
        connection.execute(
            f"""
            UPDATE agent_sessions
            SET history_version = %s,
                running_task_run_id = %s,
                updated_at = now(),
                metadata = jsonb_set(
                    metadata,
                    '{{message_count}}',
                    to_jsonb(COALESCE((metadata->>'message_count')::int, 0) + 1),
                    true
                )
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)} AND deleted_at IS NULL
            """,
            tuple([after_version, task_run_id, session_id, *_owner_filter_params(owner_key)]),
        )
        connection.commit()
        return {
            "duplicate": False,
            "session_id": session_id,
            "message_id": sequence,
            "message_uuid": message_id,
            "task_run_id": task_run_id,
            "base_history_version": current_version,
            "after_user_message_version": after_version,
            "completion_expected_version": after_version,
            "running_task_run_id": task_run_id,
        }

    def append_assistant_message_and_finish_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        task_run_id: str,
        content: str,
        completion_expected_version: int,
        status: str,
    ) -> dict[str, Any]:
        connection = self.connection_factory()
        session_row = connection.execute(
            f"""
            SELECT * FROM agent_sessions
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)}
              AND deleted_at IS NULL
            FOR UPDATE
            """,
            tuple([session_id, *_owner_filter_params(owner_key)]),
        ).fetchone()
        self._ensure_product_session_row(session_row, session_id=session_id)
        if session_row.get("running_task_run_id") != task_run_id:
            raise ValueError("task does not own session running guard")
        current_version = int(session_row.get("history_version") or 0)
        if current_version != int(completion_expected_version):
            raise ValueError("history version mismatch")

        sequence = self._next_message_sequence(connection, session_id)
        message_id = new_id("msg")
        metadata_payload = {"source": "api.session", "task_run_id": task_run_id, "status": status}
        connection.execute(
            f"""
            INSERT INTO agent_messages (
                message_id, session_id, message_sequence, role, content, metadata, created_at
            )
            VALUES (%s, %s, %s, 'assistant', %s::jsonb, %s::jsonb, now())
            """,
            (message_id, session_id, sequence, _json({"text": content}), _json(metadata_payload)),
        )
        result_version = current_version + 1
        connection.execute(
            f"""
            UPDATE agent_sessions
            SET history_version = %s,
                running_task_run_id = NULL,
                updated_at = now(),
                metadata = jsonb_set(
                    metadata,
                    '{{message_count}}',
                    to_jsonb(COALESCE((metadata->>'message_count')::int, 0) + 1),
                    true
                )
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)} AND deleted_at IS NULL
            """,
            tuple([result_version, session_id, *_owner_filter_params(owner_key)]),
        )
        connection.commit()
        return {
            "session_id": session_id,
            "message_id": sequence,
            "message_uuid": message_id,
            "task_run_id": task_run_id,
            "completion_expected_version": completion_expected_version,
            "completion_result_version": result_version,
        }

    def clear_stale_running_task(
        self,
        *,
        owner_key: str,
        session_id: str,
        task_run_id: str,
    ) -> bool:
        connection = self.connection_factory()
        row = connection.execute(
            f"""
            UPDATE agent_sessions
            SET running_task_run_id = NULL,
                updated_at = now()
            WHERE session_id = %s
              AND {_owner_filter_sql(owner_key)}
              AND running_task_run_id = %s
              AND deleted_at IS NULL
            RETURNING session_id
            """,
            tuple([session_id, *_owner_filter_params(owner_key), task_run_id]),
        ).fetchone()
        connection.commit()
        return row is not None

    def search_public_sessions(
        self,
        query: str,
        *,
        owner_key: str,
        workspace_key: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        if not owner_key:
            raise ValueError("owner_key is required")
        return self._search_sessions_by_source(query, source="api.session", owner_key=owner_key, workspace_key=workspace_key, limit=limit)

    def search_transcript_sessions(self, query: str, *, owner_key: str, limit: int = 10) -> list[dict[str, Any]]:
        if not owner_key:
            raise ValueError("owner_key is required")
        return self._search_sessions_by_source(query, source="agent.loop", owner_key=owner_key, workspace_key=None, limit=limit)

    def close(self) -> None:
        """connection_factory가 요청마다 연결을 만들기 때문에 저장소 자체 close는 no-op이다."""

    def update_title(self, *, owner_key: str, session_id: str, title: str) -> dict[str, Any]:
        connection = self.connection_factory()
        row = self._select_idle_product_session(connection, owner_key=owner_key, session_id=session_id)
        if str(row.get("title") or "") == title:
            connection.commit()
            return self.get_session(session_id) or {}
        connection.execute(
            f"""
            UPDATE agent_sessions
            SET title = %s,
                history_version = history_version + 1,
                updated_at = now()
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)} AND deleted_at IS NULL
            """,
            tuple([title, session_id, *_owner_filter_params(owner_key)]),
        )
        connection.commit()
        return self.get_session(session_id) or {}

    def archive_session(self, *, owner_key: str, session_id: str, archived: bool = True) -> dict[str, Any]:
        connection = self.connection_factory()
        row = self._select_idle_product_session(connection, owner_key=owner_key, session_id=session_id)
        already_archived = row.get("archived_at") is not None
        if already_archived == archived:
            connection.commit()
            return self.get_session(session_id) or {}
        connection.execute(
            f"""
            UPDATE agent_sessions
            SET archived_at = CASE WHEN %s THEN COALESCE(archived_at, now()) ELSE NULL END,
                updated_at = now()
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)} AND deleted_at IS NULL
            """,
            tuple([archived, session_id, *_owner_filter_params(owner_key)]),
        )
        connection.commit()
        return self.get_session(session_id) or {}

    def delete_session(self, *, owner_key: str, session_id: str, deleted_by: str | None = None, retention_days: int = 30) -> dict[str, Any]:
        connection = self.connection_factory()
        row = connection.execute(
            f"""
            SELECT * FROM agent_sessions
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)}
            FOR UPDATE
            """,
            tuple([session_id, *_owner_filter_params(owner_key)]),
        ).fetchone()
        if row is None:
            raise KeyError(session_id)
        metadata = _json_load(row.get("metadata"), {})
        source = row.get("session_source") or metadata.get("source") or row.get("session_role")
        if source != "api.session":
            raise ValueError("session is not a public product session")
        if row.get("running_task_run_id"):
            raise ValueError("session has a running task")
        if row.get("deleted_at") is not None:
            connection.commit()
            return self.get_session(session_id) or {}
        deleted_by_user_id = _owner_user_id(deleted_by or owner_key)
        # soft delete는 메시지/trace FK cascade를 건드리지 않는 것이 핵심 불변식이다.
        # purge_after만 별도로 기록해 보존 기간 뒤의 물리 정리 작업이 같은 기준을 재사용하게 한다.
        connection.execute(
            f"""
            UPDATE agent_sessions
            SET deleted_at = COALESCE(deleted_at, now()),
                deleted_by = COALESCE(deleted_by, %s),
                purge_after = COALESCE(purge_after, now() + (%s || ' days')::interval),
                archived_at = COALESCE(archived_at, now()),
                updated_at = now()
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)}
            """,
            tuple([deleted_by_user_id, int(retention_days), session_id, *_owner_filter_params(owner_key)]),
        )
        connection.commit()
        return self.get_session(session_id) or {}

    def update_session_settings(self, *, owner_key: str, session_id: str, settings: dict[str, Any]) -> dict[str, Any]:
        connection = self.connection_factory()
        row = self._select_idle_product_session(connection, owner_key=owner_key, session_id=session_id)
        current_settings = _json_load(row.get("settings"), {})
        next_settings = {**current_settings, **dict(settings)}
        if next_settings == current_settings:
            connection.commit()
            return self.get_session(session_id) or {}
        # settings update는 patch 의미다. 모델만 바꿔도 systemPrompt/toolsets 같은
        # 기존 실행 기준을 잃지 않도록 row lock 상태에서 기존 JSON과 병합한다.
        connection.execute(
            f"""
            UPDATE agent_sessions
            SET settings = %s::jsonb,
                history_version = history_version + 1,
                updated_at = now()
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)} AND deleted_at IS NULL
            """,
            tuple([_json(next_settings), session_id, *_owner_filter_params(owner_key)]),
        )
        connection.commit()
        return self.get_session(session_id) or {}

    def get_session_command_receipt(self, *, owner_key: str, session_id: str, client_command_id: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute(
            f"""
            SELECT command_signature, response_payload
            FROM session_command_receipts
            WHERE session_id = %s
              AND client_command_id = %s
              AND {_owner_filter_sql(owner_key)}
            """,
            tuple([session_id, client_command_id, *_owner_filter_params(owner_key)]),
        ).fetchone()
        if row is None:
            return None
        return {
            "command_signature": row.get("command_signature"),
            "response_payload": _json_load(row.get("response_payload"), {}),
        }

    def remember_session_command_receipt(
        self,
        *,
        owner_key: str,
        session_id: str,
        client_command_id: str,
        command_signature: str,
        response_payload: dict[str, Any],
    ) -> None:
        connection = self.connection_factory()
        owner_user_id = _owner_user_id(owner_key)
        # command receipt는 process memory가 사라져도 같은 clientCommandId 재시도를
        # 같은 응답으로 되돌리기 위한 durable idempotency 기록이다.
        connection.execute(
            """
            INSERT INTO session_command_receipts (
                session_id, client_command_id, owner_key, owner_user_id,
                command_signature, response_payload, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, now())
            ON CONFLICT (session_id, client_command_id) DO NOTHING
            """,
            (session_id, client_command_id, owner_key, owner_user_id, command_signature, _json(response_payload)),
        )
        connection.commit()

    def _next_message_sequence(self, connection: Any, session_id: str) -> int:
        sequence_row = connection.execute(
            "SELECT COALESCE(MAX(message_sequence), 0) + 1 AS next_sequence FROM agent_messages WHERE session_id = %s",
            (session_id,),
        ).fetchone()
        return int((sequence_row or {}).get("next_sequence") or 1)

    def _ensure_product_session_row(self, row: Any, *, session_id: str) -> None:
        if row is None:
            raise KeyError(session_id)
        metadata = _json_load(row.get("metadata"), {})
        source = row.get("session_source") or metadata.get("source") or row.get("session_role")
        if source != "api.session":
            raise ValueError("session is not a public product session")
        if row.get("deleted_at") is not None:
            raise KeyError(session_id)

    def _select_idle_product_session(self, connection: Any, *, owner_key: str, session_id: str) -> Any:
        row = connection.execute(
            f"""
            SELECT * FROM agent_sessions
            WHERE session_id = %s AND {_owner_filter_sql(owner_key)}
              AND deleted_at IS NULL
            FOR UPDATE
            """,
            tuple([session_id, *_owner_filter_params(owner_key)]),
        ).fetchone()
        self._ensure_product_session_row(row, session_id=session_id)
        if row.get("running_task_run_id"):
            raise ValueError("session has a running task")
        return row

    def _search_sessions_by_source(
        self,
        query: str,
        *,
        source: str,
        owner_key: str | None,
        workspace_key: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        where = [
            "COALESCE(s.session_source, s.metadata->>'source') = %s",
            "COALESCE(m.content->>'text', '') ILIKE %s",
            "s.deleted_at IS NULL",
            "s.archived_at IS NULL",
        ]
        params: list[Any] = [source, f"%{query}%"]
        if owner_key is not None:
            owner_sql, owner_params = _owner_filter(owner_key, table_alias="s")
            where.append(owner_sql)
            params.extend(owner_params)
        if workspace_key is not None:
            where.append("s.workspace_key = %s")
            params.append(workspace_key)
        connection = self.connection_factory()
        rows = connection.execute(
            f"""
            SELECT DISTINCT s.*, m.content->>'text' AS preview
            FROM agent_messages m
            JOIN agent_sessions s ON s.session_id = m.session_id
            WHERE {" AND ".join(where)}
            ORDER BY s.updated_at DESC, s.created_at DESC
            LIMIT %s
            """,
            tuple([*params, limit]),
        ).fetchall()
        results = []
        for row in rows:
            record = _session_from_row(row)
            if record is not None:
                record["preview"] = row.get("preview")
                results.append(record)
        return results


def _session_role(source: str, metadata: dict[str, Any]) -> str:
    role = str(metadata.get("session_role") or source or "main")
    if role in {"main", "user_subagent", "worker", "domain"}:
        return role
    return "worker" if "worker" in role else "main"


def _session_from_row(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    metadata = _json_load(row.get("metadata"), {})
    owner_identity = _owner_identity_from_row(row)
    return {
        "id": row["session_id"],
        "session_key": row["session_key"],
        "source": row.get("session_source") or metadata.get("source") or row.get("session_role"),
        "session_source": row.get("session_source") or metadata.get("source") or row.get("session_role"),
        "user_id": owner_identity,
        "owner_user_id": row.get("owner_user_id"),
        "owner_key": row.get("owner_key"),
        "model": metadata.get("model"),
        "system_prompt": metadata.get("system_prompt"),
        "parent_session_id": row.get("parent_session_id"),
        "parent_step_run_id": row.get("parent_step_run_id"),
        "status": row.get("status"),
        "title": row.get("title"),
        "metadata": metadata,
        "settings": _json_load(row.get("settings"), {}),
        "created_at": row.get("created_at"),
        "started_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "ended_at": row.get("ended_at"),
        "end_reason": metadata.get("end_reason"),
        "message_count": int(metadata.get("message_count") or 0),
        "history_version": int(row.get("history_version") or 0),
        "running_task_run_id": row.get("running_task_run_id"),
        "workspace_key": row.get("workspace_key"),
        "archived_at": row.get("archived_at"),
        "deleted_at": row.get("deleted_at"),
        "deleted_by": row.get("deleted_by"),
        "purge_after": row.get("purge_after"),
    }


def _message_from_row(row: Any) -> dict[str, Any]:
    content = _json_load(row.get("content"), {})
    metadata = _json_load(row.get("metadata"), {})
    return {
        "id": row.get("message_sequence"),
        "message_id": row.get("message_id"),
        "message_sequence": row.get("message_sequence"),
        "session_id": row["session_id"],
        "role": row["role"],
        "content": content.get("text"),
        "tool_name": metadata.get("tool_name"),
        "tool_call_id": metadata.get("tool_call_id"),
        "tool_calls": metadata.get("tool_calls") or [],
        "metadata": metadata,
        "timestamp": row.get("created_at"),
        "finish_reason": metadata.get("finish_reason"),
    }


def _json(value: Any) -> str:
    return json.dumps(_sanitize_json_value(value or {}), ensure_ascii=False, sort_keys=True)


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _sanitize_json_value(item) for key, item in value.items()}
    return value


def _json_load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, str):
        return json.loads(value)
    return value


def _owner_user_id(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _owner_filter(owner_key: str, *, table_alias: str | None = None) -> tuple[str, list[Any]]:
    return _owner_filter_sql(owner_key, table_alias=table_alias), _owner_filter_params(owner_key)


def _owner_filter_sql(owner_key: str, *, table_alias: str | None = None) -> str:
    prefix = f"{table_alias}." if table_alias else ""
    owner_user_id = _owner_user_id(owner_key)
    if owner_user_id is None:
        return f"{prefix}owner_key = %s"
    return f"{prefix}owner_user_id = %s"


def _owner_filter_params(owner_key: str) -> list[Any]:
    owner_user_id = _owner_user_id(owner_key)
    if owner_user_id is None:
        return [owner_key]
    return [owner_user_id]


def _owner_identity_from_row(row: Any) -> str | None:
    """권한 비교에 쓰는 owner 문자열은 metadata가 아니라 DB 소유권 컬럼에서만 만든다.

    metadata.user_id는 이전 버전 표시/호환 값이라 사용자가 바꿀 수 있는 JSON 영역에
    남아 있을 수 있다. owner_user_id가 있으면 같은 DB의 users(id)를 기준으로 삼고,
    숫자 FK가 없는 개발/기존 데이터만 owner_key로 되돌아간다.
    """

    owner_user_id = row.get("owner_user_id")
    if owner_user_id is not None:
        return str(owner_user_id)
    owner_key = row.get("owner_key")
    return str(owner_key) if owner_key is not None else None
