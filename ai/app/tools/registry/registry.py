from __future__ import annotations

from app.tools.contracts import TaskHandler
from app.tools.model.agent_loop import AgentLoopHandler

class ToolRegistry:
    """단일 agent loop 실행자를 제공한다."""

    def __init__(
        self,
        *,
        provider_registry,
        prompt_builder,
        tool_runtime,
        tool_catalog,
        session_store=None,
        enabled_toolsets: tuple[str, ...] | None = None,
    ) -> None:
        _ = enabled_toolsets
        default_provider = provider_registry.preferred_model_provider()
        self._handler = AgentLoopHandler(
            default_provider,
            prompt_builder,
            tool_runtime,
            tool_catalog,
            session_store=session_store,
            provider_registry=provider_registry,
        )

    def resolve(self) -> TaskHandler:
        return self._handler

    def list_toolsets(self) -> list[str]:
        return ["core"]
