from __future__ import annotations

import json
from typing import Any, Callable

from app.core.utils.ids import new_id


class PostgresPrototypeArtifactRepository:
    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self.connection_factory = connection_factory

    def create_artifact_version(
        self,
        *,
        session_id: str,
        owner_key: str,
        title: str,
        framework: str,
        styling: str,
        design_preset_id: str | None,
        entry_file: str,
        files: dict[str, dict[str, str]],
        summary: str,
        task_run_id: str | None = None,
        prompt_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        connection = self.connection_factory()
        session = connection.execute(
            "SELECT session_id FROM agent_sessions WHERE session_id = %s AND owner_key = %s AND deleted_at IS NULL",
            (session_id, owner_key),
        ).fetchone()
        if session is None:
            raise PermissionError("prototype session is not available for this owner")

        artifact = connection.execute(
            """
            SELECT *
            FROM session_prototype_artifacts
            WHERE session_id = %s AND owner_key = %s AND is_active = true
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (session_id, owner_key),
        ).fetchone()

        artifact_id = str(artifact["artifact_id"]) if artifact else new_id("prototype_artifact")
        if artifact is None:
            connection.execute(
                """
                INSERT INTO session_prototype_artifacts (
                    artifact_id, session_id, owner_key, title, framework, styling,
                    design_preset_id, status, is_active, metadata
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'active', true, %s::jsonb)
                """,
                (artifact_id, session_id, owner_key, title, framework, styling, design_preset_id, _json(metadata)),
            )
            version_number = 1
        else:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(version_number), 0) + 1 AS next_version
                FROM session_prototype_artifact_versions
                WHERE artifact_id = %s
                """,
                (artifact_id,),
            ).fetchone()
            version_number = int(row["next_version"] or 1)
            connection.execute(
                """
                UPDATE session_prototype_artifacts
                SET title = %s,
                    framework = %s,
                    styling = %s,
                    design_preset_id = %s,
                    metadata = COALESCE(%s::jsonb, metadata),
                    updated_at = now()
                WHERE artifact_id = %s AND session_id = %s AND owner_key = %s
                """,
                (title, framework, styling, design_preset_id, _json(metadata), artifact_id, session_id, owner_key),
            )

        version_id = new_id("prototype_version")
        connection.execute(
            """
            INSERT INTO session_prototype_artifact_versions (
                version_id, artifact_id, session_id, owner_key, version_number,
                prompt_message_id, task_run_id, files_json, entry_file, summary
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                version_id,
                artifact_id,
                session_id,
                owner_key,
                version_number,
                prompt_message_id,
                task_run_id,
                _json(files),
                entry_file,
                summary,
            ),
        )
        connection.execute(
            """
            UPDATE session_prototype_artifacts
            SET active_version_id = %s, updated_at = now()
            WHERE artifact_id = %s AND session_id = %s AND owner_key = %s
            """,
            (version_id, artifact_id, session_id, owner_key),
        )
        connection.commit()
        return self.get_version_code(
            session_id=session_id,
            owner_key=owner_key,
            artifact_id=artifact_id,
            version_id=version_id,
        )

    def get_active_artifact(self, *, session_id: str, owner_key: str) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute(
            """
            SELECT
                a.artifact_id,
                v.version_id,
                a.session_id,
                a.owner_key,
                a.title,
                a.framework,
                a.styling,
                a.design_preset_id,
                v.entry_file,
                v.files_json AS files,
                v.version_number,
                v.summary,
                a.created_at,
                a.updated_at
            FROM session_prototype_artifacts a
            JOIN session_prototype_artifact_versions v
              ON v.version_id = a.active_version_id
            WHERE a.session_id = %s
              AND a.owner_key = %s
              AND a.is_active = true
            ORDER BY a.updated_at DESC
            LIMIT 1
            """,
            (session_id, owner_key),
        ).fetchone()
        return _record(row)

    def get_version_code(
        self,
        *,
        session_id: str,
        owner_key: str,
        artifact_id: str,
        version_id: str,
    ) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute(
            """
            SELECT
                a.artifact_id,
                v.version_id,
                a.session_id,
                a.owner_key,
                a.title,
                a.framework,
                a.styling,
                a.design_preset_id,
                v.entry_file,
                v.files_json AS files,
                v.version_number,
                v.summary,
                v.created_at,
                v.created_at AS updated_at
            FROM session_prototype_artifacts a
            JOIN session_prototype_artifact_versions v
              ON v.artifact_id = a.artifact_id
            WHERE a.session_id = %s
              AND a.owner_key = %s
              AND a.artifact_id = %s
              AND v.version_id = %s
            LIMIT 1
            """,
            (session_id, owner_key, artifact_id, version_id),
        ).fetchone()
        return _record(row)


def _record(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    files = record.get("files")
    if isinstance(files, str):
        record["files"] = json.loads(files)
    elif files is None:
        record["files"] = {}
    return record


def _json(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)
