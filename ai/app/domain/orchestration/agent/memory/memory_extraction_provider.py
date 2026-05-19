from __future__ import annotations

import json
from typing import Any

from app.domain.orchestration.agent.memory.memory_extractor import MemoryExtractionContext
from app.domain.orchestration.agent.memory.memory_reconciler import MemoryReconciliationContext
from app.domain.orchestration.agent.memory.provider_retry import respond_provider_with_retry
from app.domain.orchestration.agent.memory.runtime_context import build_memory_provider_runtime_context, resolve_memory_provider_name
from app.domain.providers.model.base import AgentMessage
from app.domain.providers.registry import ProviderRegistry


_MEMORY_EXTRACTION_RETRY_DELAYS = (1.0, 2.0, 4.0, 8.0)


class ProviderMemoryExtractionClient:
    """기존 Model Provider를 사용해 memory extraction JSON을 받아온다."""

    def __init__(self, *, provider_registry: ProviderRegistry, model: str | None = None) -> None:
        self._provider_registry = provider_registry
        self._model = model
        self.last_memory_provider_meta: dict[str, Any] = {}

    async def extract_memory_json(
        self,
        *,
        system_prompt: str,
        user_message: str,
        assistant_message: str,
        context: MemoryExtractionContext,
    ) -> dict[str, Any]:
        provider_name = resolve_memory_provider_name(context.provider_name, context.model)
        provider = self._provider_registry.model_provider_for(provider_name)
        model = _select_model(provider, configured_model=self._model, requested_model=context.model)
        runtime_context = build_memory_provider_runtime_context(
            user_id=context.user_id,
            provider_name=provider_name,
            task_run_id=context.task_run_id,
            step_run_id=context.step_run_id,
            session_id=context.session_id,
            model=model,
        )
        _ensure_live_provider(provider, runtime_context=runtime_context)
        self.last_memory_provider_meta = _provider_meta(provider, model=model, retry_delays=_MEMORY_EXTRACTION_RETRY_DELAYS)
        payload = {
            "userMessage": user_message,
            "assistantMessage": assistant_message,
            "context": {
                "userId": context.user_id,
                "sessionId": context.session_id,
                "workspaceKey": context.workspace_key,
                "taskRunId": context.task_run_id,
                "requestDate": context.request_date,
            },
        }
        response = await respond_provider_with_retry(
            provider,
            retry_delays=_MEMORY_EXTRACTION_RETRY_DELAYS,
            messages=[
                AgentMessage(role="system", content=system_prompt),
                AgentMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            tools=None,
            model=model,
            tool_choice=None,
            runtime_context=runtime_context,
        )
        return _parse_json_object(response.output_text)

    async def reconcile_memory_operation_json(
        self,
        *,
        system_prompt: str,
        user_message: str,
        candidate: dict[str, Any],
        existing_memories: list[dict[str, Any]],
        context: MemoryReconciliationContext,
    ) -> dict[str, Any]:
        provider_name = resolve_memory_provider_name(context.provider_name, context.model)
        provider = self._provider_registry.model_provider_for(provider_name)
        model = _select_model(provider, configured_model=self._model, requested_model=context.model)
        runtime_context = build_memory_provider_runtime_context(
            user_id=context.user_id,
            provider_name=provider_name,
            task_run_id=context.task_run_id,
            step_run_id=context.step_run_id,
            session_id=context.session_id,
            model=model,
        )
        _ensure_live_provider(provider, runtime_context=runtime_context)
        self.last_memory_provider_meta = _provider_meta(provider, model=model)
        payload = {
            "userMessage": user_message,
            "candidate": candidate,
            "existingMemories": existing_memories,
            "context": {
                "userId": context.user_id,
                "workspaceKey": context.workspace_key,
            },
        }
        response = await respond_provider_with_retry(
            provider,
            messages=[
                AgentMessage(role="system", content=system_prompt),
                AgentMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            tools=None,
            model=model,
            tool_choice=None,
            runtime_context=runtime_context,
        )
        return _parse_json_object(response.output_text)


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    parsed = json.loads(stripped)
    if not isinstance(parsed, dict):
        raise ValueError("memory extraction response must be a JSON object")
    return parsed


def _select_model(provider, *, configured_model: str | None, requested_model: str | None) -> str:
    return (
        str(configured_model or "").strip()
        or str(requested_model or "").strip()
        or _default_model_for(provider)
    )


def _ensure_live_provider(provider, *, runtime_context: dict[str, Any] | None = None) -> None:
    health = provider.health()
    if runtime_context and getattr(provider, "auth_type", None) == "api_key":
        return
    if not bool(getattr(health, "connected", False)):
        raise RuntimeError("memory provider requires a connected model provider")


def _provider_meta(provider, *, model: str, retry_delays: tuple[float, ...] = (0.5, 1.0)) -> dict[str, Any]:
    return {
        "provider_name": str(getattr(provider, "name", None) or provider.__class__.__name__),
        "selected_model": model,
        "max_attempts": len(retry_delays) + 1,
    }


def _default_model_for(provider) -> str:
    if str(getattr(provider, "name", "") or "") == "gemini_api":
        return "gemini-2.5-pro"
    return str(getattr(getattr(provider, "settings", None), "openai_response_model", "") or "gpt-5.4")
