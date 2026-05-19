from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

SECRET_FILE_NAME_PATTERN = ("secret", "secrets", "token", "password", "passwd", "credential", "credentials", "env")
CUSTOM_SKILL_SOURCE_PREFIX = "custom://"
MAX_CUSTOM_SKILL_BODY_CHARS = 80_000
MAX_CUSTOM_SKILL_DOCUMENT_CHARS = 80_000


class PostgresSkillRepository:
    storage_backend = "postgres"

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self.connection_factory = connection_factory

    def sync_builtin_catalog(self, skills: list[dict[str, Any]]) -> None:
        connection = self.connection_factory()
        for skill in skills:
            name = str(skill.get("name") or "").strip()
            if not name:
                continue
            connection.execute(
                """
                INSERT INTO ai_skill_catalog (
                    skill_id, name, display_name, description, source_type, source_path, default_enabled, metadata
                )
                VALUES (%s, %s, %s, %s, 'builtin', %s, true, %s::jsonb)
                ON CONFLICT (skill_id) DO UPDATE
                SET name = EXCLUDED.name,
                    display_name = EXCLUDED.display_name,
                    description = EXCLUDED.description,
                    source_type = EXCLUDED.source_type,
                    source_path = EXCLUDED.source_path,
                    metadata = EXCLUDED.metadata,
                    updated_at = now()
                """,
                (
                    name,
                    name,
                    _display_name(name),
                    str(skill.get("description") or ""),
                    str(skill.get("path") or "") or None,
                    _json({"hasBody": bool(str(skill.get("body") or "").strip())}),
                ),
            )
        connection.commit()

    def list_user_skills(self, *, owner_key: str, owner_user_id: int | None) -> list[dict[str, Any]]:
        rows = self.connection_factory().execute(
            """
            SELECT
                c.skill_id,
                c.name,
                c.display_name,
                c.description,
                c.source_type,
                c.source_path,
                c.version,
                c.default_enabled,
                c.metadata,
                COALESCE(s.enabled, c.default_enabled) AS enabled,
                s.config_snapshot
            FROM ai_skill_catalog c
            LEFT JOIN ai_user_skill_settings s
              ON s.skill_id = c.skill_id
             AND s.owner_key = %s
            WHERE c.source_type <> 'custom'
               OR c.metadata->>'ownerKey' = %s
            ORDER BY c.name ASC
            """,
            (owner_key, owner_key),
        ).fetchall()
        items = [_skill_from_row(row) for row in rows]
        if items:
            self._ensure_user_settings(
                owner_key=owner_key,
                owner_user_id=owner_user_id,
                items=items,
            )
        return items

    def set_user_skill_enabled(
        self,
        *,
        owner_key: str,
        owner_user_id: int | None,
        skill_id: str,
        enabled: bool,
    ) -> dict[str, Any] | None:
        connection = self.connection_factory()
        row = connection.execute(
            """
            SELECT * FROM ai_skill_catalog
            WHERE skill_id = %s
              AND (
                source_type <> 'custom'
                OR metadata->>'ownerKey' = %s
              )
            """,
            (skill_id, owner_key),
        ).fetchone()
        if row is None:
            return None
        connection.execute(
            """
            INSERT INTO ai_user_skill_settings (
                owner_key, owner_user_id, skill_id, enabled
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (owner_key, skill_id) DO UPDATE
            SET enabled = EXCLUDED.enabled,
                owner_user_id = EXCLUDED.owner_user_id,
                updated_at = now()
            """,
            (owner_key, owner_user_id, skill_id, enabled),
        )
        connection.commit()
        return self.get_user_skill(owner_key=owner_key, skill_id=skill_id)

    def get_user_skill(self, *, owner_key: str, skill_id: str) -> dict[str, Any] | None:
        row = self.connection_factory().execute(
            """
            SELECT
                c.skill_id,
                c.name,
                c.display_name,
                c.description,
                c.source_type,
                c.source_path,
                c.version,
                c.default_enabled,
                c.metadata,
                COALESCE(s.enabled, c.default_enabled) AS enabled,
                s.config_snapshot
            FROM ai_skill_catalog c
            LEFT JOIN ai_user_skill_settings s
              ON s.skill_id = c.skill_id
             AND s.owner_key = %s
            WHERE c.skill_id = %s
              AND (
                c.source_type <> 'custom'
                OR c.metadata->>'ownerKey' = %s
              )
            """,
            (owner_key, skill_id, owner_key),
        ).fetchone()
        return _skill_from_row(row) if row is not None else None

    def get_user_skill_detail(self, *, owner_key: str, skill_id: str) -> dict[str, Any] | None:
        item = self.get_user_skill(owner_key=owner_key, skill_id=skill_id)
        if item is None:
            return None
        if _is_custom_skill_item(item):
            item["body"] = _custom_skill_body(item)
            item["files"] = _custom_skill_files(item)
            item["documents"] = _custom_skill_documents(item)
        else:
            item["body"] = _read_skill_body(item.get("source_path"))
            item["files"] = _list_skill_files(item.get("source_path"))
            item["documents"] = _read_skill_documents(item.get("source_path"))
        return item

    def create_custom_skill(
        self,
        *,
        owner_key: str,
        owner_user_id: int | None,
        name: str,
        display_name: str,
        description: str,
        body: str,
        documents: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        normalized_name = _normalize_skill_name(name)
        normalized_body = _ensure_skill_frontmatter(
            body=body,
            name=normalized_name,
            description=description,
        )
        display_name = display_name.strip() or _display_name(normalized_name)
        description = description.strip() or str(_markdown_frontmatter(normalized_body).get("description") or "")
        documents_payload = _normalize_custom_documents(documents or [])
        metadata = {
            "hasBody": bool(normalized_body.strip()),
            "ownerKey": owner_key,
            "body": normalized_body,
            "documents": documents_payload,
        }
        skill_id = f"custom:{owner_key}:{normalized_name}"
        source_path = f"{CUSTOM_SKILL_SOURCE_PREFIX}{skill_id}/SKILL.md"
        connection = self.connection_factory()
        connection.execute(
            """
            INSERT INTO ai_skill_catalog (
                skill_id, name, display_name, description, source_type, source_path, default_enabled, metadata
            )
            VALUES (%s, %s, %s, %s, 'custom', %s, true, %s::jsonb)
            ON CONFLICT (skill_id) DO UPDATE
            SET name = EXCLUDED.name,
                display_name = EXCLUDED.display_name,
                description = EXCLUDED.description,
                source_path = EXCLUDED.source_path,
                default_enabled = EXCLUDED.default_enabled,
                metadata = EXCLUDED.metadata,
                version = ai_skill_catalog.version + 1,
                updated_at = now()
            """,
            (
                skill_id,
                normalized_name,
                display_name,
                description,
                source_path,
                _json(metadata),
            ),
        )
        connection.execute(
            """
            INSERT INTO ai_user_skill_settings (
                owner_key, owner_user_id, skill_id, enabled
            )
            VALUES (%s, %s, %s, true)
            ON CONFLICT (owner_key, skill_id) DO UPDATE
            SET enabled = true,
                owner_user_id = EXCLUDED.owner_user_id,
                updated_at = now()
            """,
            (owner_key, owner_user_id, skill_id),
        )
        connection.commit()
        item = self.get_user_skill_detail(owner_key=owner_key, skill_id=skill_id)
        if item is None:
            raise KeyError(skill_id)
        return item

    def delete_custom_skill(self, *, owner_key: str, skill_id: str) -> dict[str, Any] | None:
        item = self.get_user_skill(owner_key=owner_key, skill_id=skill_id)
        if item is None or not _is_custom_skill_item(item):
            return None
        connection = self.connection_factory()
        connection.execute(
            """
            DELETE FROM ai_agent_skill_settings
            WHERE skill_id = %s
            """,
            (skill_id,),
        )
        connection.execute(
            """
            DELETE FROM ai_user_skill_settings
            WHERE skill_id = %s
            """,
            (skill_id,),
        )
        connection.execute(
            """
            DELETE FROM ai_skill_catalog
            WHERE skill_id = %s
              AND source_type = 'custom'
              AND metadata->>'ownerKey' = %s
            """,
            (skill_id, owner_key),
        )
        connection.commit()
        return item

    def list_runtime_custom_skills(self) -> list[dict[str, Any]]:
        rows = self.connection_factory().execute(
            """
            SELECT
                skill_id,
                name,
                display_name,
                description,
                source_type,
                source_path,
                version,
                default_enabled,
                metadata
            FROM ai_skill_catalog
            WHERE source_type = 'custom'
            ORDER BY name ASC
            """
        ).fetchall()
        return [_runtime_custom_skill(_skill_from_row(row)) for row in rows]

    def set_agent_skill_settings(self, *, profile_id: str, skill_ids: list[str]) -> None:
        normalized = _unique_texts(skill_ids)
        connection = self.connection_factory()
        connection.execute(
            """
            DELETE FROM ai_agent_skill_settings
            WHERE profile_id = %s
            """,
            (profile_id,),
        )
        for skill_id in normalized:
            connection.execute(
                """
                INSERT INTO ai_agent_skill_settings (profile_id, skill_id, enabled)
                SELECT %s, skill_id, true
                FROM ai_skill_catalog
                WHERE skill_id = %s
                ON CONFLICT (profile_id, skill_id) DO UPDATE
                SET enabled = EXCLUDED.enabled,
                    updated_at = now()
                """,
                (profile_id, skill_id),
            )
        connection.commit()

    def effective_skill_names(
        self,
        *,
        owner_key: str,
        profile_id: str | None = None,
        requested_skill_names: list[str] | None = None,
        explicit_agent_selection: bool = False,
    ) -> list[str]:
        rows = self.connection_factory().execute(
            """
            SELECT c.name
            FROM ai_skill_catalog c
            LEFT JOIN ai_user_skill_settings s
              ON s.skill_id = c.skill_id
             AND s.owner_key = %s
            WHERE COALESCE(s.enabled, c.default_enabled) = true
              AND (
                c.source_type <> 'custom'
                OR c.metadata->>'ownerKey' = %s
              )
            ORDER BY c.name ASC
            """,
            (owner_key, owner_key),
        ).fetchall()
        enabled_names = {str(_row_get(row, "name") or "").strip() for row in rows}
        enabled_names.discard("")
        if not enabled_names:
            return []

        requested = set(_unique_texts(requested_skill_names or []))
        if explicit_agent_selection:
            return sorted(enabled_names.intersection(requested))

        requested_known = enabled_names.intersection(requested)
        if requested_known:
            return sorted(requested_known)

        if profile_id:
            agent_rows = self.connection_factory().execute(
                """
                SELECT c.name
                FROM ai_agent_skill_settings s
                JOIN ai_skill_catalog c ON c.skill_id = s.skill_id
                WHERE s.profile_id = %s
                  AND s.enabled = true
                  AND (
                    c.source_type <> 'custom'
                    OR c.metadata->>'ownerKey' = %s
                  )
                ORDER BY c.name ASC
                """,
                (profile_id, owner_key),
            ).fetchall()
            agent_names = {str(_row_get(row, "name") or "").strip() for row in agent_rows}
            agent_names.discard("")
            if agent_names:
                return sorted(enabled_names.intersection(agent_names))
            return []

        return sorted(enabled_names)

    def _ensure_user_settings(
        self,
        *,
        owner_key: str,
        owner_user_id: int | None,
        items: list[dict[str, Any]],
    ) -> None:
        connection = self.connection_factory()
        for item in items:
            connection.execute(
                """
                INSERT INTO ai_user_skill_settings (
                    owner_key, owner_user_id, skill_id, enabled
                )
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (owner_key, skill_id) DO NOTHING
                """,
                (
                    owner_key,
                    owner_user_id,
                    str(item.get("skill_id") or ""),
                    bool(item.get("enabled", True)),
                ),
            )
        connection.commit()


def _skill_from_row(row: Any) -> dict[str, Any]:
    return {
        "skill_id": str(_row_get(row, "skill_id") or ""),
        "name": str(_row_get(row, "name") or ""),
        "display_name": str(_row_get(row, "display_name") or _row_get(row, "name") or ""),
        "description": str(_row_get(row, "description") or ""),
        "source_type": str(_row_get(row, "source_type") or "builtin"),
        "source_path": _row_get(row, "source_path"),
        "version": int(_row_get(row, "version") or 1),
        "default_enabled": bool(_row_get(row, "default_enabled", True)),
        "enabled": bool(_row_get(row, "enabled", True)),
        "metadata": _json_load(_row_get(row, "metadata"), {}),
        "config_snapshot": _json_load(_row_get(row, "config_snapshot"), {}),
    }


def _display_name(name: str) -> str:
    return name.replace("-", " ").strip().title() or name


def _is_custom_skill_item(item: dict[str, Any]) -> bool:
    return str(item.get("source_type") or "") == "custom"


def _runtime_custom_skill(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "name": str(item.get("name") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "path": str(item.get("source_path") or ""),
        "body": str(metadata.get("body") or ""),
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key not in {"body"}
        },
    }


def _custom_skill_body(item: dict[str, Any]) -> str:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return str(metadata.get("body") or "")


def _custom_skill_files(item: dict[str, Any]) -> list[str]:
    files = ["SKILL.md"] if _custom_skill_body(item).strip() else []
    for document in _custom_skill_documents(item):
        document_key = str(document.get("document_key") or "").strip()
        if document_key and document_key not in files:
            files.append(document_key)
    return files


def _custom_skill_documents(item: dict[str, Any]) -> list[dict[str, str]]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    body = str(metadata.get("body") or "")
    documents: list[dict[str, str]] = []
    if body.strip():
        documents.append(
            {
                "document_key": "SKILL.md",
                "title": "기본 지침",
                "content": _strip_markdown_frontmatter(body),
                "content_format": "markdown",
            }
        )
    raw_documents = metadata.get("documents") if isinstance(metadata.get("documents"), list) else []
    for raw_document in raw_documents:
        if not isinstance(raw_document, dict):
            continue
        document_key = str(raw_document.get("documentKey") or raw_document.get("document_key") or "").strip()
        content = str(raw_document.get("content") or "")
        title = str(raw_document.get("title") or "").strip() or _humanize_skill_document_name(Path(document_key))
        if not document_key or not content:
            continue
        documents.append(
            {
                "document_key": document_key,
                "title": title,
                "content": content,
                "content_format": "markdown",
            }
        )
    return documents


def _normalize_skill_name(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    if not text:
        raise ValueError("skill name is required")
    if len(text) > 64:
        raise ValueError("skill name is too long")
    return text


def _ensure_skill_frontmatter(*, body: str, name: str, description: str) -> str:
    text = str(body or "").strip()
    if not text:
        raise ValueError("skill body is required")
    if len(text) > MAX_CUSTOM_SKILL_BODY_CHARS:
        raise ValueError("skill body is too long")
    metadata = _markdown_frontmatter(text)
    if metadata.get("name") and metadata.get("description"):
        return text
    stripped = _strip_markdown_frontmatter(text)
    safe_description = str(description or metadata.get("description") or "").strip()
    frontmatter = ["---", f"name: {name}", f"description: {safe_description}", "---", ""]
    return "\n".join(frontmatter) + stripped.lstrip("\n")


def _normalize_custom_documents(values: list[dict[str, str]]) -> list[dict[str, str]]:
    documents: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        document_key = str(value.get("documentKey") or value.get("document_key") or "").strip().replace("\\", "/")
        content = str(value.get("content") or "")
        if not document_key or not content:
            continue
        relative_path = Path(document_key)
        if relative_path.is_absolute() or _is_hidden_or_secret_skill_file(relative_path):
            continue
        if document_key == "SKILL.md" or ".." in relative_path.parts:
            continue
        if not document_key.endswith(".md"):
            document_key = f"{document_key}.md"
        if document_key in seen or len(content) > MAX_CUSTOM_SKILL_DOCUMENT_CHARS:
            continue
        seen.add(document_key)
        documents.append(
            {
                "documentKey": document_key,
                "title": str(value.get("title") or "").strip() or _humanize_skill_document_name(relative_path),
                "content": content,
                "contentFormat": "markdown",
            }
        )
        if len(documents) >= 20:
            break
    return documents


def _read_skill_body(source_path: Any) -> str:
    text = str(source_path or "").strip()
    if not text:
        return ""
    path = Path(text)
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _list_skill_files(source_path: Any) -> list[str]:
    text = str(source_path or "").strip()
    if not text:
        return []
    skill_dir = Path(text).parent
    try:
        if not skill_dir.exists() or not skill_dir.is_dir():
            return []
        files: list[str] = []
        for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
            relative_path = path.relative_to(skill_dir)
            if _is_hidden_or_secret_skill_file(relative_path):
                continue
            files.append(relative_path.as_posix())
            if len(files) >= 200:
                break
        return files
    except OSError:
        return []


def _read_skill_documents(source_path: Any) -> list[dict[str, str]]:
    text = str(source_path or "").strip()
    if not text:
        return []
    skill_file = Path(text)
    skill_dir = skill_file.parent
    try:
        if not skill_dir.exists() or not skill_dir.is_dir():
            return []
        documents: list[dict[str, str]] = []
        paths = sorted(
            (item for item in skill_dir.rglob("*.md") if item.is_file()),
            key=lambda path: _skill_document_sort_key(path.relative_to(skill_dir)),
        )
        for path in paths:
            relative_path = path.relative_to(skill_dir)
            if _is_hidden_or_secret_skill_file(relative_path):
                continue
            content = path.read_text(encoding="utf-8")
            documents.append(
                {
                    "document_key": relative_path.as_posix(),
                    "title": _skill_document_title(relative_path, content),
                    "content": _strip_markdown_frontmatter(content),
                    "content_format": "markdown",
                }
            )
            if len(documents) >= 200:
                break
        return documents
    except OSError:
        return []


def _skill_document_title(relative_path: Path, content: str) -> str:
    if relative_path.as_posix() == "SKILL.md":
        return "기본 지침"
    frontmatter = _markdown_frontmatter(content)
    title = str(frontmatter.get("title") or "").strip()
    if title:
        return title
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip() or _humanize_skill_document_name(relative_path)
    return _humanize_skill_document_name(relative_path)


def _skill_document_sort_key(relative_path: Path) -> tuple[int, str]:
    normalized = relative_path.as_posix()
    preferred_order = {
        "SKILL.md": 0,
        "references/notion-api-basics.md": 10,
        "references/block-types.md": 20,
        "references/report-page-patterns.md": 30,
        "references/database-patterns.md": 40,
        "references/notion-style-guide.md": 50,
        "references/managed-document-patterns.md": 60,
        "references/notion-proxy-api.md": 70,
        "references/execution-policy.md": 80,
        "references/excluded-endpoints.md": 90,
    }
    return (preferred_order.get(normalized, 1_000), normalized)


def _humanize_skill_document_name(relative_path: Path) -> str:
    stem = relative_path.stem.replace("-", " ").replace("_", " ").strip()
    return stem.title() if stem else relative_path.name


def _strip_markdown_frontmatter(content: str) -> str:
    if not content.startswith("---"):
        return content
    lines = content.splitlines()
    for index, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            return "\n".join(lines[index + 1 :]).lstrip("\n")
    return content


def _markdown_frontmatter(content: str) -> dict[str, str]:
    if not content.startswith("---"):
        return {}
    lines = content.splitlines()
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip("'\"")
    return metadata


def _is_hidden_or_secret_skill_file(relative_path: Path) -> bool:
    for part in relative_path.parts:
        normalized = part.lower()
        if normalized.startswith("."):
            return True
        if any(token in normalized for token in SECRET_FILE_NAME_PATTERN):
            return True
    return False


def _unique_texts(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: Any, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return default


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    if row is None:
        return default
    if isinstance(row, dict):
        return row.get(key, default)
    if hasattr(row, "keys"):
        return row[key] if key in row.keys() else default
    try:
        return getattr(row, key)
    except AttributeError:
        return default
