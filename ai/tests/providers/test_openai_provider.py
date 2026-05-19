import httpx
import pytest

from app.core.config import Settings
from app.domain.providers.model.base import build_agent_model_response, parse_assistant_response_contract
from app.domain.providers.model.openai_api import OpenAIAPIProvider
from app.domain.providers.registry import ProviderRegistry


class DummyHTTPResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = str(payload)
        self.request = httpx.Request("POST", "https://example.test")

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request, text=self.text),
            )


def test_openai_api_provider_health_and_stub_respond():
    settings = Settings(openai_api_key="")
    provider = OpenAIAPIProvider(settings)

    health = provider.health()
    response = provider.respond(messages=[{"role": "user", "content": "hello backbone"}], tools=[], model="gpt-test")

    assert health.provider_name == "openai_api"
    assert health.healthy is True
    assert health.configured is False
    assert health.connected is False
    assert response.output_text.startswith("[stub:openai_api]")


def test_parse_assistant_response_contract_extracts_envelope():
    contract = parse_assistant_response_contract(
        """```json
{"text":"완료했습니다.","progressUpdate":{"title":"날씨 조회","summary":"기상 자료 확인 중"},"workDisposition":{"status":"done","summary":"처리 완료"}}
```"""
    )

    assert contract["text"] == "완료했습니다."
    assert contract["progressUpdate"] == {"title": "날씨 조회", "summary": "기상 자료 확인 중"}
    assert contract["workDisposition"] == {"status": "done", "summary": "처리 완료"}


def test_build_agent_model_response_extracts_assistant_envelope():
    response = build_agent_model_response(
        provider_name="openai_api",
        requested_model="gpt-test",
        response_json={
            "id": "resp_contract",
            "model": "gpt-test",
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"text":"정리 완료","progressUpdate":{"title":"자료 정리","summary":"정리 중"},'
                                '"workDisposition":{"status":"done","summary":"완료"}}'
                            ),
                        }
                    ],
                }
            ],
        },
    )

    assert response.visible_text == "정리 완료"
    assert response.progress_update == {"title": "자료 정리", "summary": "정리 중"}
    assert response.work_disposition == {"status": "done", "summary": "완료"}
    assert response.metadata["response_contract"]["progressUpdate"]["title"] == "자료 정리"


def test_openai_api_provider_respond_preserves_native_tool_call(monkeypatch):
    settings = Settings(
        openai_api_key="sk-test",
        openai_rest_api_base_url="https://api.openai.test/v1",
        openai_response_model="gpt-fallback",
    )
    provider = OpenAIAPIProvider(settings)
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None, data=None):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return DummyHTTPResponse(
            {
                "id": "resp_tool",
                "model": "gpt-agent",
                "status": "completed",
                "metadata": {"trace": "abc"},
                "output": [
                    {
                        "type": "reasoning",
                        "summary": [{"text": "도구가 필요함"}],
                        "encrypted_content": "reasoning-token",
                    },
                    {
                        "type": "function_call",
                        "call_id": "call_todo_1",
                        "name": "todo",
                        "arguments": '{"todos":[{"content":"정리","status":"pending"}]}',
                    },
                ],
                "usage": {"input_tokens": 12, "output_tokens": 4},
            }
        )

    monkeypatch.setattr("app.domain.providers.model.openai_api.httpx.post", fake_post)

    response = provider.respond(
        messages=[
            {"role": "user", "content": "할 일을 정리해줘"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_previous",
                        "name": "todo",
                        "arguments": '{"todos":[]}',
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_previous", "content": '{"todos":[]}'},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "todo",
                    "description": "todo list 관리",
                    "parameters": {"type": "object", "properties": {"todos": {"type": "array"}}},
                    "strict": True,
                },
            }
        ],
        model="gpt-agent",
        tool_choice="auto",
    )

    assert captured["url"] == "https://api.openai.test/v1/responses"
    assert captured["timeout"] == settings.agent_model_request_timeout_seconds
    assert captured["json"]["model"] == "gpt-agent"
    assert captured["json"]["input"] == [
        {"role": "user", "content": "할 일을 정리해줘"},
        {"type": "function_call", "call_id": "call_previous", "name": "todo", "arguments": '{"todos":[]}'},
        {"type": "function_call_output", "call_id": "call_previous", "output": '{"todos":[]}'},
    ]
    assert captured["json"]["tools"][0]["name"] == "todo"
    assert captured["json"]["tools"][0]["strict"] is True
    assert captured["json"]["tool_choice"] == "auto"
    assert response.finish_reason == "tool_calls"
    assert response.tool_calls[0].id == "call_todo_1"
    assert response.tool_calls[0].name == "todo"
    assert response.tool_calls[0].arguments["todos"][0]["content"] == "정리"
    assert response.reasoning[0]["encrypted_content"] == "reasoning-token"
    assert response.raw_response["id"] == "resp_tool"
    assert response.metadata["response_id"] == "resp_tool"
    assert response.metadata["raw_metadata"] == {"trace": "abc"}


