from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response

from app.api.deps.http_auth import authenticate_http_user, ensure_owner
from app.api.deps.openapi_auth import document_bearer_auth
from app.contracts.agents import (
    AgentInstructionBundleResponse,
    AgentInstructionDocumentResponse,
    AgentProfileListResponse,
    AgentProfileResponse,
    AgentTemplateListResponse,
    AgentTemplateResponse,
    CreateCustomSkillRequest,
    CustomSkillDraftResponse,
    GenerateCustomSkillDraftRequest,
    ImportCustomSkillUrlRequest,
    CreateSessionAgentRequest,
    CreateSessionAgentFromTemplateRequest,
    SaveInstructionDocumentRequest,
    SkillCatalogDetailResponse,
    SkillCatalogItemResponse,
    SkillCatalogListResponse,
    UpdateUserSkillSettingRequest,
    UpdateSessionAgentRequest,
)
from app.domain.agents.secret_store import AgentSecretStoreNotConfigured
from app.domain.providers.model.base import AgentMessage

router = APIRouter(tags=["agents"], dependencies=[Depends(document_bearer_auth)])

REMOVED_INSTRUCTION_DOCUMENT_KEYS = {"HEARTBEAT.md"}
MAX_SKILL_IMPORT_BYTES = 200_000


@router.get("/agent-templates", response_model=AgentTemplateListResponse, summary="에이전트 예시 목록 조회")
async def list_agent_templates(request: Request) -> AgentTemplateListResponse:
    await authenticate_http_user(request)
    items = [_template_response(item) for item in request.app.state.agent_repository.list_templates()]
    return AgentTemplateListResponse(items=items)


@router.get("/skills", response_model=SkillCatalogListResponse, summary="사용자 스킬 목록 조회")
async def list_user_skills(request: Request) -> SkillCatalogListResponse:
    user = await authenticate_http_user(request)
    repository = _skill_repository_or_404(request)
    items = repository.list_user_skills(
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
    )
    return SkillCatalogListResponse(items=[_skill_response(item) for item in items])


