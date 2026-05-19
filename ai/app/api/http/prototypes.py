from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field

from app.api.deps.http_auth import authenticate_http_user, ensure_owner
from app.api.deps.openapi_auth import document_bearer_auth


router = APIRouter(
    prefix="/sessions/{sessionId}/artifacts",
    tags=["prototype-artifacts"],
    dependencies=[Depends(document_bearer_auth)],
)


class PrototypeArtifactResponse(BaseModel):
    artifact_id: str = Field(alias="artifactId")
    version_id: str = Field(alias="versionId")
    session_id: str = Field(alias="sessionId")
    title: str
    framework: str
    styling: str
    design_preset_id: str | None = Field(default=None, alias="designPresetId")
    entry_file: str = Field(alias="entryFile")
    files: dict[str, dict[str, str]]
    version_number: int = Field(alias="versionNumber")
    summary: str = ""
    created_at: Any = Field(default=None, alias="createdAt")
    updated_at: Any = Field(default=None, alias="updatedAt")


class ActivePrototypeArtifactResponse(BaseModel):
    active_artifact_id: str | None = Field(default=None, alias="activeArtifactId")
    active_artifact_version_id: str | None = Field(default=None, alias="activeArtifactVersionId")
    artifact: PrototypeArtifactResponse | None = None


class PrototypeCodeResponse(BaseModel):
    artifact_id: str = Field(alias="artifactId")
    version_id: str = Field(alias="versionId")
    files: dict[str, dict[str, str]]
    entry_file: str = Field(alias="entryFile")


@router.get(
    "/active",
    response_model=ActivePrototypeArtifactResponse,
    summary="세션의 활성 프로토타입 Artifact 조회",
)
async def get_active_prototype_artifact(
    request: Request,
    sessionId: str = Path(..., description="AI 대화 세션 ID입니다."),
) -> ActivePrototypeArtifactResponse:
    user = await authenticate_http_user(request)
    _ensure_session_owner(request, session_id=sessionId, owner_key=user.user_id)
    repository = _prototype_repository(request)
    record = repository.get_active_artifact(session_id=sessionId, owner_key=user.user_id)
    if record is None:
        return ActivePrototypeArtifactResponse()
    artifact = _artifact_response(record)
    return ActivePrototypeArtifactResponse(
        activeArtifactId=artifact.artifact_id,
        activeArtifactVersionId=artifact.version_id,
        artifact=artifact,
    )


@router.get(
    "/{artifactId}/versions/{versionId}/code",
    response_model=PrototypeCodeResponse,
    summary="프로토타입 Artifact Version 코드 조회",
)
async def get_prototype_artifact_code(
    request: Request,
    sessionId: str = Path(..., description="AI 대화 세션 ID입니다."),
    artifactId: str = Path(..., description="Artifact ID입니다."),
    versionId: str = Path(..., description="Artifact Version ID입니다."),
) -> PrototypeCodeResponse:
    user = await authenticate_http_user(request)
    _ensure_session_owner(request, session_id=sessionId, owner_key=user.user_id)
    repository = _prototype_repository(request)
    record = repository.get_version_code(
        session_id=sessionId,
        owner_key=user.user_id,
        artifact_id=artifactId,
        version_id=versionId,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="prototype artifact version not found")
    return PrototypeCodeResponse(
        artifactId=str(record["artifact_id"]),
        versionId=str(record["version_id"]),
        files=_files(record),
        entryFile=str(record.get("entry_file") or "/src/App.tsx"),
    )


def _prototype_repository(request: Request):
    repository = getattr(request.app.state, "prototype_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="prototype artifact storage is not configured")
    return repository


def _ensure_session_owner(request: Request, *, session_id: str, owner_key: str) -> None:
    session = request.app.state.session_store.get_session(session_id)
    if session is None or session.get("source") != "api.session" or session.get("deleted_at") is not None:
        raise HTTPException(status_code=404, detail="session not found")
    ensure_owner(type("User", (), {"user_id": owner_key})(), session.get("user_id"))


def _artifact_response(record: dict[str, Any]) -> PrototypeArtifactResponse:
    return PrototypeArtifactResponse(
        artifactId=str(record["artifact_id"]),
        versionId=str(record["version_id"]),
        sessionId=str(record["session_id"]),
        title=str(record.get("title") or "프로토타입"),
        framework=str(record.get("framework") or "react"),
        styling=str(record.get("styling") or "css"),
        designPresetId=record.get("design_preset_id"),
        entryFile=str(record.get("entry_file") or "/src/App.tsx"),
        files=_files(record),
        versionNumber=int(record.get("version_number") or 1),
        summary=str(record.get("summary") or ""),
        createdAt=record.get("created_at"),
        updatedAt=record.get("updated_at"),
    )


def _files(record: dict[str, Any]) -> dict[str, dict[str, str]]:
    files = record.get("files")
    if not isinstance(files, dict):
        return {}
    normalized: dict[str, dict[str, str]] = {}
    for path, item in files.items():
        if isinstance(item, dict) and isinstance(item.get("code"), str):
            normalized[str(path)] = {"code": str(item["code"])}
        elif isinstance(item, str):
            normalized[str(path)] = {"code": item}
    return normalized
