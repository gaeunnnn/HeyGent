from __future__ import annotations

from abc import ABC, abstractmethod
import asyncio
import inspect
import json
import re
from typing import Any, Literal

from pydantic import Field

from app.contracts.common.base import ContractModel
from app.contracts.provider.provider_response import ProviderAuthResponse, ProviderConnectionResponse, ProviderHealthResponse


AgentRole = Literal["system", "developer", "user", "assistant", "tool"]


class AssistantToolCall(ContractModel):
    """assistant가 요청한 native tool call(모델이 구조화된 도구 호출을 직접 반환하는 방식)이다."""

    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    arguments_json: str | None = None
    type: str = "function"
    raw: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(ContractModel):
    """agent.loop가 provider에 넘기는 내부 메시지 형식이다.

    provider별 원본 message 형식은 여기로 모은 뒤 adapter에서 다시 변환한다. 이렇게 해야
    agent.loop가 특정 provider의 tool call 표현에 묶이지 않는다.
    """

    role: AgentRole
    content: str | list[dict[str, Any]] | None = None
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)
    tool_call_id: str | None = None
    name: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolResultMessage(AgentMessage):
    """runtime tool 실행 결과를 모델에게 다시 넘기는 메시지다.

    tool_call_id는 assistant가 보낸 호출 id와 같은 값이어야 모델이 도구 응답을 이어 붙일 수 있다.
    """

    role: Literal["tool"] = "tool"
    tool_call_id: str
    content: str


class AgentModelResponse(ContractModel):
    """agent.loop가 소비하는 표준 provider 응답이다.

    output_text는 사용자에게 보여 줄 텍스트이고, tool_calls는 실행해야 할 구조화된 호출 목록이다.
    둘이 동시에 올 수 있으므로 loop 종료 여부는 output_text가 아니라 tool_calls 유무로 판단한다.
    """

    provider_name: str
    model: str
    message: AgentMessage
    output_text: str = ""
    tool_calls: list[AssistantToolCall] = Field(default_factory=list)
    finish_reason: str | None = None
    reasoning: Any = None
    usage: dict[str, Any] = Field(default_factory=dict)
    raw_response: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    progress_update: dict[str, Any] | None = None
    work_disposition: dict[str, Any] | None = None
    visible_text: str | None = None


def coerce_agent_message(message: AgentMessage | ToolResultMessage | dict[str, Any]) -> AgentMessage:
    """dict로 들어온 transcript 항목을 agent.loop 내부 메시지 계약으로 정규화한다."""

    if isinstance(message, AgentMessage):
        return message
    if not isinstance(message, dict):
        raise TypeError(f"unsupported agent message type: {type(message)!r}")

    tool_calls = [coerce_assistant_tool_call(tool_call) for tool_call in message.get("tool_calls") or []]
    role = message.get("role")
    if role not in {"system", "developer", "user", "assistant", "tool"}:
        raise ValueError(f"unsupported message role: {role!r}")
    return AgentMessage(
        role=role,
        content=message.get("content"),
        tool_calls=tool_calls,
        tool_call_id=message.get("tool_call_id") or message.get("call_id"),
        name=message.get("name"),
        metadata=message.get("metadata") or {},
    )


def coerce_assistant_tool_call(tool_call: AssistantToolCall | dict[str, Any]) -> AssistantToolCall:
    """provider별 tool call 모양을 AssistantToolCall 하나로 맞춘다.

    arguments는 문자열 JSON이나 이미 파싱된 dict로 올 수 있다. 파싱에 실패한 원문은 버리지 않고
    _raw에 보존해 이후 도구 검증이나 실행 단계에서 처리하게 둔다.
    """

    if isinstance(tool_call, AssistantToolCall):
        return tool_call
    if not isinstance(tool_call, dict):
        raise TypeError(f"unsupported tool call type: {type(tool_call)!r}")

    function = tool_call.get("function") if isinstance(tool_call.get("function"), dict) else {}
    name = tool_call.get("name") or function.get("name")
    arguments_json = tool_call.get("arguments") or function.get("arguments")
    arguments: dict[str, Any] = {}
    if isinstance(arguments_json, dict):
        arguments = arguments_json
        arguments_json = json.dumps(arguments, ensure_ascii=False)
    elif isinstance(arguments_json, str) and arguments_json.strip():
        try:
            parsed = json.loads(arguments_json)
            arguments = parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            arguments = {"_raw": arguments_json}
    return AssistantToolCall(
        id=str(tool_call.get("id") or tool_call.get("call_id") or ""),
        name=str(name or ""),
        arguments=arguments,
        arguments_json=arguments_json if isinstance(arguments_json, str) else None,
        type=str(tool_call.get("type") or "function"),
        raw=tool_call,
    )


def messages_to_responses_input(messages: list[AgentMessage | ToolResultMessage | dict[str, Any]]) -> list[dict[str, Any]]:
    """내부 transcript를 provider 요청용 message item 목록으로 변환한다."""

    items: list[dict[str, Any]] = []
    for message in messages:
        items.extend(_message_to_responses_items(coerce_agent_message(message)))
    return items


