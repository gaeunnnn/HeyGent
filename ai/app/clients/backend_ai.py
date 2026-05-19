from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

import httpx

from app.clients.openai_usage_cost import decimal_to_json_number, estimate_openai_usage_cost_usd
from app.core.config import Settings, get_settings


class BackendAiClientError(RuntimeError):
    """backend AI provider/usage 내부 API 호출이나 응답 해석 실패를 나타낸다."""


@dataclass(slots=True)
class BackendCredential:
    provider_name: str
    auth_type: str
    model: str
    credential_type: str
    credential: str
    expires_at: str | None = None


@dataclass(slots=True)
class _CredentialCacheEntry:
    credential: BackendCredential
    expires_at_monotonic: float


class BackendAiClient:
    """AI runtime에서 backend provider credential과 사용량 ledger를 호출하는 client다."""

    DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS = 60 * 60 * 2

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        credential_cache_ttl_seconds: float = DEFAULT_CREDENTIAL_CACHE_TTL_SECONDS,
    ) -> None:
        self._settings = settings or get_settings()
        self._http_client = http_client or httpx.AsyncClient()
        self._owns_http_client = http_client is None
        self._credential_cache_ttl_seconds = credential_cache_ttl_seconds
        self._credential_cache: dict[tuple[int, str, str], _CredentialCacheEntry] = {}

    async def issue_credential(
        self,
        *,
        user_id: str | int,
        provider_name: str,
        model: str,
    ) -> BackendCredential:
        normalized_user_id = self._required_user_id(user_id)
        normalized_provider = self._required_text(provider_name, "providerName")
        normalized_model = self._required_text(model, "model")
        cache_key = (normalized_user_id, normalized_provider, normalized_model)
        cached = self._credential_cache.get(cache_key)
        now = time.monotonic()
        if cached is not None and cached.expires_at_monotonic > now:
            return cached.credential

        try:
            response = await self._http_client.post(
                self._url("/internal/ai/credentials/issue"),
                json={
                    "userId": normalized_user_id,
                    "providerName": normalized_provider,
                    "model": normalized_model,
                },
                headers=self._internal_headers(),
                timeout=self._settings.backend_memory_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise BackendAiClientError("backend credential 발급 요청 중 네트워크 오류가 발생했습니다.") from exc

        credential = self._read_credential(response)
        self._credential_cache[cache_key] = _CredentialCacheEntry(
            credential=credential,
            expires_at_monotonic=now + self._credential_cache_ttl_seconds,
        )
        return credential

    def invalidate_credential_cache(
        self,
        *,
        user_id: str | int,
        provider_name: str,
        model: str | None = None,
    ) -> int:
        normalized_user_id = self._required_user_id(user_id)
        normalized_provider = self._required_text(provider_name, "providerName")
        normalized_model = self._optional_text(model)

        removed = 0
        for cache_key in list(self._credential_cache):
            cache_user_id, cache_provider, cache_model = cache_key
            if cache_user_id != normalized_user_id or cache_provider != normalized_provider:
                continue
            if normalized_model is not None and cache_model != normalized_model:
                continue
            # credential cache는 실제 API key를 담고 있으므로 provider key 저장/삭제 직후에는
            # TTL이 남아 있어도 반드시 버린다. 그렇지 않으면 DB는 새 키인데 모델 호출은
            # 이전 키로 나가는 시간이 생겨 429/권한 오류가 계속 재현될 수 있다.
            self._credential_cache.pop(cache_key, None)
            removed += 1
        return removed

    async def record_command_usage(
        self,
        *,
        user_id: str | int,
        provider_name: str,
        model: str,
        task_run_id: str,
        step_run_id: str | None = None,
        session_id: str | None = None,
        request_id: str | None = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_user_id = self._required_user_id(user_id)
        normalized_provider = self._required_text(provider_name, "providerName")
        normalized_model = self._required_text(model, "model")
        normalized_task_run_id = self._required_text(task_run_id, "taskRunId")
        payload: dict[str, Any] = {
            "userId": normalized_user_id,
            "providerName": normalized_provider,
            "model": normalized_model,
            "taskRunId": normalized_task_run_id,
        }
        self._put_if_present(payload, "stepRunId", self._optional_text(step_run_id))
        self._put_if_present(payload, "sessionId", self._optional_text(session_id))
        self._put_if_present(payload, "requestId", self._optional_text(request_id))
        usage_payload = self._usage_payload(usage or {})
        payload.update(usage_payload)
        estimated_cost = self._estimated_cost_payload(
            provider_name=normalized_provider,
            model=normalized_model,
            usage=usage or {},
            usage_payload=usage_payload,
        )
        self._put_if_present(payload, "estimatedCostUsd", estimated_cost)
        if metadata:
            payload["metadata"] = metadata

        try:
            response = await self._http_client.post(
                self._url("/internal/ai/usages/commands"),
                json=payload,
                headers=self._internal_headers(),
                timeout=self._settings.backend_memory_timeout_seconds,
            )
        except httpx.HTTPError as exc:
            raise BackendAiClientError("backend AI 사용량 기록 요청 중 네트워크 오류가 발생했습니다.") from exc
        self._read_data(response)

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()

    def _url(self, path: str) -> str:
        return f"{self._settings.backend_base_url.rstrip('/')}{path}"

    def _internal_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._settings.internal_service_token or ''}"}

    def _read_credential(self, response: httpx.Response) -> BackendCredential:
        data = self._read_data(response)
        if not isinstance(data, dict):
            raise BackendAiClientError("backend credential 응답 data가 객체가 아닙니다.")
        return BackendCredential(
            provider_name=self._required_text(data.get("providerName"), "providerName"),
            auth_type=self._required_text(data.get("authType"), "authType"),
            model=self._required_text(data.get("model"), "model"),
            credential_type=self._required_text(data.get("credentialType"), "credentialType"),
            credential=self._required_text(data.get("credential"), "credential"),
            expires_at=self._optional_text(data.get("expiresAt")),
        )

    def _read_data(self, response: httpx.Response) -> Any:
        if response.status_code >= 400:
            raise BackendAiClientError(f"backend AI 내부 요청 실패: HTTP {response.status_code}")
        try:
            payload = response.json()
        except ValueError as exc:
            raise BackendAiClientError("backend AI 내부 응답이 JSON 형식이 아닙니다.") from exc
        if not isinstance(payload, dict) or "data" not in payload:
            raise BackendAiClientError("backend AI 내부 응답 wrapper에 data가 없습니다.")
        return payload["data"]

    def _usage_payload(self, usage: dict[str, Any]) -> dict[str, int]:
        input_tokens = self._optional_int(usage.get("input_tokens", usage.get("inputTokens")))
        output_tokens = self._optional_int(usage.get("output_tokens", usage.get("outputTokens")))
        total_tokens = self._optional_int(usage.get("total_tokens", usage.get("totalTokens")))
        cached_tokens = self._optional_int(
            usage.get("cached_input_tokens", usage.get("cachedInputTokens"))
        )
        reasoning_tokens = self._optional_int(usage.get("reasoning_tokens", usage.get("reasoningTokens")))

        input_details = usage.get("input_tokens_details")
        if cached_tokens is None and isinstance(input_details, dict):
            cached_tokens = self._optional_int(input_details.get("cached_tokens"))
        output_details = usage.get("output_tokens_details")
        if reasoning_tokens is None and isinstance(output_details, dict):
            reasoning_tokens = self._optional_int(output_details.get("reasoning_tokens"))

        payload: dict[str, int] = {}
        self._put_if_present(payload, "inputTokens", input_tokens)
        self._put_if_present(payload, "outputTokens", output_tokens)
        self._put_if_present(payload, "totalTokens", total_tokens)
        self._put_if_present(payload, "cachedInputTokens", cached_tokens)
        self._put_if_present(payload, "reasoningTokens", reasoning_tokens)
        return payload

    def _estimated_cost_payload(
        self,
        *,
        provider_name: str,
        model: str,
        usage: dict[str, Any],
        usage_payload: dict[str, int],
    ) -> float | None:
        explicit_cost = usage.get("estimated_cost_usd", usage.get("estimatedCostUsd"))
        if isinstance(explicit_cost, (int, float)) and not isinstance(explicit_cost, bool) and explicit_cost >= 0:
            return float(explicit_cost)
        estimated = estimate_openai_usage_cost_usd(
            provider_name=provider_name,
            model=model,
            input_tokens=usage_payload.get("inputTokens"),
            output_tokens=usage_payload.get("outputTokens"),
            cached_input_tokens=usage_payload.get("cachedInputTokens"),
        )
        return decimal_to_json_number(estimated) if estimated is not None else None

    def _required_user_id(self, value: str | int) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value.strip())
        raise BackendAiClientError("userId는 숫자여야 합니다.")

    def _required_text(self, value: Any, field_name: str) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        raise BackendAiClientError(f"{field_name} 값이 없습니다.")

    def _optional_text(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None

    def _optional_int(self, value: Any) -> int | None:
        if isinstance(value, bool) or value is None:
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float) and value >= 0:
            return int(value)
        return None

    def _put_if_present(self, target: dict[str, Any], key: str, value: Any) -> None:
        if value is not None:
            target[key] = value
