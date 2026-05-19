from __future__ import annotations
import asyncio
import inspect
from typing import Any

import httpx

from app.clients.backend_ai import BackendAiClient, BackendAiClientError
from app.contracts.provider.provider_response import ProviderAuthResponse, ProviderConnectionResponse, ProviderHealthResponse
from app.core.config import Settings
from app.domain.providers.model.base import (
    AgentMessage,
    AgentModelResponse,
    BaseProvider,
    ToolResultMessage,
    build_agent_model_response,
    messages_to_responses_input,
    tools_to_responses_tools,
)


class OpenAIAPIProvider(BaseProvider):
    """API key 기반 OpenAI Responses provider 다."""

    name = "openai_api"
    auth_type = "api_key"

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.AsyncClient | None = None,
        backend_ai_client: BackendAiClient | None = None,
    ) -> None:
        self.settings = settings
        self.backend_ai_client = backend_ai_client or BackendAiClient(settings=settings)
        self._http_client = http_client or httpx.AsyncClient()
        self._owns_http_client = http_client is None
        self._owns_backend_ai_client = backend_ai_client is None

    def health(self) -> ProviderHealthResponse:
        configured = bool(self.settings.openai_api_key)
        missing_env = [] if configured else ["HEYGENT_OPENAI_API_KEY"]
        detail = "환경 변수의 OpenAI API key 로 실제 OpenAI Responses 호출을 수행할 수 있습니다" if configured else "OpenAI API key 가 없어 REST provider 를 사용할 수 없습니다"
        return ProviderHealthResponse(
            provider_name=self.name,
            healthy=True,
            configured=configured,
            connected=configured,
            auth_type=self.auth_type,
            detail=detail,
            missing_env=missing_env,
            scopes=[],
            expires_at=None,
        )

    def start_auth(
        self,
        *,
        redirect_uri: str | None = None,
        state: str | None = None,
        force_oauth: bool = False,
    ) -> ProviderAuthResponse:
        configured = bool(self.settings.openai_api_key)
        return ProviderAuthResponse(
            provider_name=self.name,
            status="connected" if configured else "configuration_required",
            detail=(
                "OpenAI API key 가 설정되어 있어 바로 사용할 수 있습니다"
                if configured
                else "HEYGENT_OPENAI_API_KEY 를 설정하면 바로 사용할 수 있습니다"
            ),
            redirect_uri=redirect_uri,
            state=state,
            missing_env=[] if configured else ["HEYGENT_OPENAI_API_KEY"],
            metadata={"auth_type": self.auth_type},
        )

    def complete_auth(self, *, code: str, state: str) -> ProviderConnectionResponse:
        return ProviderConnectionResponse(
            provider_name=self.name,
            status="not_supported",
            connected=bool(self.settings.openai_api_key),
            detail="API key provider 는 OAuth callback 을 사용하지 않습니다",
        )

    def refresh_connection(self) -> ProviderConnectionResponse:
        configured = bool(self.settings.openai_api_key)
        return ProviderConnectionResponse(
            provider_name=self.name,
            status="connected" if configured else "configuration_required",
            connected=configured,
            detail=(
                "API key provider 는 별도 refresh 가 필요 없습니다"
                if configured
                else "HEYGENT_OPENAI_API_KEY 를 설정해야 합니다"
            ),
        )

    def disconnect(self) -> ProviderConnectionResponse:
        configured = bool(self.settings.openai_api_key)
        return ProviderConnectionResponse(
            provider_name=self.name,
            status="env_managed",
            connected=configured,
            detail="API key provider 는 .env 또는 환경 변수에서 관리됩니다. 연결 해제는 HEYGENT_OPENAI_API_KEY 제거로 처리합니다",
        )

    def respond(
        self,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentModelResponse:
        requested_model = str(model or self.settings.openai_response_model).strip() or self.settings.openai_response_model
        credential_context = self._credential_context(runtime_context, requested_model)
        if credential_context is not None:
            raise RuntimeError("backend credential 기반 OpenAI API 호출은 respond_async를 사용해야 합니다")
        credential = None
        api_key = credential.credential if credential is not None else self.settings.openai_api_key
        if not api_key:
            return self._stub_agent_response(messages=messages, model=requested_model)
        call_provider_name = credential.provider_name if credential is not None else self.name
        call_model = credential.model if credential is not None else requested_model

        request_body = self._build_responses_request_body(
            messages=messages,
            tools=tools,
            model=call_model,
            tool_choice=tool_choice,
        )
        response = httpx.post(
            f"{self.settings.openai_rest_api_base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=self.settings.agent_model_request_timeout_seconds,
        )
        response.raise_for_status()
        agent_response = build_agent_model_response(
            provider_name=call_provider_name,
            requested_model=call_model,
            response_json=response.json(),
            metadata={
                "mode": "live",
                "auth_type": self.auth_type,
                "connected": True,
                "tool_choice": tool_choice,
            },
        )
        if credential_context is not None and credential_context.get("task_run_id"):
            self._record_backend_usage(
                credential_context=credential_context,
                model=agent_response.model,
                provider_name=call_provider_name,
                response=agent_response,
            )
        return agent_response

    async def respond_async(
        self,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentModelResponse:
        if type(self).respond is not OpenAIAPIProvider.respond:
            kwargs: dict[str, Any] = {
                "messages": messages,
                "tools": tools,
                "model": model,
                "tool_choice": tool_choice,
            }
            if "runtime_context" in inspect.signature(self.respond).parameters:
                kwargs["runtime_context"] = runtime_context
            return await asyncio.to_thread(self.respond, **kwargs)
        requested_model = str(model or self.settings.openai_response_model).strip() or self.settings.openai_response_model
        credential_context = self._credential_context(runtime_context, requested_model)
        credential = await self._issue_backend_credential(credential_context) if credential_context is not None else None
        api_key = credential.credential if credential is not None else self.settings.openai_api_key
        if not api_key:
            return self._stub_agent_response(messages=messages, model=requested_model)
        call_provider_name = credential.provider_name if credential is not None else self.name
        call_model = credential.model if credential is not None else requested_model

        request_body = self._build_responses_request_body(
            messages=messages,
            tools=tools,
            model=call_model,
            tool_choice=tool_choice,
        )
        response = await self._http_client.post(
            f"{self.settings.openai_rest_api_base_url.rstrip('/')}/responses",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=request_body,
            timeout=self.settings.agent_model_request_timeout_seconds,
        )
        response.raise_for_status()
        agent_response = build_agent_model_response(
            provider_name=call_provider_name,
            requested_model=call_model,
            response_json=response.json(),
            metadata={
                "mode": "live",
                "auth_type": self.auth_type,
                "connected": True,
                "tool_choice": tool_choice,
            },
        )
        if credential_context is not None and credential_context.get("task_run_id"):
            await self._record_backend_usage(
                credential_context=credential_context,
                model=agent_response.model,
                provider_name=call_provider_name,
                response=agent_response,
            )
        return agent_response

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()
        if self._owns_backend_ai_client:
            await self.backend_ai_client.aclose()

    async def list_user_models(self, *, user_id: str | int, model: str) -> list[str]:
        requested_model = str(model or self.settings.openai_response_model).strip() or self.settings.openai_response_model
        credential = await self.backend_ai_client.issue_credential(
            user_id=user_id,
            provider_name="openai_api_key",
            model=requested_model,
        )
        response = await self._http_client.get(
            f"{self.settings.openai_rest_api_base_url.rstrip('/')}/models",
            headers={"Authorization": f"Bearer {credential.credential}"},
            timeout=self.settings.agent_model_request_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list):
            return []
        return sorted(
            {
                model_id
                for item in data
                if isinstance(item, dict)
                for model_id in [self._optional_text(item.get("id"))]
                if model_id and _is_openai_text_model(model_id)
            }
        )

    def _credential_context(self, runtime_context: dict[str, Any] | None, model: str) -> dict[str, str] | None:
        if not runtime_context:
            return None
        user_id = self._optional_text(runtime_context.get("user_id") or runtime_context.get("userId"))
        provider_name = self._optional_text(runtime_context.get("provider_name") or runtime_context.get("providerName"))
        task_run_id = self._optional_text(runtime_context.get("task_run_id") or runtime_context.get("taskRunId"))
        if not user_id or not provider_name:
            return None
        return {
            "user_id": user_id,
            "provider_name": provider_name,
            "task_run_id": task_run_id or "",
            "step_run_id": self._optional_text(runtime_context.get("step_run_id") or runtime_context.get("stepRunId")) or "",
            "session_id": self._optional_text(runtime_context.get("session_id") or runtime_context.get("sessionId")) or "",
            "model": model,
        }

    async def _issue_backend_credential(self, context: dict[str, str]):
        try:
            return await self.backend_ai_client.issue_credential(
                user_id=context["user_id"],
                provider_name=context["provider_name"],
                model=context["model"],
            )
        except BackendAiClientError:
            raise

    async def _record_backend_usage(
        self,
        *,
        credential_context: dict[str, str],
        model: str,
        provider_name: str,
        response: AgentModelResponse,
    ) -> None:
        try:
            await self.backend_ai_client.record_command_usage(
                user_id=credential_context["user_id"],
                provider_name=provider_name,
                model=model,
                task_run_id=credential_context["task_run_id"],
                step_run_id=credential_context["step_run_id"] or None,
                session_id=credential_context["session_id"] or None,
                request_id=self._optional_text(response.metadata.get("response_id")),
                usage=response.usage,
                metadata={
                    "command": "agent_loop",
                    "provider": self.name,
                    "response_id": self._optional_text(response.metadata.get("response_id")),
                },
            )
        except BackendAiClientError:
            # 사용량 기록 실패가 사용자 응답 생성을 실패시키지 않도록 모델 응답 경계에서 best-effort로 둔다.
            return

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return None

    def _build_responses_request_body(
        self,
        *,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "store": False,
            "input": messages_to_responses_input(messages),
        }
        normalized_tools = tools_to_responses_tools(tools)
        if normalized_tools:
            body["tools"] = normalized_tools
        if tool_choice is not None:
            body["tool_choice"] = tool_choice
        return body

    def _stub_agent_response(
        self,
        *,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        model: str,
    ) -> AgentModelResponse:
        preview = self._message_preview(messages)
        output_text = f"[stub:{self.name}] {preview}"
        message = AgentMessage(role="assistant", content=output_text)
        return AgentModelResponse(
            provider_name=self.name,
            model=model,
            message=message,
            output_text=output_text,
            finish_reason="stop",
            raw_response={"mode": "stub"},
            metadata={
                "mode": "stub",
                "auth_type": self.auth_type,
                "connected": False,
            },
        )

    @staticmethod
    def _message_preview(messages: list[AgentMessage | ToolResultMessage | dict[str, Any]]) -> str:
        for message in reversed(messages):
            content = message.content if isinstance(message, AgentMessage) else message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()[:120]
        return ""


def _is_openai_text_model(model_id: str) -> bool:
    normalized = model_id.lower()
    if any(
        blocked in normalized
        for blocked in (
            "audio",
            "embedding",
            "image",
            "moderation",
            "realtime",
            "search",
            "sora",
            "transcribe",
            "tts",
            "whisper",
        )
    ):
        return False
    return normalized.startswith("gpt-") or normalized.startswith("o")
