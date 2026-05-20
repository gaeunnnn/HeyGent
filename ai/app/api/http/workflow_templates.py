from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, Field

from app.api.deps.http_auth import authenticate_http_user, ensure_owner
from app.api.deps.openapi_auth import document_bearer_auth
from app.api.http.work import _session_or_404  # type: ignore[attr-defined]
from app.domain.work.service import WorkService
from app.domain.workflow_templates.models import (
    WorkflowTemplate,
    WorkflowTemplateGraph,
)


router = APIRouter(tags=["workflow_templates"], dependencies=[Depends(document_bearer_auth)])


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic 모델
# ──────────────────────────────────────────────────────────────────────────────
class WorkflowTemplateNodeIn(BaseModel):
    slot_key: str = Field(alias="slotKey")
    title: str
    description: str = ""
    assignee_agent_id: str | None = Field(default=None, alias="assigneeAgentId")
    template_key: str | None = Field(default=None, alias="templateKey")
    position_x: float = Field(default=0, alias="positionX")
    position_y: float = Field(default=0, alias="positionY")

    model_config = {"populate_by_name": True}


class WorkflowTemplateEdgeIn(BaseModel):
    source_slot_key: str = Field(alias="sourceSlotKey")
    target_slot_key: str = Field(alias="targetSlotKey")

    model_config = {"populate_by_name": True}


class WorkflowTemplateGraphIn(BaseModel):
    nodes: list[WorkflowTemplateNodeIn] = Field(default_factory=list)
    edges: list[WorkflowTemplateEdgeIn] = Field(default_factory=list)


class WorkflowTemplateCreateRequest(BaseModel):
    name: str
    description: str = ""
    graph: WorkflowTemplateGraphIn


class WorkflowTemplateUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    graph: WorkflowTemplateGraphIn | None = None


class WorkflowTemplateResponse(BaseModel):
    template_id: str = Field(alias="templateId")
    owner_key: str = Field(alias="ownerKey")
    session_id: str | None = Field(default=None, alias="sessionId")
    name: str
    description: str
    graph: dict[str, Any]
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")

    model_config = {"populate_by_name": True}


class WorkflowTemplateListResponse(BaseModel):
    items: list[WorkflowTemplateResponse]
    total_count: int = Field(alias="totalCount")

    model_config = {"populate_by_name": True}


class WorkflowTemplateInstantiateChildResponse(BaseModel):
    slot_key: str = Field(alias="slotKey")
    work_id: str = Field(alias="workId")
    identifier: str
    title: str
    assignee_agent_id: str | None = Field(default=None, alias="assigneeAgentId")

    model_config = {"populate_by_name": True}


class WorkflowTemplateInstantiateResponse(BaseModel):
    root_work_id: str = Field(alias="rootWorkId")
    child_work_ids: list[str] = Field(alias="childWorkIds")
    children_by_slot_key: dict[str, str] = Field(alias="childrenBySlotKey")
    children: list[WorkflowTemplateInstantiateChildResponse]

    model_config = {"populate_by_name": True}


# ──────────────────────────────────────────────────────────────────────────────
# 변환
# ──────────────────────────────────────────────────────────────────────────────
def _to_response(template: WorkflowTemplate) -> WorkflowTemplateResponse:
    return WorkflowTemplateResponse.model_validate(
        {
            "templateId": template.template_id,
            "ownerKey": template.owner_key,
            "sessionId": template.session_id,
            "name": template.name,
            "description": template.description,
            "graph": template.graph.to_jsonable(),
            "createdAt": template.created_at.isoformat() if template.created_at else None,
            "updatedAt": template.updated_at.isoformat() if template.updated_at else None,
        }
    )


def _graph_from_input(payload: WorkflowTemplateGraphIn) -> WorkflowTemplateGraph:
    return WorkflowTemplateGraph.from_jsonable(payload.model_dump(by_alias=True))


