from __future__ import annotations

from typing import Any, Protocol


class PrototypeArtifactRepository(Protocol):
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
    ) -> dict[str, Any]: ...

    def get_active_artifact(self, *, session_id: str, owner_key: str) -> dict[str, Any] | None: ...

    def get_version_code(
        self,
        *,
        session_id: str,
        owner_key: str,
        artifact_id: str,
        version_id: str,
    ) -> dict[str, Any] | None: ...
