from __future__ import annotations

import asyncio
import inspect
import json
import re
from typing import Any

import httpx

from app.clients.backend_ai import BackendAiClient, BackendAiClientError
from app.contracts.provider.provider_response import ProviderAuthResponse, ProviderConnectionResponse, ProviderHealthResponse
from app.core.config import Settings
from app.domain.providers.model.base import (
    AgentMessage,
    AgentModelResponse,
    AssistantToolCall,
    BaseProvider,
    ToolResultMessage,
    coerce_agent_message,
    coerce_assistant_tool_call,
    parse_assistant_response_contract,
)


class GeminiAPIProvider(BaseProvider):
    """Backend에서 발급받은 사용자 Gemini API key로 Gemini REST API를 호출한다."""

    name = "gemini_api"
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
        return ProviderHealthResponse(
            provider_name=self.name,
            healthy=True,
            configured=True,
            connected=True,
            auth_type=self.auth_type,
            detail="사용자별 Gemini API key는 backend credential 발급 경로에서 확인합니다.",
            missing_env=[],
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
        return ProviderAuthResponse(
            provider_name=self.name,
            status="backend_managed",
            detail="Gemini API key provider는 backend 사용자 API key 저장소에서 관리합니다.",
            redirect_uri=redirect_uri,
            state=state,
            missing_env=[],
            metadata={"auth_type": self.auth_type, "force_oauth": force_oauth},
        )

    def complete_auth(self, *, code: str, state: str) -> ProviderConnectionResponse:
        return ProviderConnectionResponse(
            provider_name=self.name,
            status="not_supported",
            connected=True,
            detail="Gemini API key provider는 OAuth callback을 사용하지 않습니다.",
        )

    def refresh_connection(self) -> ProviderConnectionResponse:
        return ProviderConnectionResponse(
            provider_name=self.name,
            status="backend_managed",
            connected=True,
            detail="API key provider는 별도 refresh가 필요 없습니다.",
        )

    def disconnect(self) -> ProviderConnectionResponse:
        return ProviderConnectionResponse(
            provider_name=self.name,
            status="backend_managed",
            connected=True,
            detail="연결 해제는 backend API key 삭제 API에서 처리합니다.",
        )

    def respond(
        self,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentModelResponse:
        if self._credential_context(runtime_context, model) is not None:
            raise RuntimeError("backend credential 기반 Gemini API 호출은 respond_async를 사용해야 합니다")
        return self._stub_agent_response(messages=messages, model=model)

    async def respond_async(
        self,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentModelResponse:
        if type(self).respond is not GeminiAPIProvider.respond:
            kwargs: dict[str, Any] = {
                "messages": messages,
                "tools": tools,
                "model": model,
                "tool_choice": tool_choice,
            }
            if "runtime_context" in inspect.signature(self.respond).parameters:
                kwargs["runtime_context"] = runtime_context
            return await asyncio.to_thread(self.respond, **kwargs)

        requested_model = str(model or "gemini-2.5-pro").strip() or "gemini-2.5-pro"
        credential_context = self._credential_context(runtime_context, requested_model)
        if credential_context is None:
            return self._stub_agent_response(messages=messages, model=requested_model)
        credential = await self._issue_backend_credential(credential_context)
        if credential.credential_type != "api_key":
            raise RuntimeError(f"Gemini API provider는 api_key credential만 지원합니다: {credential.credential_type}")

        request_body = self._build_generate_content_request_body(
            messages=messages,
            tools=tools,
            tool_choice=tool_choice,
        )
        response = await self._http_client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{credential.model}:generateContent",
            headers={"x-goog-api-key": credential.credential},
            json=request_body,
            timeout=self.settings.agent_model_request_timeout_seconds,
        )
        self._raise_for_gemini_error(response)
        agent_response = self._build_agent_model_response(
            provider_name=credential.provider_name,
            requested_model=credential.model,
            response_json=response.json(),
            metadata={
                "mode": "live",
                "auth_type": self.auth_type,
                "connected": True,
                "tool_choice": tool_choice,
            },
        )
        if credential_context.get("task_run_id"):
            await self._record_backend_usage(
                credential_context=credential_context,
                model=agent_response.model,
                provider_name=credential.provider_name,
                response=agent_response,
            )
        return agent_response

    async def aclose(self) -> None:
        if self._owns_http_client:
            await self._http_client.aclose()
        if self._owns_backend_ai_client:
            await self.backend_ai_client.aclose()

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
            return

    def _build_generate_content_request_body(
        self,
        *,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        tool_choice: dict[str, Any] | str | None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"contents": self._messages_to_gemini_contents(messages)}
        declarations = self._tools_to_function_declarations(tools)
        if declarations:
            body["tools"] = [{"functionDeclarations": declarations}]
            if tool_choice == "none":
                body["toolConfig"] = {"functionCallingConfig": {"mode": "NONE"}}
            elif tool_choice is not None:
                body["toolConfig"] = {"functionCallingConfig": {"mode": "AUTO"}}
        return body

    def _messages_to_gemini_contents(
        self,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
    ) -> list[dict[str, Any]]:
        contents: list[dict[str, Any]] = []
        tool_names_by_id: dict[str, str] = {}
        for raw_message in messages:
            message = coerce_agent_message(raw_message)
            if message.role in {"system", "developer"}:
                if message.content not in {None, ""}:
                    contents.append({"role": "user", "parts": [{"text": str(message.content)}]})
                continue
            if message.role == "tool":
                tool_name = tool_names_by_id.get(str(message.tool_call_id or ""), "tool")
                contents.append(
                    {
                        "role": "user",
                        "parts": [
                            {
                                "functionResponse": {
                                    "name": tool_name,
                                    "response": {"content": self._content_to_text(message.content)},
                                }
                            }
                        ],
                    }
                )
                continue

            parts: list[dict[str, Any]] = []
            if message.content not in {None, ""}:
                parts.append({"text": self._content_to_text(message.content)})
            for tool_call in message.tool_calls:
                tool_names_by_id[tool_call.id] = tool_call.name
                parts.append({"functionCall": {"name": tool_call.name, "args": tool_call.arguments}})
            if parts:
                role = "model" if message.role == "assistant" else "user"
                contents.append({"role": role, "parts": parts})
        return contents or [{"role": "user", "parts": [{"text": ""}]}]

    def _tools_to_function_declarations(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        declarations: list[dict[str, Any]] = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            function = tool.get("function") if isinstance(tool.get("function"), dict) else tool
            name = self._optional_text(function.get("name"))
            if name is None:
                continue
            parameters = self._sanitize_schema(function.get("parameters") or {})
            declaration = {
                "name": name,
                "description": str(function.get("description") or ""),
            }
            if parameters is not None:
                declaration["parameters"] = parameters
            declarations.append(declaration)
        return declarations

    @classmethod
    def _sanitize_schema(cls, schema: Any) -> dict[str, Any] | None:
        if not isinstance(schema, dict):
            return None

        sanitized: dict[str, Any] = {}
        schema_type = cls._optional_text(schema.get("type"))
        if schema_type is not None:
            sanitized["type"] = schema_type
        for key in ("description", "format", "title", "nullable"):
            value = schema.get(key)
            if isinstance(value, (str, bool)) and not (isinstance(value, str) and not value.strip()):
                sanitized[key] = value
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            sanitized["enum"] = [value for value in enum_values if isinstance(value, (str, int, float, bool))]
        items = cls._sanitize_schema(schema.get("items"))
        if items is not None:
            sanitized["items"] = items
        properties = schema.get("properties")
        if isinstance(properties, dict):
            sanitized_properties = {
                str(name): property_schema
                for name, raw_property_schema in properties.items()
                if (property_schema := cls._sanitize_schema(raw_property_schema)) is not None
            }
            if sanitized_properties:
                sanitized["properties"] = sanitized_properties
        required = schema.get("required")
        if isinstance(required, list):
            required_values = [value for value in required if isinstance(value, str) and value.strip()]
            property_names = set(sanitized.get("properties") or {})
            if property_names:
                required_values = [value for value in required_values if value in property_names]
            if required_values:
                sanitized["required"] = required_values

        if sanitized.get("type") == "object" and "properties" not in sanitized:
            return None
        if sanitized.get("type") == "array" and "items" not in sanitized:
            sanitized["items"] = {"type": "string"}
        return sanitized or None

    @classmethod
    def _raise_for_gemini_error(cls, response: httpx.Response) -> None:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = cls._gemini_error_detail(response)
            raise RuntimeError(f"Gemini API 요청 실패: HTTP {response.status_code} - {detail}") from error

    @classmethod
    def _gemini_error_detail(cls, response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            error = payload.get("error")
            if isinstance(error, dict):
                message = cls._optional_text(error.get("message"))
                status = cls._optional_text(error.get("status"))
                if message and status:
                    return cls._redact_api_keys(f"{status}: {message}")
                if message:
                    return cls._redact_api_keys(message)
            return cls._redact_api_keys(json.dumps(payload, ensure_ascii=False)[:1000])
        return cls._redact_api_keys(response.text[:1000] or "응답 본문 없음")

    @staticmethod
    def _redact_api_keys(text: str) -> str:
        return re.sub(r"AIza[0-9A-Za-z_-]{20,}", "[REDACTED_GEMINI_API_KEY]", text)

    def _build_agent_model_response(
        self,
        *,
        provider_name: str,
        requested_model: str,
        response_json: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> AgentModelResponse:
        candidate = self._first_candidate(response_json)
        parts = self._candidate_parts(candidate)
        output_text = "\n".join(part["text"] for part in parts if isinstance(part.get("text"), str))
        response_contract = parse_assistant_response_contract(output_text)
        tool_calls = self._extract_tool_calls(parts)
        finish_reason = str(candidate.get("finishReason") or ("tool_calls" if tool_calls else "stop")).lower()
        usage = self._usage(response_json)
        message = AgentMessage(
            role="assistant",
            content=response_contract.get("raw_text") or output_text,
            tool_calls=tool_calls,
            metadata={
                "response_id": response_json.get("responseId"),
                "model": requested_model,
                "response_contract": response_contract.get("contract") or {},
            },
        )
        return AgentModelResponse(
            provider_name=provider_name,
            model=requested_model,
            message=message,
            output_text=output_text,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            usage=usage,
            raw_response=response_json,
            progress_update=response_contract.get("progressUpdate"),
            work_disposition=response_contract.get("workDisposition"),
            visible_text=response_contract.get("text"),
            metadata={
                "response_id": response_json.get("responseId"),
                "model": requested_model,
                "response_contract": response_contract.get("contract") or {},
                **(metadata or {}),
            },
        )

    def _extract_tool_calls(self, parts: list[dict[str, Any]]) -> list[AssistantToolCall]:
        tool_calls: list[AssistantToolCall] = []
        for index, part in enumerate(parts, start=1):
            function_call = part.get("functionCall")
            if not isinstance(function_call, dict):
                continue
            name = self._optional_text(function_call.get("name"))
            if name is None:
                continue
            args = function_call.get("args") if isinstance(function_call.get("args"), dict) else {}
            tool_calls.append(
                coerce_assistant_tool_call(
                    {
                        "id": f"gemini_call_{index}_{name}",
                        "name": name,
                        "arguments": args,
                        "type": "function",
                    }
                )
            )
        return tool_calls

    @staticmethod
    def _first_candidate(response_json: dict[str, Any]) -> dict[str, Any]:
        candidates = response_json.get("candidates")
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], dict):
            return candidates[0]
        return {}

    @staticmethod
    def _candidate_parts(candidate: dict[str, Any]) -> list[dict[str, Any]]:
        content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
        parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        return [part for part in parts if isinstance(part, dict)]

    @staticmethod
    def _usage(response_json: dict[str, Any]) -> dict[str, int]:
        raw = response_json.get("usageMetadata") if isinstance(response_json.get("usageMetadata"), dict) else {}
        usage: dict[str, int] = {}
        mapping = {
            "promptTokenCount": "input_tokens",
            "candidatesTokenCount": "output_tokens",
            "totalTokenCount": "total_tokens",
        }
        for source, target in mapping.items():
            value = raw.get(source)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                usage[target] = value
        return usage

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
    def _content_to_text(content: str | list[dict[str, Any]] | None) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return json.dumps(content, ensure_ascii=False)
        return ""

    @staticmethod
    def _message_preview(messages: list[AgentMessage | ToolResultMessage | dict[str, Any]]) -> str:
        for message in reversed(messages):
            content = message.content if isinstance(message, AgentMessage) else message.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()[:120]
        return ""

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return None
