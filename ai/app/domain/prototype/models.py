from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class PrototypeArtifactVersion:
    artifact_id: str
    version_id: str
    session_id: str
    owner_key: str
    title: str
    framework: str = "react"
    styling: str = "css"
    design_preset_id: str | None = None
    entry_file: str = "/src/App.tsx"
    files: dict[str, dict[str, str]] = field(default_factory=dict)
    version_number: int = 1
    summary: str = ""
    created_at: Any = None
    updated_at: Any = None
