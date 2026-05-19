"""backend 가 provider credential 변경 직후 호출하는 내부 cache 관리 API."""

from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel


router = APIRouter(tags=["credential-cache-internal"])
_bearer_scheme = HTTPBearer(auto_error=False)


class CredentialCacheInvalidateRequest(BaseModel):
    userId: int
    providerName: str
    model: str | None = None


def _require_internal_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    settings = request.app.state.settings
    configured = (settings.internal_service_token or "").strip()
    if not configured:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="internal token not configured")
    provided = (credentials.credentials if credentials else "").strip()
    if not provided or not hmac.compare_digest(provided, configured):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


@router.post(
    "/internal/ai/credential-cache/invalidate",
    summary="backend credential cache 무효화",
    dependencies=[Depends(_require_internal_token)],
)
def invalidate_backend_credential_cache(
    request: Request,
    payload: CredentialCacheInvalidateRequest,
) -> dict[str, Any]:
    """provider API key 저장/삭제 후 AI 런타임에 남은 credential cache를 지운다.

    BackendAiClient 캐시는 2시간 TTL을 유지한다. 다만 사용자가 API key를 바꾼 순간에는
    같은 user/provider/model 조합의 캐시가 더 이상 신뢰할 수 없으므로 backend가 이
    내부 API를 호출해 다음 모델 호출이 새 DB 값을 다시 발급받게 만든다.
    """

    registry = getattr(request.app.state, "provider_registry", None)
    if registry is None:
        return {"invalidated": 0}
    invalidated = registry.invalidate_backend_credential_cache(
        user_id=payload.userId,
        provider_name=payload.providerName,
        model=payload.model,
    )
    return {"invalidated": invalidated}