def tools_to_responses_tools(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """agent.loop의 function wrapper schema를 provider 요청 schema로 평탄화한다."""

    normalized: list[dict[str, Any]] = []
    for tool in tools or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "function" and isinstance(tool.get("function"), dict):
            function = tool["function"]
            flat = {
                "type": "function",
                "name": function.get("name"),
                "description": function.get("description", ""),
                "parameters": function.get("parameters") or {},
            }
            if "strict" in function:
                flat["strict"] = function["strict"]
            normalized.append(flat)
        else:
            normalized.append(dict(tool))
    return normalized


def build_agent_model_response(
    *,
    provider_name: str,
    requested_model: str,
    response_json: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> AgentModelResponse:
    """provider 원본 응답에서 agent.loop가 필요한 텍스트, tool call, 사용량 정보를 추출한다."""

    output_text = extract_responses_output_text(response_json)
    response_contract = parse_assistant_response_contract(output_text)
    tool_calls = extract_responses_tool_calls(response_json)
    reasoning = extract_responses_reasoning(response_json)
    model = str(response_json.get("model") or requested_model)
    finish_reason = _resolve_finish_reason(response_json, tool_calls)
    usage = response_json.get("usage") if isinstance(response_json.get("usage"), dict) else {}
    message = AgentMessage(
        role="assistant",
        content=response_contract.get("raw_text") or output_text,
        tool_calls=tool_calls,
        metadata={
            "response_id": response_json.get("id"),
            "model": model,
            "status": response_json.get("status"),
            "raw_metadata": response_json.get("metadata") if isinstance(response_json.get("metadata"), dict) else {},
            "response_contract": response_contract.get("contract") or {},
        },
    )
    return AgentModelResponse(
        provider_name=provider_name,
        model=model,
        message=message,
        output_text=output_text,
        tool_calls=tool_calls,
        finish_reason=finish_reason,
        reasoning=reasoning,
        usage=usage,
        raw_response=response_json,
        progress_update=response_contract.get("progressUpdate"),
        work_disposition=response_contract.get("workDisposition"),
        visible_text=response_contract.get("text"),
        metadata={
            "response_id": response_json.get("id"),
            "model": model,
            "status": response_json.get("status"),
            "raw_metadata": response_json.get("metadata") if isinstance(response_json.get("metadata"), dict) else {},
            "response_contract": response_contract.get("contract") or {},
            **(metadata or {}),
        },
    )


def parse_assistant_response_contract(output_text: str) -> dict[str, Any]:
    """assistant text envelope를 provider 공통 실행 metadata로 정규화한다.

    모델은 최종 답변 본문과 진행 상태를 같은 assistant 응답으로만 돌려준다. runtime tool로
    상태를 선언하지 않으므로 provider adapter 단계에서 `{text, progressUpdate, workDisposition}`
    형태를 한 번 표준화해 loop가 provider별 JSON 모양을 몰라도 되게 한다.
    """

    raw_text = str(output_text or "")
    parsed = _parse_json_object_from_text(raw_text)
    if not isinstance(parsed, dict):
        return {"text": raw_text, "raw_text": raw_text, "contract": {}}

    contract_keys = {"text", "answer", "progressUpdate", "workDisposition"}
    if not any(key in parsed for key in contract_keys):
        return {"text": raw_text, "raw_text": raw_text, "contract": {}}

    visible_text = parsed.get("text")
    if not isinstance(visible_text, str):
        visible_text = parsed.get("answer") if isinstance(parsed.get("answer"), str) else raw_text
    progress_update = parsed.get("progressUpdate") if isinstance(parsed.get("progressUpdate"), dict) else None
    work_disposition = parsed.get("workDisposition") if isinstance(parsed.get("workDisposition"), dict) else None
    return {
        "text": str(visible_text or "").strip(),
        "raw_text": raw_text,
        "progressUpdate": progress_update,
        "workDisposition": work_disposition,
        "contract": {
            "progressUpdate": progress_update,
            "workDisposition": work_disposition,
        },
    }


def _parse_json_object_from_text(text: str) -> dict[str, Any] | None:
    stripped = str(text or "").strip()
    if not stripped:
        return None
    candidates = [stripped]
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        candidates.insert(0, fenced.group(1).strip())
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def extract_responses_output_text(response_json: dict[str, Any]) -> str:
    """provider 응답의 여러 content 위치에서 assistant 텍스트만 모은다."""

    direct = response_json.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct

    collected: list[str] = []
    for item in response_json.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message" or item.get("role") == "assistant":
            collected.extend(_extract_content_texts(item.get("content")))
    return "\n".join(text for text in collected if text)


def extract_responses_tool_calls(response_json: dict[str, Any]) -> list[AssistantToolCall]:
    """provider 응답에서 실행 가능한 native tool call만 추출한다."""

    tool_calls: list[AssistantToolCall] = []
    for item in response_json.get("output", []):
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"function_call", "tool_call"}:
            tool_calls.append(coerce_assistant_tool_call(item))
            continue
        if item.get("type") == "message" or item.get("role") == "assistant":
            for tool_call in item.get("tool_calls") or []:
                tool_calls.append(coerce_assistant_tool_call(tool_call))
    return [tool_call for tool_call in tool_calls if tool_call.id and tool_call.name]


def extract_responses_reasoning(response_json: dict[str, Any]) -> Any:
    """reasoning 계열 원본 필드는 실행 로직에 쓰지 않고 관측용으로만 보존한다."""

    if "reasoning" in response_json:
        return response_json["reasoning"]
    if "reasoning_details" in response_json:
        return response_json["reasoning_details"]

    reasoning_items: list[dict[str, Any]] = []
    for item in response_json.get("output", []):
        if isinstance(item, dict) and item.get("type") == "reasoning":
            reasoning_items.append(item)
    return reasoning_items or None


def _message_to_responses_items(message: AgentMessage) -> list[dict[str, Any]]:
    """내부 메시지 하나를 provider request item 하나 이상으로 변환한다.

    Responses API는 assistant의 이전 tool call을 message.tool_calls 필드로 받지 않고
    function_call item으로 replay(이전 호출을 입력에 다시 넣는 것)해야 한다.
    """

    if message.role == "tool":
        return [
            {
                "type": "function_call_output",
                "call_id": message.tool_call_id,
                "output": _content_to_text(message.content),
            }
        ]

    items: list[dict[str, Any]] = []
    if message.content not in {None, ""} or not message.tool_calls:
        item: dict[str, Any] = {
            "role": message.role,
            "content": _message_content_to_responses_content(message),
        }
        if message.name:
            item["name"] = message.name
        items.append(item)
    items.extend(_tool_call_to_responses_item(tool_call) for tool_call in message.tool_calls)
    return items


def _message_content_to_responses_content(message: AgentMessage) -> str | list[dict[str, Any]]:
    content = message.content
    if isinstance(content, list):
        return content
    if content is None:
        return ""
    return str(content)


def _tool_call_to_responses_item(tool_call: AssistantToolCall) -> dict[str, Any]:
    return {
        "type": "function_call",
        "call_id": tool_call.id,
        "name": tool_call.name,
        "arguments": tool_call.arguments_json or json.dumps(tool_call.arguments, ensure_ascii=False),
    }


def _extract_content_texts(content: Any) -> list[str]:
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []

    texts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if part.get("type") in {"output_text", "text"} and isinstance(text, str):
            texts.append(text)
    return texts


def _content_to_text(content: str | list[dict[str, Any]] | None) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts = _extract_content_texts(content)
        if texts:
            return "\n".join(texts)
        return json.dumps(content, ensure_ascii=False)
    return ""


def _resolve_finish_reason(response_json: dict[str, Any], tool_calls: list[AssistantToolCall]) -> str | None:
    if tool_calls:
        return "tool_calls"
    for key in ("finish_reason", "stop_reason", "status"):
        value = response_json.get(key)
        if isinstance(value, str) and value:
            return value
    return "stop" if extract_responses_output_text(response_json).strip() else None


class BaseProvider(ABC):
    """모델 SDK 직접 의존을 숨기는 최소 Provider 인터페이스다."""

    name: str

    @abstractmethod
    def health(self) -> ProviderHealthResponse:
        """현재 프로바이더 사용 가능 여부를 반환한다."""

    @abstractmethod
    def start_auth(
        self,
        *,
        redirect_uri: str | None = None,
        state: str | None = None,
        force_oauth: bool = False,
    ) -> ProviderAuthResponse:
        """OAuth 시작에 필요한 메타데이터를 반환한다.

        현재 단계에서는 실제 callback 처리를 완성하지 않더라도,
        어떤 설정이 필요하고 어떤 authorization URL(사용자 인증 페이지 주소)로 이동해야 하는지는
        공통 인터페이스로 노출해 두는 것이 중요하다.
        """

    @abstractmethod
    def complete_auth(self, *, code: str, state: str) -> ProviderConnectionResponse:
        """OAuth callback 이후 토큰 교환과 저장을 수행한다."""

    @abstractmethod
    def refresh_connection(self) -> ProviderConnectionResponse:
        """저장된 refresh token(갱신용 토큰)으로 access token(호출용 토큰)을 갱신한다."""

    @abstractmethod
    def disconnect(self) -> ProviderConnectionResponse:
        """저장된 provider 연결 정보를 제거한다."""

    @abstractmethod
    def respond(
        self,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentModelResponse:
        """agent.loop용 message/tool 기반 응답을 반환한다."""

    async def respond_async(
        self,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> AgentModelResponse:
        """비동기 실행 경로용 응답을 반환한다.

        기존 sync provider는 thread fallback으로 호환하고, event-loop bound provider는 native async로
        override한다.
        """

        kwargs: dict[str, Any] = {
            "messages": messages,
            "tools": tools,
            "model": model,
            "tool_choice": tool_choice,
        }
        if "runtime_context" in inspect.signature(self.respond).parameters:
            kwargs["runtime_context"] = runtime_context
        return await asyncio.to_thread(self.respond, **kwargs)
