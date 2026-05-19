from __future__ import annotations

from app.domain.providers.model import BaseProvider
from app.tools.contracts import HandlerSpec, OperationTemplate


class AgentLoopHandler:
    """TaskRun 을 agent.loop 중심 실행으로 연결하는 handler 다."""

    spec = HandlerSpec(
        task_type="agent.loop",
        task_title="agent loop 요청",
        step_type="agent.loop.execute",
        step_title="agent loop 실행",
        semantic_key="agent.loop",
        semantic_goal="사용자 요청을 처리하기 위해 모델 응답과 runtime tool 실행을 반복한다.",
        operation_templates=(
            OperationTemplate(key="agent.loop", title="agent loop 실행", kind="agent"),
        ),
    )

    def __init__(
        self,
        provider: BaseProvider,
        prompt_manager,
        tool_runtime,
        tool_catalog,
        session_store=None,
        provider_registry=None,
    ) -> None:
        from app.domain.orchestration.agent.tool_calling_loop import ToolCallingLoopHandler

        self.provider = provider
        self.prompt_manager = prompt_manager
        self.tool_runtime = tool_runtime
        self.tool_catalog = tool_catalog
        self.loop_handler = ToolCallingLoopHandler(
            provider=provider,
            prompt_builder=prompt_manager,
            tool_runtime=tool_runtime,
            tool_catalog=tool_catalog,
            session_store=session_store,
            provider_registry=provider_registry,
        )

    def execute(self, *, task, step=None, resume_payload=None):
        return self.loop_handler.execute(task=task, step=step, resume_payload=resume_payload)

    async def execute_async(
        self,
        *,
        task,
        step=None,
        resume_payload=None,
        progress_sink=None,
        delegate_executor=None,
        session_agent_executor=None,
    ):
        return await self.loop_handler.execute_async(
            task=task,
            step=step,
            resume_payload=resume_payload,
            progress_sink=progress_sink,
            delegate_executor=delegate_executor,
            session_agent_executor=session_agent_executor,
        )
