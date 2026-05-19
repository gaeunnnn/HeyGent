from __future__ import annotations

from fastapi import APIRouter

from app.api.http.agents import router as agents_router
from app.api.http.agent_sessions import router as agent_sessions_router
from app.api.http.bridge_internal import router as bridge_internal_router
from app.api.http.credential_cache_internal import router as credential_cache_internal_router
from app.api.http.device_tokens import router as device_tokens_router
from app.api.http.health import router as health_router
from app.api.http.providers import router as providers_router
from app.api.http.prototypes import router as prototypes_router
from app.api.http.sessions import router as sessions_router
from app.api.http.tasks import router as tasks_router
from app.api.http.work import router as work_router
from app.api.http.workflow_templates import router as workflow_templates_router
from app.api.ws.bridge_gateway import router as bridge_ws_router
from app.api.ws.gateway import router as ws_router
from app.core.config import Settings


def build_api_router(settings: Settings) -> APIRouter:
    """전역 API prefix 를 한 곳에서만 주입한다.

    각 라우터 파일에 /ai/api/v1 를 반복해서 쓰지 않고,
    앱 조립 시점에 한 번만 묶어서 경로 체계를 통일한다.
    """

    api_router = APIRouter(prefix=settings.api_prefix)
    api_router.include_router(health_router)
    api_router.include_router(sessions_router)
    api_router.include_router(prototypes_router)
    api_router.include_router(device_tokens_router)
    api_router.include_router(work_router)
    api_router.include_router(workflow_templates_router)
    api_router.include_router(agents_router)
    api_router.include_router(tasks_router)
    api_router.include_router(agent_sessions_router)
    api_router.include_router(providers_router)
    api_router.include_router(ws_router)
    api_router.include_router(bridge_ws_router)
    api_router.include_router(bridge_internal_router)
    api_router.include_router(credential_cache_internal_router)
    return api_router