@router.post("/skills", response_model=SkillCatalogDetailResponse, summary="사용자 스킬 추가")
async def create_custom_skill(
    request: Request,
    payload: CreateCustomSkillRequest,
) -> SkillCatalogDetailResponse:
    user = await authenticate_http_user(request)
    repository = _skill_repository_or_404(request)
    try:
        item = repository.create_custom_skill(
            owner_key=str(user.user_id),
            owner_user_id=_int_or_none(user.user_id),
            name=payload.name,
            display_name=payload.display_name or payload.name,
            description=payload.description,
            body=payload.body,
            documents=[
                {
                    "documentKey": document.document_key,
                    "title": document.title or "",
                    "content": document.content,
                }
                for document in payload.documents
            ],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception as error:
        if "unique" in str(error).lower():
            raise HTTPException(status_code=409, detail="skill name already exists") from error
        raise
    registry = getattr(request.app.state, "skill_registry", None)
    if registry is not None:
        registry.register_many([_runtime_skill_from_detail(item)])
    return _skill_detail_response(item)


@router.post("/skills/draft", response_model=CustomSkillDraftResponse, summary="사용자 스킬 초안 생성")
async def generate_custom_skill_draft(
    request: Request,
    payload: GenerateCustomSkillDraftRequest,
) -> CustomSkillDraftResponse:
    user = await authenticate_http_user(request)
    goal = payload.goal.strip()
    if not goal:
        raise HTTPException(status_code=400, detail="skill goal is required")
    draft = await _generate_skill_draft(
        request,
        user_prompt=goal,
        source_text="",
        source_url=None,
        user_id=str(user.user_id),
    )
    return _skill_draft_response(draft)


@router.post("/skills/import-url", response_model=CustomSkillDraftResponse, summary="URL에서 사용자 스킬 가져오기")
async def import_custom_skill_from_url(
    request: Request,
    payload: ImportCustomSkillUrlRequest,
) -> CustomSkillDraftResponse:
    user = await authenticate_http_user(request)
    url = payload.url.strip()
    if not _is_allowed_skill_import_url(url):
        raise HTTPException(status_code=400, detail="http or https url is required")
    fetched_url, content = await _fetch_skill_import_url(url)
    if not content.strip():
        raise HTTPException(status_code=400, detail="url content is empty")
    if _looks_like_skill_markdown(content):
        draft = _draft_from_skill_markdown(content, source_url=fetched_url)
    else:
        draft = await _generate_skill_draft(
            request,
            user_prompt="이 URL의 내용을 바탕으로 재사용 가능한 에이전트 스킬을 만들어줘.",
            source_text=content,
            source_url=fetched_url,
            user_id=str(user.user_id),
        )
    return _skill_draft_response(draft)


@router.get("/skills/{skillId}", response_model=SkillCatalogDetailResponse, summary="사용자 스킬 상세 조회")
async def get_user_skill_detail(
    request: Request,
    skillId: str = Path(..., description="조회할 스킬 ID입니다."),
) -> SkillCatalogDetailResponse:
    user = await authenticate_http_user(request)
    repository = _skill_repository_or_404(request)
    item = repository.get_user_skill_detail(
        owner_key=str(user.user_id),
        skill_id=skillId,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return _skill_detail_response(item)


@router.patch("/skills/{skillId}", response_model=SkillCatalogItemResponse, summary="사용자 스킬 사용 여부 수정")
async def update_user_skill_setting(
    request: Request,
    payload: UpdateUserSkillSettingRequest,
    skillId: str = Path(..., description="사용 여부를 수정할 스킬 ID입니다."),
) -> SkillCatalogItemResponse:
    user = await authenticate_http_user(request)
    repository = _skill_repository_or_404(request)
    item = repository.set_user_skill_enabled(
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
        skill_id=skillId,
        enabled=payload.enabled,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="skill not found")
    return _skill_response(item)


@router.delete("/skills/{skillId}", summary="사용자 생성 스킬 삭제")
async def delete_custom_skill(
    request: Request,
    skillId: str = Path(..., description="삭제할 사용자 생성 스킬 ID입니다."),
) -> Response:
    user = await authenticate_http_user(request)
    repository = _skill_repository_or_404(request)
    deleted = repository.delete_custom_skill(
        owner_key=str(user.user_id),
        skill_id=skillId,
    )
    if deleted is None:
        raise HTTPException(status_code=404, detail="custom skill not found")
    registry = getattr(request.app.state, "skill_registry", None)
    unregister = getattr(registry, "unregister_names", None)
    if callable(unregister):
        unregister([str(deleted.get("name") or "")])
    return Response(status_code=204)


@router.get(
    "/sessions/{sessionId}/agents",
    response_model=AgentProfileListResponse,
    summary="세션 에이전트 목록 조회",
)
async def list_session_agents(
    request: Request,
    sessionId: str = Path(..., description="세션 에이전트를 조회할 AI 세션 ID입니다."),
) -> AgentProfileListResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    items = request.app.state.agent_repository.list_session_agents(
        session_id=sessionId,
        owner_key=str(user.user_id),
    )
    items = _sanitize_profile_skill_configs(request, items=items, user=user)
    return AgentProfileListResponse(items=[_profile_response(item) for item in items])


@router.get(
    "/sessions/{sessionId}/agents/main",
    response_model=AgentProfileResponse,
    summary="세션 팀장 에이전트 조회",
)
async def get_session_main_agent(
    request: Request,
    sessionId: str = Path(..., description="팀장 에이전트를 조회할 AI 세션 ID입니다."),
) -> AgentProfileResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    item = request.app.state.agent_repository.ensure_session_main_agent(
        session_id=sessionId,
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
    )
    item = _sanitize_profile_skill_config(request, item=item, user=user)
    return _profile_response(item)


@router.post(
    "/sessions/{sessionId}/agents",
    response_model=AgentProfileResponse,
    summary="세션 에이전트 직접 생성",
)
async def create_session_agent(
    request: Request,
    payload: CreateSessionAgentRequest,
    sessionId: str = Path(..., description="에이전트를 생성할 AI 세션 ID입니다."),
) -> AgentProfileResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    if not payload.name.strip():
        raise HTTPException(status_code=400, detail="agent name is required")
    item = request.app.state.agent_repository.create_session_agent(
        session_id=sessionId,
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
        config_snapshot=_custom_agent_config_snapshot(payload),
    )
    item = _sanitize_profile_skill_config(request, item=item, user=user)
    _sync_agent_skill_settings(request, item)
    return _profile_response(item)


@router.patch(
    "/sessions/{sessionId}/agents/{profileId}",
    response_model=AgentProfileResponse,
    summary="세션 에이전트 설정 수정",
)
async def update_session_agent(
    request: Request,
    payload: UpdateSessionAgentRequest,
    sessionId: str = Path(..., description="에이전트를 수정할 AI 세션 ID입니다."),
    profileId: str = Path(..., description="수정할 세션 에이전트 프로필 ID입니다."),
) -> AgentProfileResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    existing = request.app.state.agent_repository.get_session_agent(
        profile_id=profileId,
        owner_key=str(user.user_id),
    )
    if existing is None or str(existing.get("session_id") or "") != sessionId:
        raise HTTPException(status_code=404, detail="agent profile not found")
    config_snapshot = _updated_agent_config_snapshot(existing.get("config_snapshot") or {}, payload)
    item = request.app.state.agent_repository.update_session_agent(
        session_id=sessionId,
        owner_key=str(user.user_id),
        profile_id=profileId,
        config_snapshot=config_snapshot,
    )
    if item is None:
        raise HTTPException(status_code=404, detail="agent profile not found")
    item = _sanitize_profile_skill_config(request, item=item, user=user)
    _sync_agent_skill_settings(request, item)
    return _profile_response(item)


@router.post(
    "/sessions/{sessionId}/agents/from-template",
    response_model=AgentProfileResponse,
    summary="예시에서 세션 에이전트 생성",
)
async def create_session_agent_from_template(
    request: Request,
    payload: CreateSessionAgentFromTemplateRequest,
    sessionId: str = Path(..., description="에이전트를 생성할 AI 세션 ID입니다."),
) -> AgentProfileResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    try:
        item = request.app.state.agent_repository.create_session_agent_from_template(
            session_id=sessionId,
            owner_key=str(user.user_id),
            owner_user_id=_int_or_none(user.user_id),
            template_key=payload.template_key,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="agent template not found") from error
    item = _sanitize_profile_skill_config(request, item=item, user=user)
    return _profile_response(item)


@router.post(
    "/sessions/{sessionId}/agents/defaults",
    response_model=AgentProfileListResponse,
    summary="기본 제공 세션 에이전트 생성",
)
async def create_default_session_agents(
    request: Request,
    sessionId: str = Path(..., description="기본 제공 에이전트를 생성할 AI 세션 ID입니다."),
) -> AgentProfileListResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    items = request.app.state.agent_repository.create_default_session_agents(
        session_id=sessionId,
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
    )
    items = _sanitize_profile_skill_configs(request, items=items, user=user)
    return AgentProfileListResponse(items=[_profile_response(item) for item in items])


@router.delete(
    "/sessions/{sessionId}/agents/{profileId}",
    status_code=204,
    summary="세션 에이전트 삭제",
)
async def delete_session_agent(
    request: Request,
    sessionId: str = Path(..., description="에이전트를 삭제할 AI 세션 ID입니다."),
    profileId: str = Path(..., description="삭제할 세션 에이전트 프로필 ID입니다."),
) -> Response:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    deleted = request.app.state.agent_repository.delete_session_agent(
        session_id=sessionId,
        owner_key=str(user.user_id),
        profile_id=profileId,
    )
    if not deleted:
        raise HTTPException(status_code=404, detail="agent profile not found")
    return Response(status_code=204)


@router.get(
    "/agent-profiles/{profileId}/instructions",
    response_model=AgentInstructionBundleResponse,
    summary="에이전트 지침 묶음 조회",
)
async def get_agent_instruction_bundle(
    request: Request,
    profileId: str = Path(..., description="에이전트 프로필 ID입니다."),
) -> AgentInstructionBundleResponse:
    user = await authenticate_http_user(request)
    bundle = request.app.state.agent_repository.get_instruction_bundle(
        profile_id=profileId,
        owner_key=str(user.user_id),
    )
    if bundle is None:
        raise HTTPException(status_code=404, detail="instruction bundle not found")
    return _bundle_response(bundle)


@router.post(
    "/agent-profiles/{profileId}/instructions/documents",
    response_model=AgentInstructionDocumentResponse,
    summary="에이전트 지침 문서 저장",
)
async def save_agent_instruction_document(
    request: Request,
    payload: SaveInstructionDocumentRequest,
    profileId: str = Path(..., description="에이전트 프로필 ID입니다."),
) -> AgentInstructionDocumentResponse:
    user = await authenticate_http_user(request)
    try:
        document = request.app.state.agent_repository.save_instruction_document(
            profile_id=profileId,
            owner_key=str(user.user_id),
            document_key=payload.document_key,
            display_name=payload.display_name,
            content=payload.content,
        )
    except KeyError as error:
        raise HTTPException(status_code=404, detail="instruction bundle not found") from error
    except AgentSecretStoreNotConfigured as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return _document_response(document)


def _session_or_404(request: Request, session_id: str) -> dict[str, Any]:
    session = request.app.state.session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="session not found")
    return session


def _skill_repository_or_404(request: Request) -> Any:
    repository = getattr(request.app.state, "skill_repository", None)
    if repository is None:
        raise HTTPException(status_code=503, detail="skill repository is not configured")
    return repository


def _sanitize_profile_skill_configs(
    request: Request,
    *,
    items: list[dict[str, Any]],
    user: Any,
) -> list[dict[str, Any]]:
    known_skill_ids = _known_skill_ids(request, user=user)
    if known_skill_ids is None:
        return items
    return [
        _sanitize_profile_skill_config(
            request,
            item=item,
            user=user,
            known_skill_ids=known_skill_ids,
        )
        for item in items
    ]


def _sanitize_profile_skill_config(
    request: Request,
    *,
    item: dict[str, Any],
    user: Any,
    known_skill_ids: set[str] | None = None,
) -> dict[str, Any]:
    known_ids = known_skill_ids if known_skill_ids is not None else _known_skill_ids(request, user=user)
    if known_ids is None:
        return item
    config = item.get("config_snapshot") if isinstance(item.get("config_snapshot"), dict) else {}
    skills = [str(skill).strip() for skill in list(config.get("skills") or []) if str(skill).strip()]
    filtered_skills = [skill for skill in skills if skill in known_ids]
    if filtered_skills == skills:
        return item
    session_id = str(item.get("session_id") or "")
    profile_id = str(item.get("profile_id") or "")
    next_config = dict(config)
    next_config["skills"] = filtered_skills
    if not session_id or not profile_id:
        return {**item, "config_snapshot": next_config}
    updated = request.app.state.agent_repository.update_session_agent(
        session_id=session_id,
        owner_key=str(user.user_id),
        profile_id=profile_id,
        config_snapshot=next_config,
    )
    return updated or {**item, "config_snapshot": next_config}


def _known_skill_ids(request: Request, *, user: Any) -> set[str] | None:
    repository = getattr(request.app.state, "skill_repository", None)
    if repository is None:
        return None
    items = repository.list_user_skills(
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
    )
    return {
        skill_id
        for item in items
        if (skill_id := str(item.get("skill_id") or item.get("name") or "").strip())
    }


def _sync_agent_skill_settings(request: Request, item: dict[str, Any]) -> None:
    repository = getattr(request.app.state, "skill_repository", None)
    if repository is None:
        return
    profile_id = str(item.get("profile_id") or "").strip()
    config = item.get("config_snapshot") if isinstance(item.get("config_snapshot"), dict) else {}
    if not profile_id or config.get("skillSelectionMode") != "explicit":
        return
    repository.set_agent_skill_settings(
        profile_id=profile_id,
        skill_ids=[str(skill) for skill in list(config.get("skills") or [])],
    )


def _template_response(item: dict[str, Any]) -> AgentTemplateResponse:
    config = dict(item.get("default_config_snapshot") or {})
    documents = [
        _document_response(
            {
                "document_id": None,
                "document_key": document.get("documentKey"),
                "display_name": document.get("displayName"),
                "content_format": "markdown",
                "content": document.get("content") or "",
                "version": 1,
            }
        )
        for document in list(config.get("documents") or [])
        if isinstance(document, dict) and _is_active_instruction_document(document.get("documentKey"))
    ]
    return AgentTemplateResponse(
        templateId=str(item.get("template_id") or ""),
        templateKey=str(item.get("template_key") or ""),
        templateVersion=int(item.get("template_version") or 1),
        displayName=str(config.get("displayName") or item.get("template_key") or ""),
        name=str(config.get("name") or ""),
        role=str(config.get("role") or ""),
        title=str(config.get("title") or ""),
        description=str(config.get("description") or ""),
        adapterType=str(config.get("adapterType") or ""),
        model=str(config.get("model") or "") or None,
        profileImage=_normalize_agent_profile_image(str(config.get("profileImage") or "") or None),
        visualKey=_agent_visual_key(config),
        skills=[str(skill) for skill in list(config.get("skills") or [])],
        entryDocumentKey=str(config.get("entryDocumentKey") or "AGENTS.md"),
        documents=documents,
    )


def _custom_agent_config_snapshot(payload: CreateSessionAgentRequest) -> dict[str, Any]:
    entry_document_key = payload.entry_document_key or "AGENTS.md"
    if not _is_active_instruction_document(entry_document_key):
        entry_document_key = "AGENTS.md"
    instructions_files = dict(payload.instructions_files or {})
    instructions_files = {
        key: content
        for key, content in instructions_files.items()
        if _is_active_instruction_document(key)
    }
    if entry_document_key not in instructions_files:
        instructions_files[entry_document_key] = ""
    adapter_type = (payload.adapter_type or "").strip()
    return {
        "name": payload.name.strip(),
        "role": payload.role.strip() or "general",
        "title": (payload.title or "").strip(),
        "description": (payload.description or "").strip(),
        "adapterType": adapter_type,
        "providerName": adapter_type,
        "model": (payload.model or "").strip(),
        "profileImage": (payload.profile_image or "").strip(),
        "skills": [str(skill).strip() for skill in payload.skills if str(skill).strip()],
        "skillSelectionMode": "explicit",
        "entryDocumentKey": entry_document_key,
        "documents": [
            {
                "documentKey": key,
                "displayName": _instruction_display_name(key),
                "content": content,
            }
            for key, content in instructions_files.items()
        ],
    }


def _updated_agent_config_snapshot(
    current: dict[str, Any],
    payload: UpdateSessionAgentRequest,
) -> dict[str, Any]:
    next_config = dict(current or {})
    if payload.name is not None:
        next_config["name"] = payload.name.strip()
    if payload.role is not None:
        next_config["role"] = payload.role.strip() or "general"
    if payload.title is not None:
        next_config["title"] = payload.title.strip()
    if payload.description is not None:
        next_config["description"] = payload.description.strip()
    if payload.adapter_type is not None:
        adapter_type = payload.adapter_type.strip()
        next_config["adapterType"] = adapter_type
        next_config["providerName"] = adapter_type
    if payload.model is not None:
        next_config["model"] = payload.model.strip()
    if payload.profile_image is not None:
        next_config["profileImage"] = payload.profile_image.strip()
    if payload.skills is not None:
        next_config["skills"] = [str(skill).strip() for skill in payload.skills if str(skill).strip()]
        next_config["skillSelectionMode"] = "explicit"

    entry_document_key = payload.entry_document_key
    if entry_document_key is not None:
        entry_document_key = entry_document_key.strip() or "AGENTS.md"
        if not _is_active_instruction_document(entry_document_key):
            entry_document_key = "AGENTS.md"
        next_config["entryDocumentKey"] = entry_document_key

    if payload.instructions_files is not None:
        instructions_files = {
            key: content
            for key, content in dict(payload.instructions_files).items()
            if _is_active_instruction_document(key)
        }
        active_entry = str(next_config.get("entryDocumentKey") or "AGENTS.md")
        if active_entry not in instructions_files:
            instructions_files[active_entry] = ""
        next_config["documents"] = [
            {
                "documentKey": key,
                "displayName": _instruction_display_name(key),
                "content": content,
            }
            for key, content in instructions_files.items()
        ]
    return next_config


def _profile_response(item: dict[str, Any]) -> AgentProfileResponse:
    config = dict(item.get("config_snapshot") or {})
    return AgentProfileResponse(
        profileId=str(item.get("profile_id") or ""),
        sessionId=item.get("session_id"),
        profileKey=str(item.get("profile_key") or ""),
        profileVersion=int(item.get("profile_version") or 1),
        agentType=str(item.get("agent_type") or ""),
        templateKey=item.get("template_key"),
        name=str(config.get("name") or item.get("profile_key") or ""),
        role=str(config.get("role") or item.get("agent_type") or ""),
        title=str(config.get("title") or "") or None,
        description=str(config.get("description") or "") or None,
        adapterType=str(config.get("adapterType") or item.get("provider_name") or "") or None,
        model=str(config.get("model") or item.get("model_name") or "") or None,
        profileImage=_normalize_agent_profile_image(str(config.get("profileImage") or "") or None),
        visualKey=_agent_visual_key(config),
        skills=[str(skill) for skill in list(config.get("skills") or [])],
        instructionBundleId=item.get("bundle_id"),
        entryDocumentKey=item.get("entry_document_key"),
        configSnapshot=config,
    )


def _skill_response(item: dict[str, Any]) -> SkillCatalogItemResponse:
    return SkillCatalogItemResponse(
        skillId=str(item.get("skill_id") or item.get("name") or ""),
        name=str(item.get("name") or item.get("skill_id") or ""),
        displayName=str(item.get("display_name") or item.get("name") or ""),
        description=str(item.get("description") or ""),
        sourceType=str(item.get("source_type") or "builtin"),
        sourcePath=item.get("source_path"),
        version=int(item.get("version") or 1),
        enabled=bool(item.get("enabled", True)),
        defaultEnabled=bool(item.get("default_enabled", True)),
    )


def _skill_detail_response(item: dict[str, Any]) -> SkillCatalogDetailResponse:
    base = _skill_response(item).model_dump(by_alias=True)
    return SkillCatalogDetailResponse(
        **base,
        body=str(item.get("body") or ""),
        files=[str(file) for file in list(item.get("files") or [])],
        documents=[
            {
                "documentKey": str(document.get("document_key") or document.get("documentKey") or ""),
                "title": str(document.get("title") or ""),
                "content": str(document.get("content") or ""),
                "contentFormat": str(document.get("content_format") or document.get("contentFormat") or "markdown"),
            }
            for document in list(item.get("documents") or [])
        ],
    )


def _runtime_skill_from_detail(item: dict[str, Any]) -> dict[str, Any]:
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    return {
        "name": str(item.get("name") or "").strip(),
        "description": str(item.get("description") or "").strip(),
        "path": str(item.get("source_path") or ""),
        "body": str(item.get("body") or metadata.get("body") or ""),
        "metadata": {
            key: value
            for key, value in metadata.items()
            if key != "body"
        },
    }


def _skill_draft_response(item: dict[str, Any]) -> CustomSkillDraftResponse:
    return CustomSkillDraftResponse(
        name=str(item.get("name") or ""),
        displayName=str(item.get("display_name") or item.get("displayName") or item.get("name") or ""),
        description=str(item.get("description") or ""),
        body=str(item.get("body") or ""),
        sourceUrl=str(item.get("source_url") or item.get("sourceUrl") or "") or None,
        documents=[
            {
                "documentKey": str(document.get("document_key") or document.get("documentKey") or ""),
                "title": str(document.get("title") or ""),
                "content": str(document.get("content") or ""),
                "contentFormat": str(document.get("content_format") or document.get("contentFormat") or "markdown"),
            }
            for document in list(item.get("documents") or [])
            if isinstance(document, dict)
        ],
    )


async def _generate_skill_draft(
    request: Request,
    *,
    user_prompt: str,
    source_text: str,
    source_url: str | None,
    user_id: str,
) -> dict[str, Any]:
    registry = getattr(request.app.state, "provider_registry", None)
    if registry is None:
        raise HTTPException(status_code=503, detail="model provider is not configured")
    try:
        provider = registry.preferred_model_provider()
    except Exception as error:
        raise HTTPException(status_code=503, detail="model provider is not available") from error
    model = str(getattr(request.app.state.settings, "openai_response_model", "") or "gpt-5.4")
    messages = [
        AgentMessage(
            role="system",
            content=(
                "사용자의 설명을 에이전트 skill 초안으로 만든다. JSON 객체만 반환한다. "
                "필드: name, displayName, description, body, documents. "
                "name은 영문 소문자, 숫자, 하이픈만 쓰는 짧은 key다. "
                "displayName과 description은 쉬운 한국어로 쓴다. "
                "body는 SKILL.md 전체 markdown이며 YAML frontmatter에 name과 description을 포함한다. "
                "body 본문은 에이전트가 언제 이 스킬을 써야 하는지, 어떤 순서로 작업할지, 확인 기준을 담는다. "
                "documents는 꼭 필요한 보조 문서만 배열로 둔다. 각 항목은 documentKey, title, content를 가진다. "
                "비밀값, 토큰, 인증 정보, 민감한 로컬 경로는 절대 포함하지 않는다."
            ),
        ),
        AgentMessage(
            role="user",
            content=_skill_draft_user_prompt(user_prompt=user_prompt, source_text=source_text, source_url=source_url),
        ),
    ]
    try:
        response = await asyncio.wait_for(
            provider.respond_async(
                messages=messages,
                tools=[],
                model=model,
                runtime_context={
                    "user_id": user_id,
                    "provider_name": "openai_api_key",
                },
            ),
            timeout=_skill_draft_timeout_seconds(request),
        )
    except TimeoutError as error:
        raise HTTPException(status_code=504, detail="skill draft generation timed out") from error
    except Exception as error:
        raise HTTPException(status_code=503, detail="skill draft generation failed") from error
    return _sanitize_skill_draft(response.output_text, source_url=source_url)


def _skill_draft_timeout_seconds(request: Request) -> float:
    configured = getattr(request.app.state.settings, "agent_model_request_timeout_seconds", 120.0)
    try:
        value = float(configured)
    except (TypeError, ValueError):
        return 120.0
    return max(30.0, min(value, 120.0))


def _skill_draft_user_prompt(*, user_prompt: str, source_text: str, source_url: str | None) -> str:
    parts = [f"요청:\n{user_prompt[:4000]}"]
    if source_url:
        parts.append(f"URL:\n{source_url}")
    if source_text:
        parts.append(f"참고 내용:\n{source_text[:12000]}")
    return "\n\n".join(parts)


def _sanitize_skill_draft(value: str, *, source_url: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(_extract_json_object(value))
    except Exception as error:
        raise HTTPException(status_code=502, detail="skill draft response was not valid json") from error
    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="skill draft response was not an object")
    name = _normalize_skill_key(str(parsed.get("name") or parsed.get("displayName") or "custom-skill"))
    display_name = str(parsed.get("displayName") or parsed.get("display_name") or name).strip() or name
    description = str(parsed.get("description") or "").strip()
    body = str(parsed.get("body") or "").strip()
    if not body:
        body = _default_skill_body(name=name, description=description, title=display_name)
    body = _ensure_skill_body_frontmatter(body=body, name=name, description=description)
    documents = _sanitize_draft_documents(parsed.get("documents"))
    return {
        "name": name,
        "display_name": display_name,
        "description": description,
        "body": body,
        "documents": documents,
        "source_url": source_url,
    }


def _draft_from_skill_markdown(content: str, *, source_url: str) -> dict[str, Any]:
    metadata = _markdown_frontmatter(content)
    name = _normalize_skill_key(str(metadata.get("name") or "imported-skill"))
    description = str(metadata.get("description") or "").strip()
    return {
        "name": name,
        "display_name": _display_name(name),
        "description": description,
        "body": _ensure_skill_body_frontmatter(body=content.strip(), name=name, description=description),
        "documents": [],
        "source_url": source_url,
    }


async def _fetch_skill_import_url(url: str) -> tuple[str, str]:
    errors: list[str] = []
    async with httpx.AsyncClient(follow_redirects=True, timeout=10) as client:
        for candidate in _skill_import_url_candidates(url):
            try:
                response = await client.get(candidate, headers={"User-Agent": "HeyGentAI/1.0"})
                response.raise_for_status()
                raw = response.content[:MAX_SKILL_IMPORT_BYTES]
                if not raw.strip():
                    continue
                return str(response.url), raw.decode(response.encoding or "utf-8", errors="replace")
            except httpx.HTTPError as error:
                errors.append(str(error))
    raise HTTPException(status_code=400, detail="url content could not be loaded")


def _skill_import_url_candidates(url: str) -> list[str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    candidates = [url]
    if host == "github.com":
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 5 and parts[2] == "blob":
            owner, repo, _, branch = parts[:4]
            path = "/".join(parts[4:])
            candidates.insert(0, f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}")
        elif len(parts) >= 5 and parts[2] == "tree":
            owner, repo, _, branch = parts[:4]
            path = "/".join(parts[4:])
            candidates.insert(0, f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}/SKILL.md")
        elif len(parts) >= 2:
            owner, repo = parts[:2]
            candidates.insert(0, f"https://raw.githubusercontent.com/{owner}/{repo}/main/SKILL.md")
            candidates.insert(1, f"https://raw.githubusercontent.com/{owner}/{repo}/master/SKILL.md")
    return list(dict.fromkeys(candidates))


def _is_allowed_skill_import_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return False
    host = parsed.hostname or ""
    return host not in {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _looks_like_skill_markdown(content: str) -> bool:
    frontmatter = _markdown_frontmatter(content)
    return (
        bool(frontmatter.get("name") or frontmatter.get("description"))
        and ("use" in content[:4000].lower() or content.lstrip().startswith("---"))
    )


def _sanitize_draft_documents(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    documents: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        document_key = str(item.get("documentKey") or item.get("document_key") or "").strip().replace("\\", "/")
        content = str(item.get("content") or "").strip()
        if not document_key or not content:
            continue
        if ".." in document_key.split("/") or document_key.startswith("/") or not document_key.endswith(".md"):
            continue
        if document_key in seen:
            continue
        seen.add(document_key)
        documents.append(
            {
                "documentKey": document_key,
                "title": str(item.get("title") or document_key.split("/")[-1]).strip(),
                "content": content[:80_000],
                "contentFormat": "markdown",
            }
        )
        if len(documents) >= 20:
            break
    return documents


def _ensure_skill_body_frontmatter(*, body: str, name: str, description: str) -> str:
    text = body.strip()
    metadata = _markdown_frontmatter(text)
    if metadata.get("name") and metadata.get("description"):
        return text
    stripped = _strip_markdown_frontmatter(text)
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{stripped.lstrip()}"


def _default_skill_body(*, name: str, description: str, title: str) -> str:
    return (
        f"---\nname: {name}\ndescription: {description}\n---\n\n"
        f"# {title}\n\n"
        "## 사용 기준\n\n"
        "- 사용자의 요청이 이 스킬의 목적과 직접 맞을 때 사용한다.\n\n"
        "## 작업 순서\n\n"
        "1. 요청의 목표와 필요한 입력을 확인한다.\n"
        "2. 관련 자료가 있으면 먼저 확인한다.\n"
        "3. 결과를 사용자가 검토하기 쉽게 정리한다.\n\n"
        "## 확인 기준\n\n"
        "- 결과가 사용자 요청의 목적에 맞는지 확인한다.\n"
    )


def _normalize_skill_key(value: str) -> str:
    text = str(value or "").strip().lower().replace("_", "-")
    text = re.sub(r"[^a-z0-9-]+", "-", text)
    text = re.sub(r"-{2,}", "-", text).strip("-")
    return (text or "custom-skill")[:64].rstrip("-") or "custom-skill"


def _display_name(name: str) -> str:
    return name.replace("-", " ").strip().title() or name


def _markdown_frontmatter(content: str) -> dict[str, str]:
    text = content.lstrip("\ufeff")
    if not text.startswith("---"):
        return {}
    match = re.match(r"^---\s*\n(.*?)\n---\s*(?:\n|$)", text, flags=re.DOTALL)
    if not match:
        return {}
    metadata: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line or line.startswith((" ", "\t")) or ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        metadata[key.strip()] = raw_value.strip().strip("'\"")
    return metadata


def _strip_markdown_frontmatter(content: str) -> str:
    text = content.lstrip("\ufeff")
    if not text.startswith("---"):
        return text
    match = re.match(r"^---\s*\n.*?\n---\s*(?:\n|$)", text, flags=re.DOTALL)
    if not match:
        return text
    return text[match.end() :].lstrip()


def _extract_json_object(value: str) -> str:
    text = str(value or "").strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
    if fenced:
        return fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return text[start : end + 1]
    return text


def _agent_visual_key(config: dict[str, Any]) -> str | None:
    image = _normalize_agent_profile_image(str(config.get("profileImage") or "") or None) or ""
    for part in [part for part in image.split("/") if part]:
        if part.startswith("agent") and part[5:].isdigit():
            return part
    template_key = str(config.get("templateKey") or "").strip()
    return {
        "default": "agent01",
        "security_engineer": "agent02",
        "coder": "agent03",
        "qa": "agent04",
        "ux_designer": "agent05",
        "k_services": "agent06",
    }.get(template_key)


def _normalize_agent_profile_image(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    prefix = "/assets/agents/sub/"
    suffix = ".png"
    if text.startswith(prefix) and text.endswith(suffix):
        visual_key = text[len(prefix) : -len(suffix)]
        if visual_key.startswith("agent") and visual_key[5:].isdigit():
            return f"/assets/agents/{visual_key}/idle_front.png"
    return text


def _bundle_response(item: dict[str, Any]) -> AgentInstructionBundleResponse:
    entry_document_key = str(item.get("entry_document_key") or "AGENTS.md")
    if not _is_active_instruction_document(entry_document_key):
        entry_document_key = "AGENTS.md"
    return AgentInstructionBundleResponse(
        bundleId=str(item.get("bundle_id") or ""),
        profileId=str(item.get("profile_id") or ""),
        mode=str(item.get("mode") or "managed"),
        entryDocumentKey=entry_document_key,
        documents=[
            _document_response(document)
            for document in list(item.get("documents") or [])
            if _is_active_instruction_document(document.get("document_key"))
        ],
    )


def _document_response(item: dict[str, Any]) -> AgentInstructionDocumentResponse:
    return AgentInstructionDocumentResponse(
        documentId=item.get("document_id"),
        documentKey=str(item.get("document_key") or ""),
        displayName=str(item.get("display_name") or item.get("document_key") or ""),
        contentFormat=str(item.get("content_format") or "markdown"),
        content=str(item.get("content") or ""),
        version=int(item.get("version") or 1),
    )


def _instruction_display_name(document_key: str) -> str:
    if document_key == "AGENTS.md":
        return "기본 지침"
    if document_key == "SOUL.md":
        return "역할 성향 지침"
    if document_key == "TOOLS.md":
        return "도구 사용 지침"
    return document_key


def _is_active_instruction_document(document_key: Any) -> bool:
    return str(document_key or "").strip() not in REMOVED_INSTRUCTION_DOCUMENT_KEYS


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
