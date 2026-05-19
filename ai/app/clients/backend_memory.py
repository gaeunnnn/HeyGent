from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import Settings, get_settings


class BackendMemoryClientError(RuntimeError):
    """backend 장기기억 API 호출이나 응답 해석에 실패했음을 나타낸다."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        response_message: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.response_message = response_message


@dataclass(slots=True)
class BackendMemoryItem:
    """AI prompt/writeback 경계에서 사용할 backend 장기기억 응답 모델이다."""

    id: int
    memory_type: str
    store_type: str
    scope_type: str
    content: str
    summary: str | None = None
    importance: float | None = None
    confidence: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BackendMemoryClient:
    """AI runtime에서 Spring backend 장기기억 API를 호출하는 client이다.

    recall 조회, 기억 후보 저장, 사용 피드백 전달처럼 장기기억의 실제
    저장소인 backend와 통신하는 경계 역할을 맡는다.
    """

    def __init__(self, *, settings: Settings | None = None, http_client: httpx.AsyncClient | None = None) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client or httpx.AsyncClient()
        self._owns_http_client = http_client is None

    async def recall(
        self,
        *,
        user_id: str,
        query: str | None = None,
        limit: int = 5,
        workspace_key: str | None = None,
        store_type: str | None = None,
        memory_type: str | None = None,
        scope_type: str | None = None,
        resource_id: str | None = None,
        tags: list[str] | None = None,
        metadata_categories: list[str] | None = None,
    ) -> list[BackendMemoryItem]:
        """AI 요청 전 prompt에 주입할 장기기억 후보를 조회한다."""

        params: dict[str, Any] = {
            "userId": self._coerce_user_id(user_id),
            "limit": limit,
        }
        self._put_if_present(params, "query", query)
        self._put_if_present(params, "workspaceKey", workspace_key)
        self._put_if_present(params, "storeType", store_type)
        self._put_if_present(params, "memoryType", memory_type)
        self._put_if_present(params, "scopeType", scope_type)
        self._put_if_present(params, "resourceId", resource_id)
        if tags:
            params["tags"] = tags
        if metadata_categories:
            params["metadataCategories"] = metadata_categories

        try:
            response = await self._http_client.get(
                self._url("/internal/ai/memories/recall"),
                params=params,
                headers=self._internal_headers(),
                timeout=self._settings.backend_memory_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise BackendMemoryClientError("backend 장기기억 recall 요청 중 네트워크 오류가 발생했습니다.") from exc
        return self._read_memory_list(response)

    async def create_candidates(
        self,
        *,
        user_id: str,
        candidates: list[dict[str, Any]],
    ) -> list[BackendMemoryItem]:
        """AI가 추출한 장기기억 후보를 backend에 저장 요청한다."""

        try:
            response = await self._http_client.post(
                self._url("/internal/ai/memories/candidates"),
                json={
                    "userId": self._coerce_user_id(user_id),
                    "candidates": candidates,
                },
                headers=self._internal_headers(),
                timeout=self._settings.backend_memory_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise BackendMemoryClientError("backend 장기기억 후보 저장 요청 중 네트워크 오류가 발생했습니다.") from exc
        return self._read_memory_list(response)

    async def mark_used(
        self,
        *,
        user_id: str,
        memory_id: int,
        usefulness_score: float | None = None,
        source_task_run_id: str | None = None,
    ) -> BackendMemoryItem:
        """AI 응답에 실제 사용한 장기기억을 backend에 피드백한다."""

        payload: dict[str, Any] = {"userId": self._coerce_user_id(user_id)}
        if usefulness_score is not None:
            payload["usefulnessScore"] = usefulness_score
        self._put_if_present(payload, "sourceTaskRunId", source_task_run_id)

        try:
            response = await self._http_client.post(
                self._url(f"/internal/ai/memories/{memory_id}/used"),
                json=payload,
                headers=self._internal_headers(),
                timeout=self._settings.backend_memory_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise BackendMemoryClientError("backend 장기기억 사용 피드백 요청 중 네트워크 오류가 발생했습니다.") from exc
        return self._read_memory(response)

    async def aclose(self) -> None:
        """client가 생성한 HTTP 세션만 닫는다."""

        if self._owns_http_client:
            await self._http_client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._settings.backend_base_url.rstrip('/')}{path}"

    def _internal_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.internal_service_token or ''}"}

    def _read_memory_list(self, response: httpx.Response) -> list[BackendMemoryItem]:
        data = self._read_data(response)
        if not isinstance(data, list):
            raise BackendMemoryClientError("backend 장기기억 응답 data가 목록이 아닙니다.")
        return [self._parse_memory_item(item) for item in data]

    def _read_memory(self, response: httpx.Response) -> BackendMemoryItem:
        return self._parse_memory_item(self._read_data(response))

    def _read_data(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            error_code, response_message = _backend_error_details(response)
            raise BackendMemoryClientError(
                f"backend 장기기억 요청 실패: HTTP {response.status_code}",
                status_code=response.status_code,
                error_code=error_code,
                response_message=response_message,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendMemoryClientError("backend 장기기억 응답이 JSON 형식이 아닙니다.") from exc
        if not isinstance(payload, dict):
            raise BackendMemoryClientError("backend 장기기억 응답 wrapper가 객체가 아닙니다.")
        if "data" not in payload:
            raise BackendMemoryClientError("backend 장기기억 응답에 data가 없습니다.")
        return payload["data"]

    def _parse_memory_item(self, value: Any) -> BackendMemoryItem:
        if not isinstance(value, dict):
            raise BackendMemoryClientError("backend 장기기억 항목이 객체가 아닙니다.")
        metadata = value.get("metadata") or {}
        if not isinstance(metadata, dict):
            raise BackendMemoryClientError("backend 장기기억 metadata 형식이 올바르지 않습니다.")
        return BackendMemoryItem(
            id=self._required_int(value.get("id"), "id"),
            memory_type=self._required_str(value.get("memoryType"), "memoryType"),
            store_type=self._required_str(value.get("storeType"), "storeType"),
            scope_type=self._required_str(value.get("scopeType"), "scopeType"),
            content=self._required_str(value.get("content"), "content"),
            summary=self._optional_str(value.get("summary"), "summary"),
            importance=self._optional_float(value.get("importance"), "importance"),
            confidence=self._optional_float(value.get("confidence"), "confidence"),
            metadata=metadata,
        )

    def _coerce_user_id(self, value: str) -> int:
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise BackendMemoryClientError("장기기억 요청 user_id는 숫자 문자열이어야 합니다.") from exc
        if normalized <= 0:
            raise BackendMemoryClientError("장기기억 요청 user_id는 양수여야 합니다.")
        return normalized

    def _required_int(self, value: Any, field_name: str) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        raise BackendMemoryClientError(f"backend 장기기억 응답의 {field_name} 형식이 올바르지 않습니다.")

    def _required_str(self, value: Any, field_name: str) -> str:
        if isinstance(value, str) and value:
            return value
        raise BackendMemoryClientError(f"backend 장기기억 응답의 {field_name} 형식이 올바르지 않습니다.")

    def _optional_str(self, value: Any, field_name: str) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        raise BackendMemoryClientError(f"backend 장기기억 응답의 {field_name} 형식이 올바르지 않습니다.")

    def _optional_float(self, value: Any, field_name: str) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        raise BackendMemoryClientError(f"backend 장기기억 응답의 {field_name} 형식이 올바르지 않습니다.")

    def _put_if_present(self, params: dict[str, Any], key: str, value: str | None) -> None:
        if value is not None and value != "":
            params[key] = value


def _backend_error_details(response: httpx.Response) -> tuple[str | None, str | None]:
    try:
        payload = response.json()
    except ValueError:
        return None, None
    if not isinstance(payload, dict):
        return None, None

    error_code = _optional_text(payload.get("code") or payload.get("errorCode"))
    response_message = _optional_text(payload.get("message") or payload.get("error"))
    return error_code, response_message[:500] if response_message else None


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
