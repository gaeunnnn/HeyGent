from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
from typing import Any

from app.contracts.task.step_status import StepStatus
from app.contracts.task.task_status import TaskStatus
from app.core.utils.ids import new_id
from app.domain.orchestration.capabilities import apply_task_capabilities
from app.domain.orchestration.agent.tool_failure_circuit import (
    RunLocalToolFailureCircuit,
    build_provider_failure_payload,
    classify_provider_failure,
)
from app.domain.orchestration.agent.tool_guard import ToolGuard, ToolGuardDecision, ToolGuardResult
from app.domain.orchestration.agent.tool_result_store import store_raw_tool_result
from app.domain.providers.model.base import AgentMessage, AgentModelResponse, ToolResultMessage, parse_assistant_response_contract
from app.domain.orchestration.prompts.prompt_builder import assemble_agent_loop_messages
from app.domain.session.sessions.transcript_store import TranscriptStore
from app.domain.orchestration.runtime_planning.todo_state import (
    apply_tool_results_to_todo_state,
    build_task_todo_payload,
    build_todo_detail_patch,
    parse_task_todo_payload,
)


class ToolCallingLoopHandler:
    """현재 provider 위에서 native tool call(모델이 구조화된 도구 호출을 직접 반환하는 방식) loop를 실행한다."""

    TOOL_RESULT_OBSERVATION_MAX_CHARS = 12_000
    TOOL_RESULT_INLINE_MAX_CHARS = 12_000
    TOOL_RESULT_PREVIEW_MAX_CHARS = 6_000
    TOOL_RESULT_ARRAY_SAMPLE_SIZE = 3

    def __init__(
        self,
        provider,
        prompt_builder,
        tool_runtime,
        tool_catalog,
        session_store: TranscriptStore | None = None,
        tool_guard=None,
        provider_registry=None,
    ) -> None:
        self.provider = provider
        self.provider_registry = provider_registry
        self.prompt_builder = prompt_builder
        self.tool_runtime = tool_runtime
        self.tool_catalog = tool_catalog
        self.session_store = session_store
        self.tool_guard = tool_guard or ToolGuard()

    def execute(self, *, task, step, resume_payload=None) -> dict[str, Any]:
        return asyncio.run(self.execute_async(task=task, step=step, resume_payload=resume_payload))

    async def execute_async(
        self,
        *,
        task,
        step,
        resume_payload=None,
        progress_sink=None,
        delegate_executor=None,
        session_agent_executor=None,
    ) -> dict[str, Any]:
        task_input = dict(task.input_payload or {})
        apply_task_capabilities(
            task_input,
            skill_registry=getattr(self.tool_runtime, "skill_registry", None),
            default_toolsets=getattr(self.tool_catalog, "default_toolsets", None),
        )
        # 요청 payload의 workspace_root는 API 호출자가 선택한 이번 실행 root로 바인딩한다.
        request_tool_runtime = self._bind_request_tool_runtime(
            workspace_root=task_input.get("workspace_root"),
            owner_key=getattr(task, "owner_key", None),
            runtime_context=task_input,
        )
        requested_toolsets = self._requested_toolsets(task_input)
        available_tools = self.tool_catalog.list_available_tools(requested_toolsets=requested_toolsets)
        operation_counters: dict[str, int] = {}
        current_todo_state = dict(task.todo_state or {})

        return await self._execute_native(
            task=task,
            step=step,
            task_input=task_input,
            available_tools=available_tools,
            requested_toolsets=requested_toolsets,
            tool_runtime=request_tool_runtime,
            resume_payload=resume_payload,
            operation_counters=operation_counters,
            current_todo_state=current_todo_state,
            progress_sink=progress_sink,
            delegate_executor=delegate_executor,
            session_agent_executor=session_agent_executor,
        )

    async def _execute_native(
        self,
        *,
        task,
        step,
        task_input: dict[str, Any],
        available_tools: list[dict[str, Any]],
        requested_toolsets: tuple[str, ...] | None,
        tool_runtime,
        resume_payload: dict[str, Any] | None,
        operation_counters: dict[str, int],
        current_todo_state: dict[str, Any],
        progress_sink,
        delegate_executor=None,
        session_agent_executor=None,
    ) -> dict[str, Any]:
        """모델 응답과 runtime tool 실행을 번갈아 수행한다.

        모델이 tool_calls 없이 최종 텍스트를 반환하면 loop를 종료하고, tool_calls가 있으면
        같은 대화 이력에 ToolResultMessage를 붙여 다음 모델 호출에서 이어서 판단하게 한다.
        """

        all_tool_results: list[dict[str, Any]] = []
        operations: list[dict[str, Any]] = []
        failure_circuit = RunLocalToolFailureCircuit()
        max_iterations = self._max_iterations(task_input)
        model = self._optional_text(task_input.get("model")) or self._provider_default_model()
        transcript_session_id = self._ensure_transcript_session(task=task, task_input=task_input, model=model)
        provider_tools, provider_tool_name_map = self._provider_tool_schemas(available_tools)
        prompt_tools = self._provider_prompt_tools(available_tools, provider_tool_name_map)
        prompt = self.prompt_builder.build_agent_loop_prompt(
            input_payload=task_input,
            available_tools=prompt_tools,
            tool_results=[],
            task_todo_state=current_todo_state,
            resume_payload=resume_payload,
            turn_index=1,
            max_iterations=max_iterations,
        )
        messages = self._load_transcript_messages(transcript_session_id)
        guard_task_input = self._task_input_for_guard(task_input=task_input, step=step, resume_payload=resume_payload)
        if resume_payload is not None:
            # resume은 WAITING 상태였던 StepRun(사용자에게 보이는 의미 단계의 실행 anchor)을 이어서 처리한다.
            resumed_tool_result = self._resolve_pending_tool_after_resume(
                step=step,
                resume_payload=resume_payload,
                requested_toolsets=requested_toolsets,
                tool_runtime=tool_runtime,
            )
            if resumed_tool_result is not None:
                self._append_tool_result_observation(
                    tool_result=resumed_tool_result,
                    all_tool_results=all_tool_results,
                    messages=messages,
                    transcript_session_id=transcript_session_id,
                    operations=operations,
                    operation_counters=operation_counters,
                )
                failure_circuit.record_result(
                    tool_name=str(resumed_tool_result.get("name") or ""),
                    args=dict(resumed_tool_result.get("args") or {}),
                    result=resumed_tool_result.get("result"),
                )
                messages = self._order_tool_results_for_replay(messages)
                current_todo_state = self._next_todo_state(current_todo_state, all_tool_results)
        new_turn_messages = self._new_turn_messages(task_input=task_input, prompt=prompt, replay_messages=messages)
        messages.extend(new_turn_messages)
        for message in new_turn_messages:
            self._append_transcript_message(transcript_session_id, message)
        generated = None
        llm_call_count = 0

        for turn_index in range(1, max_iterations + 1):
            model_started_at = time.perf_counter()
            runtime_context = self._model_runtime_context(task=task, step=step, task_input=task_input)
            await self._emit_model_call_progress(
                progress_sink=progress_sink,
                event_type="model.started",
                turn_index=turn_index,
                model=model,
                runtime_context=runtime_context,
                messages=messages,
                tools=provider_tools,
            )
            try:
                generated = await self._respond_with_runtime_context_async(
                    messages=messages,
                    tools=provider_tools,
                    model=model,
                    tool_choice=None,
                    runtime_context=runtime_context,
                )
            except Exception as exc:
                await self._emit_model_call_progress(
                    progress_sink=progress_sink,
                    event_type="model.failed",
                    turn_index=turn_index,
                    model=model,
                    runtime_context=runtime_context,
                    messages=messages,
                    tools=provider_tools,
                    duration_ms=self._elapsed_ms(model_started_at),
                    error=exc,
                )
                provider_failure = classify_provider_failure(exc)
                if provider_failure is None:
                    raise
                return self._build_provider_failure_outcome(
                    task_input=task_input,
                    prompt=prompt,
                    failure_payload=build_provider_failure_payload(provider_failure),
                    tool_results=all_tool_results,
                    operations=operations,
                    llm_call_count=llm_call_count,
                    todo_state=current_todo_state,
                    operation_counters=operation_counters,
                )
            llm_call_count += 1
            await self._emit_model_call_progress(
                progress_sink=progress_sink,
                event_type="model.completed",
                turn_index=turn_index,
                model=self._model_name(generated, task_input),
                runtime_context=runtime_context,
                messages=messages,
                tools=provider_tools,
                duration_ms=self._elapsed_ms(model_started_at),
                generated=generated,
            )
            messages.append(generated.message)
            self._append_transcript_message(transcript_session_id, generated.message, finish_reason=generated.finish_reason)
            response_contract = self._response_contract_from_model_response(generated)
            progress_update = generated.progress_update if isinstance(generated.progress_update, dict) else response_contract.get("progressUpdate")
            if isinstance(progress_update, dict):
                await self._emit_model_progress_update(
                    progress_sink=progress_sink,
                    progress_update=progress_update,
                    turn_index=turn_index,
                    generated=generated,
                )
            visible_output_text = str(generated.visible_text or response_contract.get("text") or generated.output_text or "")
            operations.append(
                {
                    "key": self._next_operation_key(
                        operation_counters,
                        namespace="llm",
                        base_key="respond",
                    ),
                    "title": f"모델 응답 생성 {turn_index}",
                    "kind": "llm",
                    "status": "completed",
                    "summary": visible_output_text[:80] or self._progress_summary(progress_update) or f"tool_calls={len(generated.tool_calls)}",
                }
            )

            if not generated.tool_calls:
                final_text = visible_output_text
                return self._build_completed_outcome(
                    task_input=task_input,
                    prompt=prompt,
                    generated=generated,
                    final_text=final_text,
                    response_contract=response_contract,
                    tool_results=all_tool_results,
                    operations=operations,
                    llm_call_count=llm_call_count,
                    resume_payload=resume_payload,
                    todo_state=current_todo_state,
                    operation_counters=operation_counters,
                )

            delegate_boundary_started = False
            for tool_call_index, tool_call in enumerate(generated.tool_calls):
                runtime_tool_name = self._runtime_tool_name(tool_call.name, provider_tool_name_map)
                circuit_decision = None
                if delegate_boundary_started and runtime_tool_name != "delegate_task":
                    # worker 결과가 돌아온 뒤 같은 assistant 응답 안의 후속 실행 도구를 바로 돌리면
                    # "조사 worker 진행 중 -> 문서 작성" 순서가 뒤섞인다. provider tool_call 불변식은
                    # 지키되 실제 실행은 다음 모델 turn이 worker 결과를 읽고 다시 선택하게 미룬다.
                    for sibling_call in generated.tool_calls[tool_call_index:]:
                        sibling_runtime_name = self._runtime_tool_name(sibling_call.name, provider_tool_name_map)
                        sibling_result = {
                            "tool_call_id": sibling_call.id,
                            "name": sibling_runtime_name,
                            "args": sibling_call.arguments,
                            "result": self._deferred_tool_result_by_delegate(
                                delegate_tool_name="delegate_task",
                                deferred_tool_name=sibling_runtime_name,
                            ),
                        }
                        self._append_tool_result_observation(
                            tool_result=sibling_result,
                            all_tool_results=all_tool_results,
                            messages=messages,
                            transcript_session_id=transcript_session_id,
                            operations=operations,
                            operation_counters=operation_counters,
                        )
                    break
                guard_result = self.tool_guard.evaluate(
                    task_input=guard_task_input,
                    tool_call_id=tool_call.id,
                    tool_name=runtime_tool_name,
                    arguments=tool_call.arguments,
                )
                decision = self._guard_decision(guard_result)
                if decision == ToolGuardDecision.NEEDS_APPROVAL:
                    pending = {
                        "pending_tool_call_id": tool_call.id,
                        "pending_tool_name": runtime_tool_name,
                        "pending_tool_arguments": tool_call.arguments,
                        "transcript_session_id": transcript_session_id,
                        "approval_policy_result": self._guard_payload(guard_result),
                        "resume_decision": "pending",
                    }
                    for sibling_call in generated.tool_calls[tool_call_index + 1 :]:
                        sibling_runtime_name = self._runtime_tool_name(sibling_call.name, provider_tool_name_map)
                        sibling_result = {
                            "tool_call_id": sibling_call.id,
                            "name": sibling_runtime_name,
                            "args": sibling_call.arguments,
                            "result": self._deferred_tool_result(
                                pending_tool_call_id=tool_call.id,
                                pending_tool_name=runtime_tool_name,
                                deferred_tool_name=sibling_runtime_name,
                            ),
                        }
                        # approval 대기 때문에 이번 turn에서 실행하지 않은 sibling tool_call도
                        # tool result를 남겨 resume/replay 때 provider 입력 불변식이 깨지지 않게 한다.
                        self._append_tool_result_observation(
                            tool_result=sibling_result,
                            all_tool_results=all_tool_results,
                            messages=messages,
                            transcript_session_id=transcript_session_id,
                            operations=operations,
                            operation_counters=operation_counters,
                        )
                    current_todo_state = self._next_todo_state(current_todo_state, all_tool_results)
                    # 승인 대기는 실행 직전 tool action snapshot만 저장하고 StepRun/TaskRun을 WAITING으로 돌려준다.
                    outcome = self._build_waiting_outcome(
                        tool_results=all_tool_results,
                        operations=operations,
                        approval_reason=guard_result.reason or f"{runtime_tool_name} 실행 전 승인이 필요합니다",
                        llm_call_count=llm_call_count,
                        model_name=self._model_name(generated, task_input),
                        todo_state=current_todo_state,
                        operation_counters=operation_counters,
                    )
                    outcome["wait_payload"] = {**outcome.get("wait_payload", {}), **pending}
                    outcome["approval_payload"] = {**outcome.get("approval_payload", {}), **pending}
                    return outcome

                if decision == ToolGuardDecision.BLOCK:
                    # BLOCK도 전체 실패가 아니라 막힌 tool result로 transcript에 남겨 LLM이 다음 행동을 정한다.
                    result = self._blocked_tool_result(guard_result)
                else:
                    circuit_decision = failure_circuit.pre_call_decision(
                        tool_name=runtime_tool_name,
                        args=tool_call.arguments,
                    )
                    if circuit_decision.action == "block_with_synthetic_result" and circuit_decision.record is not None:
                        result = failure_circuit.build_blocked_result(record=circuit_decision.record)
                        failure_circuit.record_block(circuit_decision.record)
                    else:
                        await self._emit_tool_progress(
                            progress_sink=progress_sink,
                            event_type="tool.started",
                            tool_call_id=tool_call.id,
                            tool_name=runtime_tool_name,
                            args=tool_call.arguments,
                            result=None,
                        )
                        # PoC 단계 2: run_call이 동기 함수인데 내부에서 브릿지 위임 시
                        # 메인 이벤트 루프에 코루틴을 던지고 동기 차단으로 결과 대기 → 데드락.
                        # to_thread로 별도 스레드에 옮겨 메인 루프가 자유롭게 굴러가게 한다.
                        result = await asyncio.to_thread(
                            self._run_native_tool_call,
                            name=runtime_tool_name,
                            args=tool_call.arguments,
                            requested_toolsets=requested_toolsets,
                            tool_runtime=tool_runtime,
                        )
                        if runtime_tool_name == "delegate_task" and delegate_executor is not None:
                            result = await self._execute_delegate_tool_result(
                                delegate_executor=delegate_executor,
                                tool_call_id=tool_call.id,
                                args=tool_call.arguments,
                                accepted_result=result,
                            )
                            delegate_boundary_started = True
                        if runtime_tool_name == "session_agent_task" and session_agent_executor is not None:
                            result = await self._execute_session_agent_tool_result(
                                session_agent_executor=session_agent_executor,
                                tool_call_id=tool_call.id,
                                args=tool_call.arguments,
                                accepted_result=result,
                            )
                        failure_circuit.record_result(
                            tool_name=runtime_tool_name,
                            args=tool_call.arguments,
                            result=result,
                        )
                tool_result = {
                    "tool_call_id": tool_call.id,
                    "name": runtime_tool_name,
                    "args": tool_call.arguments,
                    "result": result,
                    "task_run_id": getattr(task, "id", None) or getattr(task, "task_run_id", None),
                }
                stored_tool_result = self._append_tool_result_observation(
                    tool_result=tool_result,
                    all_tool_results=all_tool_results,
                    messages=messages,
                    transcript_session_id=transcript_session_id,
                    operations=operations,
                    operation_counters=operation_counters,
                )
                await self._emit_tool_progress(
                    progress_sink=progress_sink,
                    event_type="tool.completed",
                    tool_call_id=tool_call.id,
                    tool_name=runtime_tool_name,
                    args=tool_call.arguments,
                    result=stored_tool_result.get("result"),
                )
                self._sync_dynamic_runtime_context(
                    task=task,
                    task_input=task_input,
                    tool_runtime=tool_runtime,
                )
                if (
                    decision != ToolGuardDecision.BLOCK
                    and circuit_decision is not None
                    and circuit_decision.action == "block_with_synthetic_result"
                    and circuit_decision.should_abort
                ):
                    self._append_circuit_deferred_siblings(
                        generated_tool_calls=generated.tool_calls,
                        start_index=tool_call_index + 1,
                        provider_tool_name_map=provider_tool_name_map,
                        all_tool_results=all_tool_results,
                        messages=messages,
                        transcript_session_id=transcript_session_id,
                        operations=operations,
                        operation_counters=operation_counters,
                    )
                    current_todo_state = self._next_todo_state(current_todo_state, all_tool_results)
                    return self._build_circuit_blocked_outcome(
                        task_input=task_input,
                        generated=generated,
                        tool_results=all_tool_results,
                        operations=operations,
                        llm_call_count=llm_call_count,
                        todo_state=current_todo_state,
                        operation_counters=operation_counters,
                        result=result,
                    )
            current_todo_state = self._next_todo_state(current_todo_state, all_tool_results)

        return self._build_failed_outcome(
            task_input=task_input,
            generated=generated,
            tool_results=all_tool_results,
            operations=operations,
            llm_call_count=llm_call_count,
            todo_state=current_todo_state,
            operation_counters=operation_counters,
            max_iterations=max_iterations,
        )

    def _new_turn_messages(
        self,
        *,
        task_input: dict[str, Any],
        prompt: str,
        replay_messages: list[AgentMessage | ToolResultMessage],
    ) -> list[AgentMessage]:
        """새 user turn에 필요한 provider message를 만든다.

        transcript replay가 이미 있으면 approval 재개나 tool_call continuation 상태이므로 공개 대화
        history를 다시 섞지 않는다. 새 공개 대화 턴에서는 product history를 참고 블록으로 낮추고,
        현재 turn 실행 지시는 별도 current_turn 블록으로 격리한다.
        """

        if replay_messages:
            return [AgentMessage(role="user", content=prompt)]
        history = task_input.get("conversation_history")
        if not isinstance(history, list) or not history:
            return [AgentMessage(role="user", content=prompt)]
        system_prompt_snapshot = self._optional_text(task_input.get("system_prompt_snapshot")) or ""
        return assemble_agent_loop_messages(
            system_prompt_snapshot=system_prompt_snapshot,
            conversation_history=[item for item in history if isinstance(item, dict)],
            current_user_prompt="",
            runtime_prompt_suffix=prompt,
        )

    @classmethod
    def _provider_tool_schemas(cls, available_tools: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        """provider가 허용하는 tool name으로 변환하고 runtime 이름으로 되돌릴 map을 만든다.

        일부 provider의 function name은 점(.)을 허용하지 않으므로, `terminal.run` 같은 runtime tool은
        provider 요청에서만 `terminal_run`으로 바꾼다. 내부 실행과 결과 표시는 원래 이름을 유지한다.
        """

        schemas: list[dict[str, Any]] = []
        name_map: dict[str, str] = {}
        used_names: set[str] = set()
        for tool in available_tools:
            schema = tool.get("schema")
            if isinstance(schema, dict):
                function_schema = dict(schema)
                runtime_name = str(function_schema.get("name") or "").strip()
                provider_name = cls._unique_provider_tool_name(runtime_name, used_names)
                used_names.add(provider_name)
                if provider_name != runtime_name:
                    description = str(function_schema.get("description") or "").strip()
                    suffix = f"Runtime tool name: {runtime_name}."
                    function_schema["description"] = f"{description}\n{suffix}" if description else suffix
                function_schema["name"] = provider_name
                name_map[provider_name] = runtime_name or provider_name
                schemas.append({"type": "function", "function": function_schema})
        return schemas, name_map

    @classmethod
    def _unique_provider_tool_name(cls, runtime_name: str, used_names: set[str]) -> str:
        base_name = cls._safe_provider_tool_name(runtime_name)
        if base_name not in used_names:
            return base_name
        next_index = 2
        while f"{base_name}_{next_index}" in used_names:
            next_index += 1
        return f"{base_name}_{next_index}"

    @staticmethod
    def _safe_provider_tool_name(runtime_name: str) -> str:
        safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(runtime_name or "").strip())
        safe_name = re.sub(r"_+", "_", safe_name).strip("_")
        return safe_name or "tool"

    @staticmethod
    def _runtime_tool_name(provider_tool_name: str, provider_tool_name_map: dict[str, str]) -> str:
        return provider_tool_name_map.get(provider_tool_name, provider_tool_name)

    @staticmethod
    def _provider_prompt_tools(available_tools: list[dict[str, Any]], provider_tool_name_map: dict[str, str]) -> list[dict[str, Any]]:
        runtime_to_provider_name = {runtime_name: provider_name for provider_name, runtime_name in provider_tool_name_map.items()}
        prompt_tools: list[dict[str, Any]] = []
        for tool in available_tools:
            item = dict(tool)
            runtime_name = str(item.get("name") or "").strip()
            provider_name = runtime_to_provider_name.get(runtime_name, runtime_name)
            if provider_name != runtime_name:
                summary = str(item.get("summary") or "").strip()
                item["summary"] = f"{summary} runtime name: {runtime_name}".strip()
            item["name"] = provider_name
            prompt_tools.append(item)
        return prompt_tools

    def _ensure_transcript_session(self, *, task, task_input: dict[str, Any], model: str) -> str | None:
        """transcript 저장소가 있으면 agent.loop 기록을 같은 세션에 묶는다."""

        if self.session_store is None:
            return None
        explicit_session_id = self._optional_text(task_input.get("transcript_session_id"))
        if explicit_session_id and self.session_store.get_session(explicit_session_id) is not None:
            # worker 실행은 parent session_key를 공유해도 transcript는 별도 agent_session을 사용한다.
            return explicit_session_id
        session_key = str(getattr(task, "session_key", "") or getattr(task, "task_run_id", "")).strip()
        if not session_key:
            return None
        latest = self.session_store.get_latest_session_by_key(session_key)
        if latest is not None:
            return str(latest["id"])
        session_id = new_id("session")
        self.session_store.create_session(
            session_id=session_id,
            session_key=session_key,
            source="agent.loop",
            user_id=getattr(task, "owner_key", None),
            model=model,
            title=str(getattr(task, "title", "") or task_input.get("prompt") or session_key)[:120],
            metadata={"task_run_id": getattr(task, "task_run_id", None)},
        )
        return session_id

    def _load_transcript_messages(self, session_id: str | None) -> list[AgentMessage | ToolResultMessage]:
        """저장된 transcript를 provider 재호출 입력으로 복원한다.

        resume/replay에서는 이전 assistant tool_calls와 tool result(tool 실행 결과를 모델에게 다시 넘기는 메시지)를
        같은 순서로 되살려야 provider가 대화 불변식을 유지할 수 있다.
        """

        if self.session_store is None or not session_id:
            return []

        messages: list[AgentMessage | ToolResultMessage] = []
        for row in self.session_store.list_messages(session_id):
            role = str(row.get("role") or "")
            if role == "tool":
                tool_call_id = str(row.get("tool_call_id") or "")
                if tool_call_id:
                    messages.append(ToolResultMessage(tool_call_id=tool_call_id, content=str(row.get("content") or "")))
                continue
            if role in {"system", "developer", "user", "assistant"}:
                messages.append(
                    AgentMessage(
                        role=role,
                        content=row.get("content"),
                        tool_calls=list(row.get("tool_calls") or []),
                        metadata=dict(row.get("metadata") or {}),
                    )
                )
        return self._order_tool_results_for_replay(messages)

    @staticmethod
    def _order_tool_results_for_replay(messages: list[AgentMessage | ToolResultMessage]) -> list[AgentMessage | ToolResultMessage]:
        """assistant tool_calls 뒤의 tool result 순서를 provider replay 규칙에 맞춘다.

        approval 대기 중에는 pending tool result가 resume 이후에 저장될 수 있다. DB 저장 시각은 늦더라도
        provider 입력은 assistant가 만든 tool_call 순서대로 재배치해야 function_call과 output 대응이 안정적이다.
        """

        ordered: list[AgentMessage | ToolResultMessage] = []
        index = 0
        while index < len(messages):
            message = messages[index]
            ordered.append(message)
            index += 1
            if not isinstance(message, AgentMessage) or message.role != "assistant" or not message.tool_calls:
                continue

            tool_messages: list[ToolResultMessage] = []
            while index < len(messages) and isinstance(messages[index], ToolResultMessage):
                tool_messages.append(messages[index])
                index += 1
            by_call_id = {tool_message.tool_call_id: tool_message for tool_message in tool_messages}
            emitted_ids: set[str] = set()
            for tool_call in message.tool_calls:
                tool_message = by_call_id.get(tool_call.id)
                if tool_message is not None:
                    ordered.append(tool_message)
                    emitted_ids.add(tool_message.tool_call_id)
            ordered.extend(tool_message for tool_message in tool_messages if tool_message.tool_call_id not in emitted_ids)
        return ordered

    def _append_transcript_message(
        self,
        session_id: str | None,
        message: AgentMessage | ToolResultMessage,
        *,
        tool_name: str | None = None,
        finish_reason: str | None = None,
    ) -> None:
        if self.session_store is None or not session_id:
            return

        tool_calls = [tool_call.model_dump(mode="json") for tool_call in message.tool_calls]
        self.session_store.append_message(
            session_id=session_id,
            role=message.role,
            content=self._message_content_text(message.content),
            tool_name=tool_name,
            tool_call_id=message.tool_call_id,
            tool_calls=tool_calls,
            finish_reason=finish_reason,
            metadata=message.metadata,
        )

    @staticmethod
    def _message_content_text(content: str | list[dict[str, Any]] | None) -> str | None:
        if content is None or isinstance(content, str):
            return content
        return json.dumps(content, ensure_ascii=False)

    def _run_native_tool_call(
        self,
        *,
        name: str,
        args: dict[str, Any],
        requested_toolsets: tuple[str, ...] | None,
        tool_runtime,
    ) -> dict[str, Any]:
        """이미 정규화된 native tool call 이름과 인자를 local runtime으로 넘긴다."""

        return tool_runtime.run_call(
            name=name,
            args=args,
            enabled_toolsets=requested_toolsets,
        )

    @staticmethod
    async def _execute_delegate_tool_result(
        *,
        delegate_executor,
        tool_call_id: str,
        args: dict[str, Any],
        accepted_result: dict[str, Any],
    ) -> dict[str, Any]:
        """delegate_task tool result 를 실제 worker 실행 결과로 바꾼다.

        runtime tool 은 우선 worker 계약(child_session)을 검증해서 반환한다. 여기서 바로
        worker 를 실행해야 parent LLM 이 결과를 본 다음 문서 작성/저장 같은 다음 도구를 판단할 수 있다.
        """

        if not isinstance(accepted_result, dict) or accepted_result.get("ok") is False:
            return accepted_result
        child_session = accepted_result.get("child_session")
        if not isinstance(child_session, dict):
            return accepted_result
        return await delegate_executor(
            child_session=dict(child_session),
            tool_call_id=tool_call_id,
            args=dict(args or {}),
            accepted_result=dict(accepted_result),
        )

    @staticmethod
    async def _execute_session_agent_tool_result(
        *,
        session_agent_executor,
        tool_call_id: str,
        args: dict[str, Any],
        accepted_result: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(accepted_result, dict) or accepted_result.get("ok") is False:
            return accepted_result
        child_work = accepted_result.get("child_work")
        if not isinstance(child_work, dict):
            return accepted_result
        if accepted_result.get("startExecution") is False:
            return accepted_result
        return await session_agent_executor(
            child_work=dict(child_work),
            tool_call_id=tool_call_id,
            args=dict(args or {}),
            accepted_result=dict(accepted_result),
        )

    async def _emit_tool_progress(
        self,
        *,
        progress_sink,
        event_type: str,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any] | None,
    ) -> None:
        if progress_sink is None:
            return

        await progress_sink(
            event_type=event_type,
            summary_message=self._tool_progress_summary(tool_name=tool_name, args=args, result=result),
            payload=self._tool_progress_payload(
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                args=args,
                result=result,
            ),
        )

    async def _emit_model_call_progress(
        self,
        *,
        progress_sink,
        event_type: str,
        turn_index: int,
        model: str,
        runtime_context: dict[str, Any],
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        duration_ms: int | None = None,
        generated: AgentModelResponse | None = None,
        error: BaseException | None = None,
    ) -> None:
        if progress_sink is None:
            return

        payload: dict[str, Any] = {
            "turnIndex": turn_index,
            "model": model,
            "providerName": str(runtime_context.get("provider_name") or runtime_context.get("providerName") or ""),
            "messageCount": len(messages),
            "toolSchemaCount": len(tools or []),
        }
        if duration_ms is not None:
            payload["durationMs"] = duration_ms
        if generated is not None:
            payload.update(
                {
                    "finishReason": generated.finish_reason,
                    "toolCallCount": len(generated.tool_calls),
                    "outputTextLength": len(str(generated.output_text or "")),
                    "visibleTextLength": len(str(generated.visible_text or "")),
                    "usage": dict(generated.usage or {}),
                }
            )
        if error is not None:
            payload["error"] = {
                "type": type(error).__name__,
                "message": str(error)[:500],
            }

        await progress_sink(
            event_type=event_type,
            summary_message=self._model_progress_summary(
                event_type=event_type,
                turn_index=turn_index,
                duration_ms=duration_ms,
                generated=generated,
            ),
            payload=payload,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _model_progress_summary(
        *,
        event_type: str,
        turn_index: int,
        duration_ms: int | None,
        generated: AgentModelResponse | None,
    ) -> str:
        if event_type == "model.started":
            return f"모델 응답 생성 {turn_index} 시작"
        if event_type == "model.failed":
            return f"모델 응답 생성 {turn_index} 실패"
        suffix = f" ({duration_ms}ms)" if duration_ms is not None else ""
        if generated is not None and generated.tool_calls:
            return f"모델 응답 생성 {turn_index} 완료: tool_calls={len(generated.tool_calls)}{suffix}"
        return f"모델 응답 생성 {turn_index} 완료{suffix}"

    @classmethod
    def _tool_progress_summary(cls, *, tool_name: str, args: dict[str, Any], result: dict[str, Any] | None) -> str:
        if tool_name == "todo":
            active_title = cls._active_todo_title(args.get("todos"))
            if active_title:
                return active_title
        if tool_name == "write_file":
            path = cls._optional_text(args.get("path")) or cls._optional_text((result or {}).get("path"))
            return f"{path} 파일 작성" if path else "파일 작성"
        if tool_name == "read_file":
            path = cls._optional_text(args.get("path")) or cls._optional_text((result or {}).get("path"))
            return f"{path} 파일 읽기" if path else "파일 읽기"
        if tool_name == "search_files":
            query = cls._optional_text(args.get("query")) or cls._optional_text(args.get("pattern"))
            return f"{query} 검색" if query else "파일 검색"
        if tool_name == "terminal.run":
            command = cls._terminal_command_summary(args)
            return f"{command} 실행" if command else "터미널 실행"
        if tool_name == "delegate_task":
            delegate = (result or {}).get("delegate") if isinstance(result, dict) else None
            summary = cls._optional_text((delegate or {}).get("summary")) if isinstance(delegate, dict) else None
            goal = cls._optional_text(args.get("goal"))
            if summary:
                return f"worker 결과 회수: {summary[:80]}"
            return f"{goal} worker 실행" if goal else "worker 실행"
        return f"{tool_name} 실행"

    @classmethod
    def _tool_progress_payload(
        cls,
        *,
        tool_call_id: str,
        tool_name: str,
        args: dict[str, Any],
        result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "tool_call_id": tool_call_id,
            "toolCallId": tool_call_id,
            "tool_name": tool_name,
            "toolName": tool_name,
            "title": cls._tool_progress_summary(tool_name=tool_name, args=args, result=result),
            "input": cls._compact_progress_value(args),
        }
        for key in ("path", "query", "pattern"):
            value = cls._optional_text(args.get(key)) or cls._optional_text((result or {}).get(key))
            if value:
                payload[key] = value
        if tool_name == "todo":
            todos = [item for item in args.get("todos") or [] if isinstance(item, dict)]
            payload["todos"] = [
                {
                    "id": cls._optional_text(item.get("id") or item.get("key")),
                    "content": cls._optional_text(item.get("content") or item.get("title")),
                    "status": cls._optional_text(item.get("status")),
                }
                for item in todos[:12]
            ]
        if isinstance(result, dict):
            payload["result"] = cls._compact_progress_value(result)
            if result.get("ok") is False:
                payload["ok"] = False
                error = result.get("error")
                if isinstance(error, dict):
                    payload["error"] = {
                        "code": cls._optional_text(error.get("code")),
                        "message": cls._optional_text(error.get("message")),
                    }
            for key in ("bytes_written", "lines_written", "returncode", "total_count"):
                value = result.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    payload[key] = value
        return payload

    @classmethod
    def _compact_progress_value(cls, value: Any, *, depth: int = 0) -> Any:
        """세부 기록용 tool 입출력을 너무 커지지 않게 줄이고 민감값은 가린다."""

        if depth >= 5:
            return "..."
        if isinstance(value, dict):
            compacted: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 40:
                    compacted["..."] = "truncated"
                    break
                key_text = str(key)
                if cls._looks_sensitive_key(key_text):
                    compacted[key_text] = "[redacted]"
                else:
                    compacted[key_text] = cls._compact_progress_value(item, depth=depth + 1)
            return compacted
        if isinstance(value, list):
            compacted_items = [cls._compact_progress_value(item, depth=depth + 1) for item in value[:20]]
            if len(value) > 20:
                compacted_items.append("...")
            return compacted_items
        if isinstance(value, str):
            return cls._redact_progress_text(value[:4000] + ("..." if len(value) > 4000 else ""))
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return cls._redact_progress_text(str(value))

    @staticmethod
    def _looks_sensitive_key(key: str) -> bool:
        return bool(re.search(r"(?i)(api[_-]?key|access[_-]?token|refresh[_-]?token|secret|password|authorization)", key))

    @staticmethod
    def _redact_progress_text(value: str) -> str:
        redacted = re.sub(r"sk-[A-Za-z0-9_-]{10,}", "[redacted]", value)
        redacted = re.sub(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [redacted]", redacted)
        return re.sub(
            r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*[^,\s]+",
            r"\1=[redacted]",
            redacted,
        )

    @classmethod
    def _active_todo_title(cls, value: Any) -> str | None:
        if not isinstance(value, list):
            return None
        for status in ("in_progress", "pending", "completed"):
            for item in value:
                if not isinstance(item, dict):
                    continue
                if str(item.get("status") or "").strip().lower() != status:
                    continue
                title = cls._optional_text(item.get("content") or item.get("title"))
                if title:
                    return title
        return None

    @classmethod
    def _terminal_command_summary(cls, args: dict[str, Any]) -> str | None:
        argv = args.get("argv")
        if isinstance(argv, list) and argv:
            text = " ".join(str(item) for item in argv[:4])
            return text[:80]
        return cls._optional_text(args.get("command"))

    def _bind_request_tool_runtime(self, *, workspace_root: Any, owner_key: Any, runtime_context: dict[str, Any] | None = None):
        context_binder = getattr(self.tool_runtime, "bind_request_context", None)
        if callable(context_binder):
            return context_binder(workspace_root=workspace_root, owner_key=owner_key, runtime_context=runtime_context)
        binder = getattr(self.tool_runtime, "bind_workspace_root", None)
        if callable(binder):
            return binder(workspace_root)
        return self.tool_runtime

    @staticmethod
    def _sync_dynamic_runtime_context(*, task, task_input: dict[str, Any], tool_runtime) -> None:
        runtime_context = getattr(tool_runtime, "runtime_context", None)
        dynamic_keys = (
            "workId",
            "workIdentifier",
            "workTitle",
            "workAssigneeAgentId",
            "workContext",
            "workLinkReason",
        )
        if isinstance(runtime_context, dict):
            # session_agent_task처럼 도구 실행 중 새로 연결된 work context는 tool runtime에 먼저 생긴다.
            # 이 값을 TaskRun input에도 즉시 반영해야 이후 loop와 최종 WorkService 처리에서
            # 같은 parent work/run 관계를 잃지 않는다.
            runtime_updates = {
                key: runtime_context[key]
                for key in dynamic_keys
                if key in runtime_context and task_input.get(key) != runtime_context[key]
            }
            if runtime_updates:
                task_input.update(runtime_updates)
                latest_input = dict(getattr(task, "input_payload", None) or {})
                latest_input.update(runtime_updates)
                task.input_payload = latest_input

        latest_input = dict(getattr(task, "input_payload", None) or {})
        updates = {
            key: latest_input[key]
            for key in dynamic_keys
            if key in latest_input and task_input.get(key) != latest_input[key]
        }
        if not updates:
            return
        task_input.update(updates)
        if isinstance(runtime_context, dict):
            runtime_context.update(updates)

    @staticmethod
    def _task_input_for_guard(*, task_input: dict[str, Any], step, resume_payload: dict[str, Any] | None) -> dict[str, Any]:
        guard_input = dict(task_input)
        if not bool((resume_payload or {}).get("approved", False)) or step is None:
            return guard_input

        pending_payload = dict(getattr(step, "wait_payload", None) or {})
        approval_policy = dict(pending_payload.get("approval_policy_result") or {})
        if approval_policy.get("source") != "legacy_input_payload":
            return guard_input

        # 승인된 resume 문맥은 같은 TaskRun(사용자 요청 전체 실행)의 전역 approval_required 재차단만 피하게 한다.
        # tool별 위험 정책은 별도 guard 판단으로 계속 적용될 수 있도록 원본 입력은 보존하고 내부 marker만 덧붙인다.
        guard_input["_approved_resume_context"] = {
            "approved": True,
            "source": approval_policy.get("source"),
            "pending_tool_call_id": pending_payload.get("pending_tool_call_id"),
            "pending_tool_name": pending_payload.get("pending_tool_name"),
        }
        return guard_input

    def _resolve_pending_tool_after_resume(
        self,
        *,
        step,
        resume_payload: dict[str, Any],
        requested_toolsets: tuple[str, ...] | None,
        tool_runtime,
    ) -> dict[str, Any] | None:
        """승인 재개 응답에 따라 저장해 둔 pending tool call의 결과를 먼저 만든다.

        이렇게 해야 승인 전 assistant가 만든 tool_call_id(도구 호출 식별자)에 정확히 대응하는
        ToolResultMessage를 transcript에 붙이고, 같은 도구를 모델에게 다시 고르게 만들지 않는다.
        """

        if step is None:
            return None
        pending_payload = dict(getattr(step, "wait_payload", None) or {})
        call_id = str(pending_payload.get("pending_tool_call_id") or "").strip()
        tool_name = str(pending_payload.get("pending_tool_name") or "").strip()
        args = pending_payload.get("pending_tool_arguments")
        if not call_id or not tool_name or not isinstance(args, dict):
            return None
        if bool(resume_payload.get("approved", False)):
            # PoC 단계 2 메모: 이 경로는 approval resume용. 동기 함수 안이라 to_thread 못 씀.
            # 브릿지 위임이 필요하면 함수 시그니처를 async로 바꾸거나 별도 처리 필요.
            result = self._run_native_tool_call(
                name=tool_name,
                args=args,
                requested_toolsets=requested_toolsets,
                tool_runtime=tool_runtime,
            )
        else:
            # 거절된 approval도 원래 tool_call_id에 대한 tool result를 남겨 provider replay 불변식을 맞춘다.
            reason = str(resume_payload.get("reason") or resume_payload.get("message") or "사용자가 도구 실행을 거절했습니다")
            guard_payload = dict(pending_payload.get("approval_policy_result") or {})
            result = self._blocked_tool_result(
                ToolGuardResult(
                    decision=ToolGuardDecision.BLOCK,
                    reason=reason,
                    payload={**guard_payload, "resume_decision": "rejected"},
                )
            )
        return {
            "tool_call_id": call_id,
            "name": tool_name,
            "args": args,
            "result": result,
        }

    def _append_tool_result_observation(
        self,
        *,
        tool_result: dict[str, Any],
        all_tool_results: list[dict[str, Any]],
        messages: list[AgentMessage | ToolResultMessage],
        transcript_session_id: str | None,
        operations: list[dict[str, Any]],
        operation_counters: dict[str, int],
    ) -> dict[str, Any]:
        tool_name = str(tool_result["name"])
        result = tool_result["result"]
        observed_result = self._tool_result_model_observation_result(
            result,
            tool_name=tool_name,
            tool_call_id=str(tool_result["tool_call_id"]),
            task_run_id=str(tool_result.get("task_run_id") or "") or None,
        )
        stored_tool_result = {
            **tool_result,
            "result": observed_result,
        }
        stored_tool_result.pop("task_run_id", None)
        all_tool_results.append(stored_tool_result)
        tool_message = ToolResultMessage(
            tool_call_id=str(tool_result["tool_call_id"]),
            content=self._tool_result_content(observed_result),
        )
        messages.append(tool_message)
        self._append_transcript_message(transcript_session_id, tool_message, tool_name=tool_name)
        # tool_call_id는 assistant가 보낸 호출 id와 정확히 맞아야 replay 시 결과를 대응시킬 수 있다.
        operation = {
            "key": self._next_operation_key(
                operation_counters,
                namespace="tool",
                base_key=tool_name,
            ),
            "title": tool_name,
            "kind": "tool",
            "status": self._tool_operation_status(result),
            "summary": self._tool_summary(result),
        }
        operation_error = self._tool_operation_error(result)
        if operation_error is not None:
            operation["error"] = operation_error
        operations.append(operation)
        return stored_tool_result

    @staticmethod
    def _guard_decision(guard_result: ToolGuardResult) -> ToolGuardDecision:
        decision = guard_result.decision
        if isinstance(decision, ToolGuardDecision):
            return decision
        return ToolGuardDecision(str(decision))

    def _respond_with_runtime_context(
        self,
        *,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None,
        runtime_context: dict[str, Any],
    ):
        provider = self._provider_for_runtime_context(runtime_context)
        signature = inspect.signature(provider.respond)
        if "runtime_context" in signature.parameters:
            return provider.respond(
                messages=messages,
                tools=tools,
                model=model,
                tool_choice=tool_choice,
                runtime_context=runtime_context,
            )
        return provider.respond(
            messages=messages,
            tools=tools,
            model=model,
            tool_choice=tool_choice,
        )

    async def _respond_with_runtime_context_async(
        self,
        *,
        messages: list[AgentMessage | ToolResultMessage | dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        model: str,
        tool_choice: dict[str, Any] | str | None,
        runtime_context: dict[str, Any],
    ):
        provider = self._provider_for_runtime_context(runtime_context)
        respond_async = getattr(provider, "respond_async", None)
        if callable(respond_async):
            signature = inspect.signature(respond_async)
            if "runtime_context" in signature.parameters:
                return await respond_async(
                    messages=messages,
                    tools=tools,
                    model=model,
                    tool_choice=tool_choice,
                    runtime_context=runtime_context,
                )
            return await respond_async(
                messages=messages,
                tools=tools,
                model=model,
                tool_choice=tool_choice,
            )
        return await asyncio.to_thread(
            self._respond_with_runtime_context,
            messages=messages,
            tools=tools,
            model=model,
            tool_choice=tool_choice,
            runtime_context=runtime_context,
        )

    def _provider_for_runtime_context(self, runtime_context: dict[str, Any]):
        if self.provider_registry is None:
            return self.provider
        provider_name = runtime_context.get("provider_name") or runtime_context.get("providerName")
        return self.provider_registry.model_provider_for(provider_name)

    @staticmethod
    def _model_runtime_context(*, task, step, task_input: dict[str, Any]) -> dict[str, Any]:
        return {
            "user_id": getattr(task, "owner_key", None),
            "provider_name": task_input.get("provider_name")
            or task_input.get("providerName")
            or "openai_api_key",
            "task_run_id": getattr(task, "task_run_id", None),
            "step_run_id": getattr(step, "step_run_id", None),
            "session_id": getattr(task, "session_key", None)
            or task_input.get("session_id")
            or task_input.get("sessionId"),
        }

    @staticmethod
    def _guard_payload(guard_result: ToolGuardResult) -> dict[str, Any]:
        if hasattr(guard_result, "to_payload"):
            return guard_result.to_payload()
        return {
            **dict(getattr(guard_result, "payload", {}) or {}),
            "decision": str(getattr(guard_result, "decision", "")),
            "reason": getattr(guard_result, "reason", None),
        }

    def _blocked_tool_result(self, guard_result: ToolGuardResult) -> dict[str, Any]:
        guard_payload = self._guard_payload(guard_result)
        reason = str(guard_payload.get("reason") or "tool call blocked")
        return {
            "ok": False,
            "content": f"Tool call blocked: {reason}",
            "error": {
                "code": "tool_blocked",
                "message": reason,
            },
            "guard": guard_payload,
        }

    @staticmethod
    def _deferred_tool_result(
        *,
        pending_tool_call_id: str,
        pending_tool_name: str,
        deferred_tool_name: str,
    ) -> dict[str, Any]:
        message = (
            f"{pending_tool_name} 승인이 대기 중이라 {deferred_tool_name} 호출은 이번 turn에서 실행하지 않았습니다. "
            "승인 이후에도 필요하면 모델이 다시 요청해야 합니다."
        )
        return {
            "ok": False,
            "content": message,
            "error": {
                "code": "tool_deferred_by_approval",
                "message": message,
            },
            "guard": {
                "decision": "DEFERRED_BY_APPROVAL",
                "pending_tool_call_id": pending_tool_call_id,
                "pending_tool_name": pending_tool_name,
            },
        }

    @staticmethod
    def _deferred_tool_result_by_delegate(
        *,
        delegate_tool_name: str,
        deferred_tool_name: str,
    ) -> dict[str, Any]:
        message = (
            f"{delegate_tool_name} worker 결과를 먼저 반영해야 해서 {deferred_tool_name} 호출은 이번 turn에서 실행하지 않았습니다. "
            "worker 결과를 읽은 뒤에도 필요하면 다음 turn에서 다시 요청해야 합니다."
        )
        return {
            "ok": False,
            "content": message,
            "error": {
                "code": "tool_deferred_by_delegate_boundary",
                "message": message,
            },
            "guard": {
                "decision": "DEFERRED_BY_DELEGATE_BOUNDARY",
                "pending_tool_name": delegate_tool_name,
            },
        }

    @staticmethod
    def _deferred_tool_result_by_circuit(*, deferred_tool_name: str) -> dict[str, Any]:
        message = f"{deferred_tool_name} 실행은 같은 assistant 응답에서 이전 도구가 circuit breaker로 중단되어 보류됐습니다."
        payload = {"error": {"code": "tool_deferred_by_circuit_breaker", "message": message}}
        return {
            "ok": False,
            "content": json.dumps(payload, ensure_ascii=False),
            "error": {
                "code": "tool_deferred_by_circuit_breaker",
                "message": message,
                "tool_name": deferred_tool_name,
                "retryable": False,
            },
            "circuit_breaker": {
                "scope": "run",
                "blocked": True,
            },
        }

    def _append_circuit_deferred_siblings(
        self,
        *,
        generated_tool_calls,
        start_index: int,
        provider_tool_name_map: dict[str, str],
        all_tool_results: list[dict[str, Any]],
        messages: list[AgentMessage | ToolResultMessage],
        transcript_session_id: str | None,
        operations: list[dict[str, Any]],
        operation_counters: dict[str, int],
    ) -> None:
        for sibling_call in generated_tool_calls[start_index:]:
            sibling_runtime_name = self._runtime_tool_name(sibling_call.name, provider_tool_name_map)
            sibling_result = {
                "tool_call_id": sibling_call.id,
                "name": sibling_runtime_name,
                "args": sibling_call.arguments,
                "result": self._deferred_tool_result_by_circuit(deferred_tool_name=sibling_runtime_name),
            }
            self._append_tool_result_observation(
                tool_result=sibling_result,
                all_tool_results=all_tool_results,
                messages=messages,
                transcript_session_id=transcript_session_id,
                operations=operations,
                operation_counters=operation_counters,
            )

    @staticmethod
    def _tool_result_content(result: Any) -> str:
        try:
            return json.dumps(result, ensure_ascii=False, default=str)
        except TypeError:
            return json.dumps(str(result), ensure_ascii=False)

    def _tool_result_model_observation_result(
        self,
        result: Any,
        *,
        tool_name: str,
        tool_call_id: str,
        task_run_id: str | None,
    ) -> dict[str, Any]:
        """큰 tool 원문은 별도 저장소로 빼고, 모델/DB에는 bounded observation만 남긴다."""

        raw_text = self._stable_json(result)
        if len(raw_text) <= self.TOOL_RESULT_INLINE_MAX_CHARS:
            if isinstance(result, dict):
                return result
            return {"ok": True, "content": str(result)}

        raw_meta = store_raw_tool_result(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            task_run_id=task_run_id,
            result=result,
        )
        preview, preview_meta = self._preview_tool_result_value(result)
        observation = {
            "ok": self._tool_result_ok_value(result),
            "content": (
                "[...truncated tool result: "
                f"kept preview of {raw_meta['raw_chars']} chars. "
                "Use tool_result.read with raw_ref, or call the tool again with narrower parameters, "
                "if the preview is insufficient.]"
            ),
            "observation_type": "tool_result_preview",
            "tool_name": tool_name,
            "truncated": True,
            "raw_ref": raw_meta["raw_ref"],
            "raw_chars": raw_meta["raw_chars"],
            "expires_at": raw_meta["expires_at"],
            "preview": preview,
            "preview_meta": preview_meta,
        }
        return self._cap_observation_result(observation)

    def _preview_tool_result_value(self, value: Any) -> tuple[Any, dict[str, Any]]:
        large_arrays: list[dict[str, Any]] = []
        preview = self._preview_value(value, path="$", large_arrays=large_arrays, depth=0)
        return preview, {
            "large_arrays": large_arrays[:20],
            "preview_chars": len(self._stable_json(preview)),
            "array_sample_size": self.TOOL_RESULT_ARRAY_SAMPLE_SIZE,
        }

    def _preview_value(self, value: Any, *, path: str, large_arrays: list[dict[str, Any]], depth: int) -> Any:
        if depth >= 6:
            return self._preview_leaf(value)
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for index, (key, item) in enumerate(value.items()):
                if index >= 30:
                    result["..."] = f"{len(value) - index} more keys omitted"
                    break
                child_path = f"{path}.{key}" if path else str(key)
                result[str(key)] = self._preview_value(item, path=child_path, large_arrays=large_arrays, depth=depth + 1)
            return result
        if isinstance(value, list):
            if len(value) > self.TOOL_RESULT_ARRAY_SAMPLE_SIZE:
                large_arrays.append(
                    {
                        "path": path,
                        "count": len(value),
                        "sample_count": self.TOOL_RESULT_ARRAY_SAMPLE_SIZE,
                    }
                )
            sample = [
                self._preview_value(item, path=f"{path}[{index}]", large_arrays=large_arrays, depth=depth + 1)
                for index, item in enumerate(value[: self.TOOL_RESULT_ARRAY_SAMPLE_SIZE])
            ]
            if len(value) > self.TOOL_RESULT_ARRAY_SAMPLE_SIZE:
                sample.append(f"... {len(value) - self.TOOL_RESULT_ARRAY_SAMPLE_SIZE} more items omitted")
            return sample
        return self._preview_leaf(value)

    @staticmethod
    def _preview_leaf(value: Any) -> Any:
        if isinstance(value, str) and len(value) > 1_000:
            return value[:1_000] + f"\n...[truncated string: kept 1000 of {len(value)} chars]..."
        return value

    def _cap_observation_result(self, observation: dict[str, Any]) -> dict[str, Any]:
        rendered = self._stable_json(observation)
        if len(rendered) <= self.TOOL_RESULT_OBSERVATION_MAX_CHARS:
            return observation
        capped = {
            **observation,
            "preview": self._stable_json(observation.get("preview"))[: self.TOOL_RESULT_PREVIEW_MAX_CHARS]
            + "\n...[truncated preview]...",
            "preview_meta": {
                **dict(observation.get("preview_meta") or {}),
                "observation_capped": True,
                "observation_chars_before_cap": len(rendered),
            },
        }
        if len(self._stable_json(capped)) <= self.TOOL_RESULT_OBSERVATION_MAX_CHARS:
            return capped
        capped["preview"] = "[preview omitted because the tool result shape is too large; use raw_ref with a narrow offset/limit.]"
        return capped

    @staticmethod
    def _tool_result_ok_value(result: Any) -> bool:
        if isinstance(result, dict) and isinstance(result.get("ok"), bool):
            return bool(result["ok"])
        return True

    @staticmethod
    def _stable_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        except TypeError:
            return json.dumps(str(value), ensure_ascii=False)

    def _build_completed_outcome(
        self,
        *,
        task_input: dict[str, Any],
        prompt: str,
        generated,
        final_text: str,
        response_contract: dict[str, Any] | None,
        tool_results: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        llm_call_count: int,
        resume_payload: dict[str, Any] | None,
        todo_state: dict[str, Any],
        operation_counters: dict[str, int],
    ) -> dict[str, Any]:
        """agent.loop 실행 결과를 TaskRun/StepRun 저장 형식에 맞춰 모은다."""

        provider_name = generated.provider_name if generated is not None else self.provider.name
        metadata = dict(generated.metadata or {}) if generated is not None else {}
        usage = dict(generated.usage or {}) if generated is not None else {}
        model_name = self._model_name(generated, task_input)
        tool_names = [str(item["name"]) for item in tool_results]
        result_payload = {
            "provider_name": provider_name,
            "text": final_text,
            "metadata": metadata,
            "tool_results": tool_results,
        }
        work_disposition = self._work_disposition_from_response_contract(response_contract)
        if work_disposition is None:
            work_disposition = self._parent_work_disposition_from_tool_results(tool_results)
        if work_disposition is not None:
            result_payload["workDisposition"] = work_disposition
        output_payload = {
            "prompt": prompt,
            "text": final_text,
            "usage": usage,
            "tool_results": tool_results,
            "approval_response": resume_payload or {},
        }
        detail_json = self._build_detail_json(
            tool_names=tool_names,
            llm_call_count=llm_call_count,
            model_name=model_name,
            todo_state=todo_state,
        )
        delegate_agent_detail = self._delegate_agent_detail_from_tool_results(tool_results)
        if delegate_agent_detail is not None:
            # worker 실행은 tool 호출 중간에 이미 StepRun detail 에 반영되지만,
            # 최종 handler detail_json 이 agentDetail 기본값으로 덮어쓰지 않도록 같은 정보를 다시 싣는다.
            detail_json["agentDetail"] = delegate_agent_detail
        session_agent_detail = self._session_agent_detail_from_tool_results(tool_results)
        if session_agent_detail is not None:
            detail_json["agentDetail"] = {
                **dict(detail_json.get("agentDetail") or {}),
                **session_agent_detail,
            }
        if resume_payload is not None:
            operations.append(
                {
                    "key": self._next_operation_key(
                        operation_counters,
                        namespace="approval",
                        base_key="resume",
                    ),
                    "title": "승인 후 재개",
                    "kind": "approval",
                    "status": "completed",
                    "summary": json.dumps(resume_payload, ensure_ascii=False),
                }
            )
        outcome = {
            "task_status": TaskStatus.COMPLETED,
            "step_status": StepStatus.COMPLETED,
            "result_payload": result_payload,
            "output_payload": output_payload,
            "detail_json": detail_json,
            "todo_state": todo_state,
            "observed_steps": [],
            "summary_message": self._progress_summary(response_contract.get("progressUpdate")) or final_text[:120] or "agent loop completed",
            "operations": operations,
        }
        child_session = self._child_session_from_tool_results(tool_results)
        if child_session is not None:
            # delegate_task는 runtime tool result로 관찰되지만 실제 worker 실행은 TaskEngine이
            # parent StepRun에 worker agent_session linkage를 만든 뒤 처리해야 한다.
            outcome["child_session"] = child_session
        return outcome

    def _build_waiting_outcome(
        self,
        *,
        tool_results: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        approval_reason: str,
        llm_call_count: int,
        model_name: str | None,
        todo_state: dict[str, Any],
        operation_counters: dict[str, int],
    ) -> dict[str, Any]:
        """approval 대기 상태를 TaskRun/StepRun 저장 형식으로 만든다."""

        tool_names = [str(item["name"]) for item in tool_results]
        return {
            "task_status": TaskStatus.WAITING,
            "step_status": StepStatus.WAITING,
            "output_payload": {
                "tool_results": tool_results,
            },
            "wait_payload": {
                "reason": "approval_required",
                "approvalReason": approval_reason,
            },
            "detail_json": self._build_detail_json(
                tool_names=tool_names,
                llm_call_count=llm_call_count,
                model_name=model_name,
                todo_state=todo_state,
            ),
            "todo_state": todo_state,
            "observed_steps": [],
            "summary_message": "approval required",
            "approval_payload": {
                "reason": approval_reason,
                "tool_results": tool_results,
            },
            "operations": [
                *operations,
                {
                    "key": self._next_operation_key(
                        operation_counters,
                        namespace="approval",
                        base_key="request",
                    ),
                    "title": "사용자 승인 요청",
                    "kind": "approval",
                    "status": "waiting",
                    "summary": approval_reason,
                },
            ],
        }

    def _build_failed_outcome(
        self,
        *,
        task_input: dict[str, Any],
        generated: AgentModelResponse | None,
        tool_results: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        llm_call_count: int,
        todo_state: dict[str, Any],
        operation_counters: dict[str, int],
        max_iterations: int,
    ) -> dict[str, Any]:
        tool_names = [str(item["name"]) for item in tool_results]
        message = f"작업 반복 한도({max_iterations})에 도달했습니다."
        return {
            "task_status": TaskStatus.FAILED,
            "step_status": StepStatus.FAILED,
            "result_payload": {
                "text": generated.output_text if generated is not None and generated.output_text else message,
                "tool_results": tool_results,
                "error": {
                    "code": "max_iterations_exceeded",
                    "maxIterations": max_iterations,
                },
            },
            "output_payload": {
                "tool_results": tool_results,
            },
            "detail_json": self._build_detail_json(
                tool_names=tool_names,
                llm_call_count=llm_call_count,
                model_name=self._model_name(generated, task_input) if generated is not None else None,
                todo_state=todo_state,
            ),
            "todo_state": todo_state,
            "observed_steps": [],
            "summary_message": message,
            "error_message": message,
            "operations": [
                *operations,
                {
                    "key": self._next_operation_key(
                        operation_counters,
                        namespace="loop",
                        base_key="max_iterations",
                    ),
                    "title": "반복 한도 도달",
                    "kind": "system",
                    "status": "failed",
                    "summary": message,
                },
            ],
        }

    def _build_circuit_blocked_outcome(
        self,
        *,
        task_input: dict[str, Any],
        generated: AgentModelResponse | None,
        tool_results: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        llm_call_count: int,
        todo_state: dict[str, Any],
        operation_counters: dict[str, int],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        tool_names = [str(item["name"]) for item in tool_results]
        operation_error = self._tool_operation_error(result) or {
            "code": "tool_failure_blocked",
            "message": "반복 도구 실패가 차단되었습니다.",
        }
        failure_type = str(operation_error.get("type") or "")
        code = "rate_limited_blocked" if failure_type == "rate_limited" else "tool_failure_blocked"
        message = str(operation_error.get("message") or "반복 도구 실패가 차단되었습니다.")
        result_error = {**operation_error, "code": code}
        return {
            "task_status": TaskStatus.FAILED,
            "step_status": StepStatus.FAILED,
            "result_payload": {
                "text": generated.output_text if generated is not None and generated.output_text else message,
                "tool_results": tool_results,
                "error": result_error,
            },
            "output_payload": {
                "tool_results": tool_results,
            },
            "detail_json": self._build_detail_json(
                tool_names=tool_names,
                llm_call_count=llm_call_count,
                model_name=self._model_name(generated, task_input) if generated is not None else None,
                todo_state=todo_state,
            ),
            "todo_state": todo_state,
            "observed_steps": [],
            "summary_message": message,
            "error_message": message,
            "operations": [
                *operations,
                {
                    "key": self._next_operation_key(
                        operation_counters,
                        namespace="loop",
                        base_key="tool_circuit",
                    ),
                    "title": "반복 도구 실패 차단",
                    "kind": "system",
                    "status": "failed",
                    "summary": message,
                    "error": result_error,
                },
            ],
        }

    def _build_provider_failure_outcome(
        self,
        *,
        task_input: dict[str, Any],
        prompt: str,
        failure_payload: dict[str, Any],
        tool_results: list[dict[str, Any]],
        operations: list[dict[str, Any]],
        llm_call_count: int,
        todo_state: dict[str, Any],
        operation_counters: dict[str, int],
    ) -> dict[str, Any]:
        message = str(failure_payload.get("message") or "모델 provider 호출이 실패했습니다.")
        code = str(failure_payload.get("code") or "provider_call_failed")
        return {
            "task_status": TaskStatus.FAILED,
            "step_status": StepStatus.FAILED,
            "result_payload": {
                "text": message,
                "tool_results": tool_results,
                "error": failure_payload,
            },
            "output_payload": {
                "prompt": prompt,
                "tool_results": tool_results,
            },
            "detail_json": self._build_detail_json(
                tool_names=[str(item["name"]) for item in tool_results],
                llm_call_count=llm_call_count,
                model_name=None,
                todo_state=todo_state,
            ),
            "todo_state": todo_state,
            "observed_steps": [],
            "summary_message": message,
            "error_message": message,
            "operations": [
                *operations,
                {
                    "key": self._next_operation_key(
                        operation_counters,
                        namespace="provider",
                        base_key=code,
                    ),
                    "title": "모델 provider 호출 실패",
                    "kind": "llm",
                    "status": "failed",
                    "summary": message,
                    "error": failure_payload,
                },
            ],
        }

    @staticmethod
    def _requested_toolsets(task_input: dict[str, Any]) -> tuple[str, ...] | None:
        raw_toolsets = task_input.get("enabled_toolsets")
        if not isinstance(raw_toolsets, list):
            if ToolCallingLoopHandler._is_worker_payload(task_input):
                return ("skills", "terminal", "file", "web")
            return None
        normalized = tuple(str(item).strip() for item in raw_toolsets if str(item).strip())
        if ToolCallingLoopHandler._is_worker_payload(task_input):
            # worker는 depth1 leaf 실행 단위다. parent가 준 toolset에 실수로 delegation/all이 섞여도
            # 하위 worker를 다시 만들 수 없게 실행 가능한 toolset만 남긴다.
            worker_toolsets = tuple(
                item
                for item in normalized
                if item not in {"all", "*", "delegate", "delegation", "delegate_task"}
            )
            return worker_toolsets or ("skills", "terminal", "file", "web")
        return normalized or None

    def _max_iterations(self, task_input: dict[str, Any]) -> int:
        raw_value = task_input.get("max_iterations")
        explicit_value = raw_value is not None and raw_value != ""
        default_value = self._default_max_iterations(task_input)
        try:
            value = int(raw_value) if explicit_value else default_value
        except (TypeError, ValueError):
            value = default_value
        upper_bound = self._configured_positive_int("agent_loop_max_iterations", default=120)
        return max(1, min(value, upper_bound))

    def _default_max_iterations(self, task_input: dict[str, Any]) -> int:
        if self._is_worker_payload(task_input):
            return self._configured_positive_int("agent_loop_worker_default_max_iterations", default=80)
        return self._configured_positive_int("agent_loop_default_max_iterations", default=90)

    def _configured_positive_int(self, name: str, *, default: int) -> int:
        settings = getattr(self.provider, "settings", None)
        raw_value = getattr(settings, name, default)
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            value = default
        return max(1, value)

    @staticmethod
    def _is_worker_payload(task_input: dict[str, Any]) -> bool:
        worker_payload = task_input.get("worker")
        if isinstance(worker_payload, dict) and worker_payload.get("leaf") is True:
            return True
        role = str(task_input.get("role") or "").strip().lower()
        profile_key = str(task_input.get("profile_key") or "").strip().lower()
        return role == "worker" or profile_key.startswith("worker.")

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    def _provider_default_model(self) -> str:
        settings = getattr(self.provider, "settings", None)
        model = getattr(settings, "openai_response_model", None)
        return str(model or "gpt-5.4").strip() or "gpt-5.4"

    @staticmethod
    def _model_name(generated, task_input: dict[str, Any]) -> str | None:
        if generated is not None:
            model_attr = getattr(generated, "model", None)
            if isinstance(model_attr, str) and model_attr.strip():
                return model_attr.strip()
            metadata = generated.metadata or {}
            for key in ("model", "resolved_model"):
                value = metadata.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        model = task_input.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
        return None

    @classmethod
    def _response_contract_from_model_response(cls, generated: AgentModelResponse) -> dict[str, Any]:
        contract = parse_assistant_response_contract(generated.output_text)
        if isinstance(generated.progress_update, dict):
            contract["progressUpdate"] = generated.progress_update
        if isinstance(generated.work_disposition, dict):
            contract["workDisposition"] = generated.work_disposition
        if isinstance(generated.visible_text, str) and generated.visible_text.strip():
            contract["text"] = generated.visible_text.strip()
        return contract

    @staticmethod
    async def _emit_model_progress_update(
        *,
        progress_sink,
        progress_update: dict[str, Any],
        turn_index: int,
        generated: AgentModelResponse,
    ) -> None:
        if progress_sink is None:
            return
        payload = {
            "progressUpdate": dict(progress_update),
            "turn": turn_index,
            "model": generated.model,
            "responseId": (generated.metadata or {}).get("response_id"),
        }
        await progress_sink(
            event_type="model.progress.updated",
            summary_message=ToolCallingLoopHandler._progress_summary(progress_update),
            payload=payload,
        )

    @staticmethod
    def _progress_summary(progress_update: Any) -> str | None:
        if not isinstance(progress_update, dict):
            return None
        for key in ("summary", "message", "statusMessage", "title", "step"):
            value = progress_update.get(key)
            if isinstance(value, str) and value.strip():
                return " ".join(value.split())[:120]
        return None

    @staticmethod
    def _child_session_from_tool_results(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        for tool_result in tool_results:
            if str(tool_result.get("name") or "") != "delegate_task":
                continue
            result = tool_result.get("result")
            if not isinstance(result, dict) or result.get("ok") is False:
                continue
            child_session = result.get("child_session")
            if isinstance(child_session, dict):
                return dict(child_session)
        return None

    @staticmethod
    def _work_disposition_from_response_contract(response_contract: dict[str, Any] | None) -> dict[str, Any] | None:
        if not isinstance(response_contract, dict):
            return None
        disposition = response_contract.get("workDisposition")
        if not isinstance(disposition, dict):
            return None
        status = str(disposition.get("status") or "").strip()
        if status not in {"todo", "in_progress", "in_review", "blocked", "done", "cancelled"}:
            return None
        normalized = dict(disposition)
        normalized["status"] = status
        return normalized

    @staticmethod
    def _parent_work_disposition_from_tool_results(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        for item in reversed(tool_results):
            if str(item.get("name") or "") != "session_agent_task":
                continue
            result = item.get("result")
            if isinstance(result, dict) and isinstance(result.get("parentWorkDisposition"), dict):
                return dict(result["parentWorkDisposition"])
        return None

    @staticmethod
    def _delegate_agent_detail_from_tool_results(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        workers: list[dict[str, Any]] = []
        for tool_result in tool_results:
            if str(tool_result.get("name") or "") != "delegate_task":
                continue
            result = tool_result.get("result")
            if not isinstance(result, dict) or result.get("ok") is False:
                continue
            delegate = result.get("delegate")
            if not isinstance(delegate, dict):
                continue
            worker = {
                "agentId": delegate.get("agent_id") or delegate.get("agentId"),
                "workerSessionId": delegate.get("worker_session_id") or delegate.get("workerSessionId"),
                "profileKey": delegate.get("profile_key") or delegate.get("profileKey"),
                "summary": delegate.get("summary"),
                "status": delegate.get("status"),
            }
            workers.append(worker)
        if not workers:
            return None
        latest = workers[-1]
        return {
            "called": True,
            "agentId": latest.get("agentId"),
            "workerSessionId": latest.get("workerSessionId"),
            "profileKey": latest.get("profileKey"),
            "summary": latest.get("summary"),
            "status": latest.get("status"),
            "workers": workers,
        }

    @staticmethod
    def _session_agent_detail_from_tool_results(tool_results: list[dict[str, Any]]) -> dict[str, Any] | None:
        session_agents: list[dict[str, Any]] = []
        for tool_result in tool_results:
            if str(tool_result.get("name") or "") != "session_agent_task":
                continue
            result = tool_result.get("result")
            if not isinstance(result, dict):
                continue
            child_work = result.get("child_work") or result.get("childWork")
            if not isinstance(child_work, dict):
                continue
            assignee_agent_id = child_work.get("assigneeAgentId") or child_work.get("assignee_agent_id")
            session_agents.append(
                {
                    "agentId": assignee_agent_id,
                    "workId": child_work.get("workId") or child_work.get("work_id"),
                    "identifier": child_work.get("identifier"),
                    "taskRunId": result.get("taskRunId") or result.get("task_run_id"),
                    "status": result.get("childStatus") or result.get("child_status"),
                    "summary": result.get("content"),
                }
            )
        if not session_agents:
            return None
        latest = session_agents[-1]
        return {
            "called": True,
            "agentId": latest.get("agentId"),
            "status": latest.get("status"),
            "summary": latest.get("summary"),
            "sessionAgents": session_agents,
        }

    @staticmethod
    def _build_detail_json(
        *,
        tool_names: list[str],
        llm_call_count: int,
        model_name: str | None,
        todo_state: dict[str, Any],
    ) -> dict[str, Any]:
        """UI detail_json에는 실제 호출된 도구와 현재 todo projection을 함께 담는다."""

        unique_tool_names = list(dict.fromkeys(tool_names))
        detail_json = {
            "agentDetail": {
                "called": False,
                "agentId": None,
                "workerSessionId": None,
                "profileKey": None,
            },
            "toolDetail": {
                "toolNames": unique_tool_names,
                "primaryTool": unique_tool_names[0] if unique_tool_names else None,
            },
            "llmDetail": {
                "model": model_name,
                "callCount": llm_call_count,
            },
        }
        detail_json = {
            **detail_json,
            **build_todo_detail_patch(parse_task_todo_payload(todo_state)),
        }
        return detail_json

    @staticmethod
    def _next_todo_state(current_todo_state: dict[str, Any], tool_results: list[dict[str, Any]]) -> dict[str, Any]:
        """도구 실행 결과 중 todo 결과를 기준으로 agent.loop의 todo projection을 다시 계산한다."""

        observed_results = [
            result
            for result in tool_results
            if not (isinstance(result.get("result"), dict) and result["result"].get("ok") is False)
        ]
        return build_task_todo_payload(apply_tool_results_to_todo_state(current_todo_state, observed_results))

    @staticmethod
    def _tool_operation_status(result: Any) -> str:
        error = result.get("error") if isinstance(result, dict) else None
        if isinstance(error, dict) and error.get("code") == "tool_deferred_by_approval":
            return "waiting"
        if isinstance(result, dict) and result.get("ok") is False:
            return "failed"
        return "completed"

    @staticmethod
    def _tool_summary(result: dict) -> str:
        if isinstance(result, dict):
            for key in ("stdout", "body", "count", "session_id"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:80]
                if isinstance(value, int):
                    return f"{key}={value}"
            return json.dumps(result, ensure_ascii=False)[:80]
        return str(result)[:80]

    @classmethod
    def _tool_operation_error(cls, result: Any) -> dict[str, Any] | None:
        if not isinstance(result, dict) or result.get("ok") is not False:
            return None

        raw_error = result.get("error")
        source = raw_error if isinstance(raw_error, dict) else {}
        message = cls._optional_text(source.get("message") or (raw_error if isinstance(raw_error, str) else None))
        if message is None:
            message = cls._tool_summary(result)

        normalized: dict[str, Any] = {"message": message}
        code = cls._optional_text(source.get("code"))
        error_type = cls._optional_text(source.get("type"))
        retryable = source.get("retryable")
        if code is not None:
            normalized["code"] = code
        if error_type is not None:
            normalized["type"] = error_type
        if isinstance(retryable, bool):
            normalized["retryable"] = retryable
        return normalized

    @staticmethod
    def _next_operation_key(operation_counters: dict[str, int], *, namespace: str, base_key: str) -> str:
        sanitized_base_key = str(base_key or "operation").strip().replace(" ", "_")
        counter_key = f"{namespace}:{sanitized_base_key}"
        next_index = operation_counters.get(counter_key, 0) + 1
        operation_counters[counter_key] = next_index
        return f"{namespace}.{sanitized_base_key}.{next_index}"