# ──────────────────────────────────────────────────────────────────────────────
# CRUD
# ──────────────────────────────────────────────────────────────────────────────
@router.get(
    "/sessions/{sessionId}/workflow-templates",
    response_model=WorkflowTemplateListResponse,
    summary="세션의 워크플로우 템플릿 목록",
)
async def list_workflow_templates(
    request: Request,
    sessionId: str = Path(...),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> WorkflowTemplateListResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    repo = request.app.state.workflow_template_repository
    items = repo.list_for_session(str(user.user_id), sessionId, limit=limit, offset=offset)
    return WorkflowTemplateListResponse(
        items=[_to_response(item) for item in items], totalCount=len(items)
    )


@router.post(
    "/sessions/{sessionId}/workflow-templates",
    response_model=WorkflowTemplateResponse,
    summary="워크플로우 템플릿 생성 (세션 종속)",
)
async def create_workflow_template(
    request: Request,
    payload: WorkflowTemplateCreateRequest,
    sessionId: str = Path(...),
) -> WorkflowTemplateResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    repo = request.app.state.workflow_template_repository
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    template = repo.create(
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
        session_id=sessionId,
        name=name,
        description=payload.description.strip(),
        graph=_graph_from_input(payload.graph),
    )
    return _to_response(template)


@router.get(
    "/sessions/{sessionId}/workflow-templates/{templateId}",
    response_model=WorkflowTemplateResponse,
    summary="워크플로우 템플릿 조회",
)
async def get_workflow_template(
    request: Request,
    sessionId: str = Path(...),
    templateId: str = Path(...),
) -> WorkflowTemplateResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    repo = request.app.state.workflow_template_repository
    template = repo.get(templateId, owner_key=str(user.user_id))
    if template is None or template.session_id != sessionId:
        raise HTTPException(status_code=404, detail="workflow template not found")
    return _to_response(template)


@router.put(
    "/sessions/{sessionId}/workflow-templates/{templateId}",
    response_model=WorkflowTemplateResponse,
    summary="워크플로우 템플릿 수정",
)
async def update_workflow_template(
    request: Request,
    payload: WorkflowTemplateUpdateRequest,
    sessionId: str = Path(...),
    templateId: str = Path(...),
) -> WorkflowTemplateResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    repo = request.app.state.workflow_template_repository
    template = repo.get(templateId, owner_key=str(user.user_id))
    if template is None or template.session_id != sessionId:
        raise HTTPException(status_code=404, detail="workflow template not found")
    updated = repo.update(
        templateId,
        owner_key=str(user.user_id),
        name=payload.name.strip() if payload.name is not None else None,
        description=payload.description.strip() if payload.description is not None else None,
        graph=_graph_from_input(payload.graph) if payload.graph is not None else None,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="workflow template not found")
    return _to_response(updated)


@router.delete(
    "/sessions/{sessionId}/workflow-templates/{templateId}",
    response_model=dict,
    summary="워크플로우 템플릿 삭제",
)
async def delete_workflow_template(
    request: Request,
    sessionId: str = Path(...),
    templateId: str = Path(...),
) -> dict[str, bool]:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    repo = request.app.state.workflow_template_repository
    template = repo.get(templateId, owner_key=str(user.user_id))
    if template is None or template.session_id != sessionId:
        return {"deleted": False}
    deleted = repo.delete(templateId, owner_key=str(user.user_id))
    return {"deleted": deleted}


# ──────────────────────────────────────────────────────────────────────────────
# Instantiate — 그림 → 실제 작업 + 화살표 (자동 실행은 X)
# ──────────────────────────────────────────────────────────────────────────────
@router.post(
    "/sessions/{sessionId}/workflow-templates/{templateId}/instantiate",
    response_model=WorkflowTemplateInstantiateResponse,
    summary="템플릿으로 실제 작업 생성 (실행은 별도)",
)
async def instantiate_workflow_template(
    request: Request,
    sessionId: str = Path(...),
    templateId: str = Path(...),
) -> WorkflowTemplateInstantiateResponse:
    user = await authenticate_http_user(request)
    session = _session_or_404(request, sessionId)
    ensure_owner(user, session.get("user_id"))
    repo = request.app.state.workflow_template_repository
    template = repo.get(templateId, owner_key=str(user.user_id))
    if template is None or template.session_id != sessionId:
        raise HTTPException(status_code=404, detail="workflow template not found")

    work_repo = request.app.state.work_repository
    service = WorkService(work_repo)

    import time

    run_seed = f"wftmpl:{template.template_id}:{int(time.time() * 1000)}"

    # 1) 루트 작업 (템플릿의 컨테이너) — 템플릿 이름을 제목으로
    root = service.create_from_payload(
        session_id=sessionId,
        owner_key=str(user.user_id),
        owner_user_id=_int_or_none(user.user_id),
        payload={
            "title": template.name,
            "description": template.description or template.name,
            "rawUserInput": template.description or template.name,
            "executionInstruction": template.description or template.name,
            "assigneeAgentId": "CEO",
            "metadata": {"workflowTemplateId": template.template_id},
        },
        client_request_id=f"{run_seed}:root",
    )
    work_repo.update_status(root.work_id, "todo")

    # 2) 그림의 각 노드 → 자식 작업 생성
    slot_to_work_id: dict[str, str] = {}
    children: list[WorkflowTemplateInstantiateChildResponse] = []
    for index, node in enumerate(template.graph.nodes):
        child_payload = {
            "title": node.title,
            "description": node.description or node.title,
            "rawUserInput": node.description or node.title,
            "executionInstruction": node.description or node.title,
            "assigneeAgentId": node.assignee_agent_id or "CEO",
            "parentId": root.work_id,
            "flowOrder": index,
            "metadata": {
                "workflowTemplateId": template.template_id,
                "workflowSlotKey": node.slot_key,
            },
        }
        child = service.create_from_payload(
            session_id=sessionId,
            owner_key=str(user.user_id),
            owner_user_id=_int_or_none(user.user_id),
            payload=child_payload,
            client_request_id=f"{run_seed}:{node.slot_key}",
        )
        work_repo.update_status(child.work_id, "todo")
        slot_to_work_id[node.slot_key] = child.work_id
        children.append(
            WorkflowTemplateInstantiateChildResponse(
                slotKey=node.slot_key,
                workId=child.work_id,
                identifier=child.identifier,
                title=child.title,
                assigneeAgentId=child.assignee_agent_id,
            )
        )

    # 3) 그림의 화살표 → blocks 관계
    for edge in template.graph.edges:
        source_id = slot_to_work_id.get(edge.source_slot_key)
        target_id = slot_to_work_id.get(edge.target_slot_key)
        if not source_id or not target_id or source_id == target_id:
            continue
        try:
            work_repo.add_relation(
                source_work_id=source_id,
                target_work_id=target_id,
                relation_type="blocks",
            )
        except Exception:
            # 같은 노드끼리 또는 중복 관계는 무시
            pass

    child_work_ids = list(slot_to_work_id.values())
    return WorkflowTemplateInstantiateResponse(
        rootWorkId=root.work_id,
        childWorkIds=child_work_ids,
        childrenBySlotKey=slot_to_work_id,
        children=children,
    )


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