@pytest.mark.asyncio
async def test_openai_api_provider_uses_backend_credential_and_records_usage_async():
    settings = Settings(
        openai_api_key="",
        openai_rest_api_base_url="https://api.openai.test/v1",
        openai_response_model="gpt-fallback",
    )
    issued: list[dict] = []
    recorded: list[dict] = []
    captured: dict = {}

    class FakeBackendAiClient:
        async def issue_credential(self, **kwargs):
            issued.append(kwargs)

            class Credential:
                provider_name = "openai_api_key"
                model = "gpt-agent"
                credential = "sk-issued"

            return Credential()

        async def record_command_usage(self, **kwargs):
            recorded.append(kwargs)

    class FakeOpenAIHttpClient:
        async def post(self, url, headers=None, json=None, timeout=None, data=None):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            captured["timeout"] = timeout
            return DummyHTTPResponse(
                {
                    "id": "resp_usage",
                    "model": "gpt-agent",
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                    "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
                }
            )

    provider = OpenAIAPIProvider(
        settings,
        http_client=FakeOpenAIHttpClient(),
        backend_ai_client=FakeBackendAiClient(),
    )

    response = await provider.respond_async(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        model="gpt-agent",
        runtime_context={
            "user_id": "10",
            "provider_name": "openai_api_key",
            "task_run_id": "task-1",
            "step_run_id": "step-1",
            "session_id": "session-1",
        },
    )

    assert issued == [{"user_id": "10", "provider_name": "openai_api_key", "model": "gpt-agent"}]
    assert captured["url"] == "https://api.openai.test/v1/responses"
    assert captured["headers"]["Authorization"] == "Bearer sk-issued"
    assert captured["json"]["model"] == "gpt-agent"
    assert captured["timeout"] == settings.agent_model_request_timeout_seconds
    assert recorded == [
        {
            "user_id": "10",
            "provider_name": "openai_api_key",
            "model": "gpt-agent",
            "task_run_id": "task-1",
            "step_run_id": "step-1",
            "session_id": "session-1",
            "request_id": "resp_usage",
            "usage": {"input_tokens": 12, "output_tokens": 4, "total_tokens": 16},
            "metadata": {
                "command": "agent_loop",
                "provider": "openai_api",
                "response_id": "resp_usage",
            },
        }
    ]
    assert response.output_text == "ok"


@pytest.mark.asyncio
async def test_openai_api_provider_uses_backend_credential_without_task_run_id_and_skips_usage_async():
    settings = Settings(
        openai_api_key="",
        openai_rest_api_base_url="https://api.openai.test/v1",
        openai_response_model="gpt-fallback",
    )
    issued: list[dict] = []
    recorded: list[dict] = []
    captured: dict = {}

    class FakeBackendAiClient:
        async def issue_credential(self, **kwargs):
            issued.append(kwargs)

            class Credential:
                provider_name = "openai_api_key"
                model = "gpt-agent"
                credential = "sk-issued"

            return Credential()

        async def record_command_usage(self, **kwargs):
            recorded.append(kwargs)

    class FakeOpenAIHttpClient:
        async def post(self, url, headers=None, json=None, timeout=None, data=None):
            captured["headers"] = headers
            captured["json"] = json
            return DummyHTTPResponse(
                {
                    "id": "resp_memory",
                    "model": "gpt-agent",
                    "status": "completed",
                    "output": [{"type": "message", "content": [{"type": "output_text", "text": "ok"}]}],
                    "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
                }
            )

    provider = OpenAIAPIProvider(
        settings,
        http_client=FakeOpenAIHttpClient(),
        backend_ai_client=FakeBackendAiClient(),
    )

    response = await provider.respond_async(
        messages=[{"role": "user", "content": "hello"}],
        tools=[],
        model="gpt-agent",
        runtime_context={
            "user_id": "10",
            "provider_name": "openai_api_key",
            "session_id": "session-1",
        },
    )

    assert issued == [{"user_id": "10", "provider_name": "openai_api_key", "model": "gpt-agent"}]
    assert captured["headers"]["Authorization"] == "Bearer sk-issued"
    assert captured["json"]["model"] == "gpt-agent"
    assert recorded == []
    assert response.output_text == "ok"


def test_provider_registry_returns_health_list():
    registry = ProviderRegistry([OpenAIAPIProvider(Settings(openai_api_key=""))])

    names = registry.list_names()
    health_list = registry.health()

    assert names == ["openai_api"]
    assert health_list[0].provider_name == "openai_api"


def test_provider_registry_prefers_api_key_provider_for_runtime_backend_credentials():
    settings = Settings(openai_api_key="")
    registry = ProviderRegistry([OpenAIAPIProvider(settings)])

    provider = registry.preferred_model_provider()

    assert provider.name == "openai_api"
