from __future__ import annotations

import json
from typing import Any

from app.api.memory_context import MemoryRecallPlan
from app.domain.orchestration.agent.memory.provider_retry import respond_provider_with_retry
from app.domain.orchestration.agent.memory.runtime_context import build_memory_provider_runtime_context, resolve_memory_provider_name
from app.domain.providers.model.base import AgentMessage
from app.domain.providers.registry import ProviderRegistry


class ProviderMemoryRecallPlannerClient:
    """기존 Model Provider를 사용해 memory recall planning JSON을 받아온다."""

    def __init__(self, *, provider_registry: ProviderRegistry, model: str | None = None) -> None:
        self._provider_registry = provider_registry
        self._model = model
        self.last_memory_provider_meta: dict[str, Any] = {}

    async def plan_memory_recall_json(
        self,
        *,
        system_prompt: str,
        query: str,
        workspace_key: str | None,
        rule_plan: MemoryRecallPlan,
        model: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        selected_model = (
            str(self._model or "").strip()
            or str(model or "").strip()
            or str((runtime_context or {}).get("model") or "").strip()
            or str((runtime_context or {}).get("providerModel") or "").strip()
        )
        provider_name = resolve_memory_provider_name(
            (runtime_context or {}).get("provider_name") or (runtime_context or {}).get("providerName"),
            selected_model,
        )
        provider = self._provider_registry.model_provider_for(provider_name)
        if not selected_model:
            selected_model = _default_model_for(provider)
        provider_runtime_context = _runtime_context_with_model(runtime_context, selected_model)
        _ensure_live_provider(provider, runtime_context=provider_runtime_context)
        self.last_memory_provider_meta = {
            "provider_name": str(getattr(provider, "name", None) or provider.__class__.__name__),
            "selected_model": selected_model,
        }
        payload = {
            "query": query,
            "workspaceKey": workspace_key,
            "rulePlanHint": {
                "shouldRecall": rule_plan.should_recall,
                "reason": rule_plan.reason,
                "filters": rule_plan.filters(),
            },
        }
        response = await respond_provider_with_retry(
            provider,
            messages=[
                AgentMessage(role="system", content=system_prompt),
                AgentMessage(role="user", content=json.dumps(payload, ensure_ascii=False)),
            ],
            tools=None,
            model=selected_model,
            tool_choice=None,
            runtime_context=provider_runtime_context,
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
        raise ValueError("memory recall planner response must be a JSON object")
    return parsed


def _ensure_live_provider(provider, *, runtime_context: dict[str, Any] | None = None) -> None:
    health = provider.health()
    if runtime_context and getattr(provider, "auth_type", None) == "api_key":
        return
    if not bool(getattr(health, "connected", False)):
        raise RuntimeError("memory provider requires a connected model provider")


def _default_model_for(provider) -> str:
    if str(getattr(provider, "name", "") or "") == "gemini_api":
        return "gemini-2.5-pro"
    return str(getattr(getattr(provider, "settings", None), "openai_response_model", "") or "gpt-5.4")


def _runtime_context_with_model(runtime_context: dict[str, Any] | None, model: str) -> dict[str, str] | None:
    if not runtime_context:
        return None
    return build_memory_provider_runtime_context(
        user_id=runtime_context.get("user_id") or runtime_context.get("userId"),
        provider_name=runtime_context.get("provider_name") or runtime_context.get("providerName"),
        task_run_id=runtime_context.get("task_run_id") or runtime_context.get("taskRunId"),
        step_run_id=runtime_context.get("step_run_id") or runtime_context.get("stepRunId"),
        session_id=runtime_context.get("session_id") or runtime_context.get("sessionId"),
        model=model,
    )
