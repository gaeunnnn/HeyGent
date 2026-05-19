from __future__ import annotations

import inspect
import json
from time import monotonic
from typing import Any

from app.contracts.task.task_status import TaskStatus
from app.core.utils.ids import new_id
from app.domain.orchestration.delegation.launcher import ChildSessionLauncher
from app.domain.orchestration.delegation.policies import worker_session_unsuccessful
from app.domain.orchestration.delegation.spec import ChildSessionSpec
from app.domain.session.sessions.transcript_store import TranscriptStore
from app.domain.tasks.detail import merge_step_detail


BLOCKED_WORKER_TOOLSETS = ("delegate", "delegation")
DEFAULT_WORKER_TOOLSETS = ("skills", "terminal", "file", "web")
DEFAULT_WORKER_MAX_ITERATIONS = 80
DEFAULT_WORKER_HARD_TIMEOUT_SECONDS = 900


class DelegateRuntime:
    """child session lifecycle 을 parent step 관점에서 정리한다."""

    def __init__(self, child_session_launcher: ChildSessionLauncher, session_store: TranscriptStore | None = None) -> None:
        self.child_session_launcher = child_session_launcher
        self.session_store = session_store

    async def apply(self, *, task, step, outcome: dict, repository, on_step_updated=None) -> dict:
        child_session = outcome.get("child_session")
        if not child_session:
            return outcome

        profile = self._load_agent_profile(repository=repository, task=task, child_session=child_session)
        normalized_contract = self._normalize_child_contract(task=task, step=step, child_session=child_session, profile=profile)
        worker_session_id = self._create_worker_session(
            task=task,
            step=step,
            contract=normalized_contract,
        )
        spec = ChildSessionSpec(
            parent_task_run_id=task.task_run_id,
            parent_step_run_id=step.step_run_id,
            summary_prompt=child_session.get("summary_prompt"),
            metadata={
                **dict(child_session.get("metadata") or {}),
                "profile_id": normalized_contract["profile_id"],
                "profile_key": normalized_contract["profile_key"],
                "profile_version": normalized_contract["profile_version"],
                "agent_id": normalized_contract["agent_id"],
                "toolsets": normalized_contract["toolsets"],
                "blocked_toolsets": normalized_contract["blocked_toolsets"],
                "hard_timeout_seconds": normalized_contract["hard_timeout_seconds"],
                **({"provider_name": normalized_contract["provider_name"]} if normalized_contract.get("provider_name") else {}),
            },
            worker_session_id=worker_session_id,
        )

        # parent step 은 child 실행이 끝나기 전에도 "어떤 child 를 띄우려 했는가"를 저장해야 한다.
        # 그래야 launch 중간 실패나 프로세스 중단이 나도 위임 시도가 기록으로 남고,
        # 이후 exact step 기준으로 parent-child linkage 를 다시 복원할 수 있다.
        step.detail_json = merge_step_detail(step.detail_json, self.child_session_launcher.build_pending_detail(spec))
        repository.update_step(step)
        await self._notify_step_updated(
            on_step_updated,
            step=step,
            event_type="step.updated",
            payload={
                "reason": "delegate.started",
                "workerSessionId": worker_session_id,
                "profileKey": normalized_contract["profile_key"],
                "agentId": normalized_contract["agent_id"],
                "status": "RUNNING",
            },
            summary_message=f"{normalized_contract['goal']} worker 실행 중",
        )
        handoff_id = self._create_worker_handoff(
            repository=repository,
            spec=spec,
            task=task,
            contract=normalized_contract,
        )

        started_at = monotonic()
        try:
            launch_result = await self.child_session_launcher.launch(
                spec=spec,
                owner_key=task.owner_key,
                session_key=task.session_key,
                input_payload=self._build_worker_input_payload(
                    contract=normalized_contract,
                    worker_session_id=worker_session_id,
                    handoff_id=handoff_id,
                ),
            )
        except Exception as error:
            error_message = f"child session launch failed: {error}"
            delegate_summary = self._build_delegate_summary(
                contract=normalized_contract,
                agent_id=normalized_contract["agent_id"],
                worker_session_id=worker_session_id,
                status=TaskStatus.FAILED,
                summary="child session launch failed",
                started_at=started_at,
                error=error_message,
            )
            self._complete_worker_handoff(
                repository=repository,
                handoff_id=handoff_id,
                status="FAILED",
                result_summary=delegate_summary,
            )
            self._end_worker_session(worker_session_id, end_reason="FAILED")
            return {
                **outcome,
                "task_status": TaskStatus.FAILED,
                "step_status": TaskStatus.FAILED,
                "error_message": error_message,
                "summary_message": "child session launch failed",
                "result_payload": {
                    **dict(outcome.get("result_payload") or {}),
                    "delegate": delegate_summary,
                    "results": delegate_summary["results"],
                    "total_duration_seconds": delegate_summary["total_duration_seconds"],
                    "workerSessionId": worker_session_id,
                    "profileKey": normalized_contract["profile_key"],
                },
                "output_payload": {
                    **dict(outcome.get("output_payload") or {}),
                    "delegate": delegate_summary,
                    "workerSessionId": worker_session_id,
                    "profileKey": normalized_contract["profile_key"],
                },
                "detail_json": merge_step_detail(
                    outcome.get("detail_json"),
                    self.child_session_launcher.build_failed_detail(spec, error_message),
                ),
                "operations": [
                    *list(outcome.get("operations") or []),
                    {
                        "key": "agent.delegate",
                        "title": "worker 세션 실행",
                        "kind": "agent",
                        "status": "failed",
                        "summary": error_message,
                    }
                ],
            }

        detail_patch = self.child_session_launcher.build_result_detail(spec, launch_result)
        delegate_summary = self._build_delegate_summary(
            contract=normalized_contract,
            agent_id=launch_result.agent_id,
            worker_session_id=worker_session_id,
            status=str(launch_result.status),
            summary=launch_result.summary,
            started_at=started_at,
            launch_result=launch_result,
        )
        self._complete_worker_handoff(
            repository=repository,
            handoff_id=handoff_id,
            status=str(launch_result.status),
            result_summary=delegate_summary,
        )
        self._end_worker_session(worker_session_id, end_reason=str(launch_result.status))
        merged_output_payload = {**dict(outcome.get("output_payload") or {})}
        merged_output_payload["childStatus"] = launch_result.status
        merged_output_payload["workerSessionId"] = worker_session_id
        merged_output_payload["profileKey"] = normalized_contract["profile_key"]
        merged_output_payload["delegate"] = delegate_summary

        merged_result_payload = {**dict(outcome.get("result_payload") or {})}
        merged_result_payload["workerSessionId"] = worker_session_id
        merged_result_payload["profileKey"] = normalized_contract["profile_key"]
        merged_result_payload["delegate"] = delegate_summary
        merged_result_payload["results"] = delegate_summary["results"]
        merged_result_payload["total_duration_seconds"] = delegate_summary["total_duration_seconds"]

        merged_operations = [
            *list(outcome.get("operations") or []),
            {
                "key": "agent.delegate",
                "title": "worker 세션 실행",
                "kind": "agent",
                "status": "completed" if not worker_session_unsuccessful(launch_result.status) else "failed",
                "summary": launch_result.summary or worker_session_id,
            },
            {
                "key": "agent.collect_summary",
                "title": "worker 결과 회수",
                "kind": "agent",
                "status": "completed" if not worker_session_unsuccessful(launch_result.status) else "failed",
                "summary": launch_result.summary or worker_session_id,
            },
        ]

        if worker_session_unsuccessful(launch_result.status):
            terminal_status = TaskStatus.FAILED if launch_result.status == TaskStatus.FAILED else TaskStatus.CANCELED
            return {
                **outcome,
                "task_status": terminal_status,
                "step_status": terminal_status,
                "result_payload": merged_result_payload,
                "output_payload": merged_output_payload,
                "error_message": f"worker session ended in {launch_result.status}: {worker_session_id}",
                "summary_message": launch_result.summary or "worker session ended unsuccessfully",
                "detail_json": merge_step_detail(outcome.get("detail_json"), detail_patch),
                "operations": merged_operations,
            }

        return {
            **outcome,
            "result_payload": merged_result_payload,
            "output_payload": merged_output_payload,
            "summary_message": launch_result.summary or outcome.get("summary_message"),
            "detail_json": merge_step_detail(outcome.get("detail_json"), detail_patch),
            "operations": merged_operations,
        }

    async def run_child_as_tool(self, *, task, step, child_session: dict[str, Any], repository, on_step_updated=None) -> dict[str, Any]:
        """delegate_task 호출 1개를 실제 worker 실행 결과로 변환한다.

        parent LLM 이 worker 요약을 읽고 다음 tool_call 을 다시 판단해야 단계 순서가 맞는다.
        그래서 최종 TaskRun outcome 적용 시점까지 미루지 않고 tool 실행 중간에 worker 를 실행한다.
        """

        outcome = await self.apply(
            task=task,
            step=step,
            outcome={
                "child_session": child_session,
                "result_payload": {},
                "output_payload": {},
                "operations": [],
                "detail_json": {},
            },
            repository=repository,
            on_step_updated=on_step_updated,
        )
        detail_patch = outcome.get("detail_json")
        if isinstance(detail_patch, dict):
            step.detail_json = self._merge_worker_list_detail(step.detail_json, detail_patch)
            repository.update_step(step)
            await self._notify_step_updated(
                on_step_updated,
                step=step,
                event_type="step.updated",
                payload={"reason": "delegate.completed"},
                summary_message=outcome.get("summary_message"),
            )

        result_payload = dict(outcome.get("result_payload") or {})
        output_payload = dict(outcome.get("output_payload") or {})
        delegate_summary = result_payload.get("delegate") if isinstance(result_payload.get("delegate"), dict) else output_payload.get("delegate")
        if not isinstance(delegate_summary, dict):
            delegate_summary = {}
        status = str(delegate_summary.get("status") or outcome.get("task_status") or TaskStatus.COMPLETED)
        ok = not worker_session_unsuccessful(status)
        summary = str(delegate_summary.get("summary") or outcome.get("summary_message") or "").strip()
        error_message = outcome.get("error_message")
        content = self._tool_result_content(summary=summary, delegate_summary=delegate_summary, error_message=error_message)
        tool_result = {
            "ok": ok,
            "content": content,
            "delegate": delegate_summary,
            "workerSessionId": result_payload.get("workerSessionId") or output_payload.get("workerSessionId"),
            "profileKey": result_payload.get("profileKey") or output_payload.get("profileKey"),
            "childStatus": status,
        }
        if not ok and error_message:
            tool_result["error"] = {"message": error_message}
        return tool_result

    @staticmethod
    def _create_worker_handoff(*, repository, spec: ChildSessionSpec, task, contract: dict[str, Any]) -> str | None:
        if not hasattr(repository, "create_worker_handoff"):
            return None
        handoff_id = new_id("handoff")
        metadata = dict(spec.metadata or {})
        # worker handoff row는 parent transcript와 분리된 실행 시도를 재시작 뒤에도 추적하기 위한 anchor다.
        repository.create_worker_handoff(
            {
                "handoff_id": handoff_id,
                "task_run_id": spec.parent_task_run_id,
                "parent_step_run_id": spec.parent_step_run_id,
                "parent_session_id": contract.get("parent_session_id"),
                "worker_session_id": spec.worker_session_id,
                "worker_profile_id": contract["profile_id"] or contract["profile_key"],
                "worker_profile_version": contract["profile_version"],
                "status": "RUNNING",
                "input_payload": {
                    **contract,
                    "summary_prompt": spec.summary_prompt,
                    "metadata": metadata,
                },
            }
        )
        return handoff_id

    @staticmethod
    def _complete_worker_handoff(*, repository, handoff_id: str | None, status: str, result_summary: dict) -> None:
        if handoff_id is None or not hasattr(repository, "complete_worker_handoff"):
            return
        repository.complete_worker_handoff(
            handoff_id,
            {
                "status": status,
                "result_summary": result_summary,
            },
        )

    def _create_worker_session(self, *, task, step, contract: dict[str, Any]) -> str | None:
        if self.session_store is None:
            return None

        session_key = str(getattr(task, "session_key", "") or getattr(task, "task_run_id", "")).strip()
        if not session_key:
            return None

        parent_session_id = self._resolve_parent_session_id(task=task, session_key=session_key)
        contract["parent_session_id"] = parent_session_id

        worker_session_id = new_id("session")
        # worker session은 같은 session_key 아래에 두되 parent_session_id와 parent_step_run_id로 계층을 고정한다.
        self.session_store.create_session(
            session_id=worker_session_id,
            session_key=session_key,
            source="worker",
            user_id=getattr(task, "owner_key", None),
            model=contract.get("model"),
            parent_session_id=parent_session_id,
            title=str(contract.get("goal") or getattr(step, "title", None) or "worker")[:120],
            metadata={
                "task_run_id": getattr(task, "task_run_id", None),
                "parent_task_run_id": getattr(task, "task_run_id", None),
                "parent_step_run_id": getattr(step, "step_run_id", None),
                "profile_key": contract["profile_key"],
                "agent_id": contract["agent_id"],
                "session_role": "worker",
                "delegation_policy": {
                    "leaf": True,
                    "max_worker_depth": 0,
                    "blocked_toolsets": list(BLOCKED_WORKER_TOOLSETS),
                },
                "toolsets": contract["toolsets"],
                **({"provider_name": contract["provider_name"]} if contract.get("provider_name") else {}),
            },
        )
        return worker_session_id

    def _resolve_parent_session_id(self, *, task, session_key: str) -> str | None:
        task_input = dict(getattr(task, "input_payload", {}) or {})
        transcript_session_id = self._optional_text(task_input.get("transcript_session_id"))
        if transcript_session_id:
            session = self._get_session(transcript_session_id)
            if session is not None:
                return self._flatten_worker_parent(session)
            return transcript_session_id

        latest_parent = self.session_store.get_latest_session_by_key(session_key)
        if latest_parent is None:
            return None
        return self._flatten_worker_parent(latest_parent)

    def _get_session(self, session_id: str) -> dict[str, Any] | None:
        getter = getattr(self.session_store, "get_session", None)
        if not callable(getter):
            return None
        return getter(session_id)

    def _end_worker_session(self, worker_session_id: str | None, *, end_reason: str) -> None:
        if not worker_session_id or self.session_store is None:
            return
        end_session = getattr(self.session_store, "end_session", None)
        if callable(end_session):
            end_session(worker_session_id, end_reason=end_reason)

    @staticmethod
    def _flatten_worker_parent(session: dict[str, Any]) -> str | None:
        session_id = str(session.get("id") or "").strip() or None
        metadata = dict(session.get("metadata") or {})
        role = str(metadata.get("session_role") or session.get("source") or "").strip().lower()
        parent_session_id = str(session.get("parent_session_id") or "").strip() or None
        # worker가 다시 worker를 만드는 구조는 depth1 원칙과 UI 계층을 깨뜨린다.
        # 혹시 worker 세션이 기준으로 들어와도 parent main transcript 아래에 평평하게 붙인다.
        if role == "worker" and parent_session_id:
            return parent_session_id
        return session_id

    @classmethod
    def _load_agent_profile(cls, *, repository, task, child_session: dict[str, Any]) -> dict[str, Any] | None:
        getter = getattr(repository, "get_agent_profile", None)
        if not callable(getter):
            return None
        metadata = dict(child_session.get("metadata") or {})
        profile_key = cls._optional_text(child_session.get("profile_key")) or cls._optional_text(metadata.get("profile_key")) or "worker.default"
        profile_version = metadata.get("profile_version") or child_session.get("profile_version")
        try:
            return getter(profile_key, owner_key="system", profile_version=profile_version)
        except TypeError:
            # 테스트 double이나 이전 repository 계약은 keyword를 덜 받을 수 있다.
            return getter(profile_key)

    @classmethod
    def _normalize_child_contract(cls, *, task, step, child_session: dict[str, Any], profile: dict[str, Any] | None = None) -> dict[str, Any]:
        source_payload = dict(child_session.get("input_payload") or {})
        metadata = dict(child_session.get("metadata") or {})
        profile_config = dict((profile or {}).get("config_snapshot") or {})
        profile_policy = dict((profile or {}).get("delegation_policy") or {})
        goal = cls._optional_text(child_session.get("goal")) or cls._optional_text(source_payload.get("goal")) or cls._optional_text(source_payload.get("prompt")) or "worker task"
        context = child_session.get("context", source_payload.get("context", {}))
        toolsets = cls._normalize_worker_toolsets(
            child_session.get("toolsets", source_payload.get("toolsets", source_payload.get("enabled_toolsets"))),
            profile_toolsets=profile_config.get("toolsets"),
        )
        max_iterations = cls._normalize_positive_int(
            child_session.get("max_iterations", source_payload.get("max_iterations", profile_policy.get("maxIterations", profile_policy.get("max_iterations")))),
            default=DEFAULT_WORKER_MAX_ITERATIONS,
        )
        # hard timeout은 worker profile의 실행 정책이다. payload에 같이 싣고 runner에서
        # 실제 asyncio.wait_for로 강제해야 DB seed 값이 문서상 숫자로만 남지 않는다.
        hard_timeout_seconds = cls._normalize_positive_int(
            child_session.get(
                "hard_timeout_seconds",
                child_session.get(
                    "hardTimeoutSeconds",
                    source_payload.get(
                        "hard_timeout_seconds",
                        source_payload.get(
                            "hardTimeoutSeconds",
                            profile_policy.get("hardTimeoutSeconds", profile_policy.get("hard_timeout_seconds")),
                        ),
                    ),
                ),
            ),
            default=DEFAULT_WORKER_HARD_TIMEOUT_SECONDS,
        )
        profile_key = cls._optional_text(child_session.get("profile_key")) or cls._optional_text(metadata.get("profile_key")) or "worker.default"
        profile_id = cls._optional_text((profile or {}).get("profile_id"))
        profile_version = cls._normalize_positive_int((profile or {}).get("profile_version") or metadata.get("profile_version"), default=1)
        agent_id = (
            cls._optional_text(child_session.get("agent_id"))
            or cls._optional_text(metadata.get("agent_id"))
            or profile_id
            or f"{getattr(step, 'step_run_id', 'step')}:worker"
        )
        role = cls._optional_text(child_session.get("role", source_payload.get("role"))) or "worker"
        tasks = child_session.get("tasks", source_payload.get("tasks", []))
        if not isinstance(tasks, list):
            tasks = []
        model = cls._optional_text(child_session.get("model", source_payload.get("model", profile_config.get("model"))))
        provider_name = cls._worker_provider_name(
            child_session=child_session,
            source_payload=source_payload,
            profile_config=profile_config,
            profile=profile,
            model=model,
        )

        return {
            "goal": goal,
            "context": context if context is not None else {},
            "toolsets": toolsets,
            "blocked_toolsets": list(BLOCKED_WORKER_TOOLSETS),
            "max_iterations": max_iterations,
            "hard_timeout_seconds": hard_timeout_seconds,
            "role": role,
            "acp_command": child_session.get("acp_command", source_payload.get("acp_command")),
            "acp_args": dict(child_session.get("acp_args", source_payload.get("acp_args", {})) or {}),
            "tasks": tasks,
            "profile_id": profile_id,
            "profile_key": profile_key,
            "profile_version": profile_version,
            "agent_id": agent_id,
            "model": model,
            "provider_name": provider_name,
            "input_payload": source_payload,
            "parent_task_run_id": getattr(task, "task_run_id", None),
            "parent_step_run_id": getattr(step, "step_run_id", None),
        }

    @staticmethod
    def _build_worker_input_payload(*, contract: dict[str, Any], worker_session_id: str | None, handoff_id: str | None) -> dict[str, Any]:
        payload = dict(contract.get("input_payload") or {})
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            prompt_parts = [f"Goal: {contract['goal']}"]
            context_value = contract.get("context")
            if context_value is not None and context_value != "" and context_value != {}:
                prompt_parts.append(f"Context: {contract['context']}")
            prompt = "\n".join(prompt_parts)
        payload.update(
            {
                "prompt": prompt,
                "goal": contract["goal"],
                "context": contract["context"],
                "toolsets": contract["toolsets"],
                "enabled_toolsets": contract["toolsets"],
                "blocked_toolsets": contract["blocked_toolsets"],
                "max_iterations": contract["max_iterations"],
                "hard_timeout_seconds": contract["hard_timeout_seconds"],
                "hardTimeoutSeconds": contract["hard_timeout_seconds"],
                "role": contract["role"],
                "acp_command": contract["acp_command"],
                "acp_args": contract["acp_args"],
                "tasks": contract["tasks"],
                "profile_key": contract["profile_key"],
                "profile_version": contract["profile_version"],
                "agent_id": contract["agent_id"],
                "model": contract["model"],
                "transcript_session_id": worker_session_id,
                "worker": {
                    "leaf": True,
                    "handoff_id": handoff_id,
                    "parent_task_run_id": contract["parent_task_run_id"],
                    "parent_step_run_id": contract["parent_step_run_id"],
                    "worker_session_id": worker_session_id,
                    "blocked_toolsets": contract["blocked_toolsets"],
                    "hard_timeout_seconds": contract["hard_timeout_seconds"],
                },
            }
        )
        if contract.get("provider_name"):
            payload["provider_name"] = contract["provider_name"]
            payload["providerName"] = contract["provider_name"]
        return payload

    @classmethod
    def _build_delegate_summary(
        cls,
        *,
        contract: dict[str, Any],
        agent_id: str,
        worker_session_id: str | None,
        status: str,
        summary: str | None,
        started_at: float,
        launch_result=None,
        error: str | None = None,
    ) -> dict[str, Any]:
        duration = cls._duration_since(started_at)
        result_payload = dict(getattr(launch_result, "result_payload", {}) or {})
        output_payload = dict(getattr(launch_result, "output_payload", {}) or {})
        result_item = {
            "task_index": 0,
            "status": status,
            "summary": summary,
            "api_calls": cls._api_call_count(result_payload=result_payload, output_payload=output_payload),
            "duration_seconds": getattr(launch_result, "duration_seconds", None) if launch_result is not None else duration,
            "model": cls._model_name(result_payload=result_payload, output_payload=output_payload, contract=contract),
            "exit_reason": status,
            "tokens": cls._tokens(result_payload=result_payload, output_payload=output_payload),
            "tool_trace": cls._tool_trace(result_payload=result_payload, output_payload=output_payload),
            "error": error,
        }
        return {
            "profile_key": contract["profile_key"],
            "profileKey": contract["profile_key"],
            "agent_id": agent_id,
            "worker_session_id": worker_session_id,
            "workerSessionId": worker_session_id,
            "tasks": list(contract.get("tasks") or []),
            "results": [result_item],
            "total_duration_seconds": duration,
            "toolsets": contract["toolsets"],
            "blocked_toolsets": contract["blocked_toolsets"],
            "leaf": True,
            "status": status,
            "summary": summary,
            "error": error,
        }

    @staticmethod
    def _normalize_worker_toolsets(raw_toolsets: Any, *, profile_toolsets: Any = None) -> list[str]:
        source = raw_toolsets if isinstance(raw_toolsets, list) else list(DEFAULT_WORKER_TOOLSETS)
        profile_allowed = _profile_allowed_toolsets(profile_toolsets)
        normalized: list[str] = []
        blocked = set(BLOCKED_WORKER_TOOLSETS)
        for item in source:
            name = str(item or "").strip()
            if not name or name in blocked or name in normalized:
                continue
            if profile_allowed is not None and name not in profile_allowed:
                continue
            normalized.append(name)
        if normalized:
            return normalized
        if profile_allowed is not None:
            fallback = [item for item in DEFAULT_WORKER_TOOLSETS if item in profile_allowed]
            if fallback:
                return fallback
        return list(DEFAULT_WORKER_TOOLSETS)

    @staticmethod
    def _normalize_positive_int(value: Any, *, default: int) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return default
        return max(1, parsed)

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    @classmethod
    def _worker_provider_name(
        cls,
        *,
        child_session: dict[str, Any],
        source_payload: dict[str, Any],
        profile_config: dict[str, Any],
        profile: dict[str, Any] | None,
        model: str | None,
    ) -> str | None:
        provider = (
            cls._optional_text(child_session.get("provider_name"))
            or cls._optional_text(child_session.get("providerName"))
            or cls._optional_text(child_session.get("adapterType"))
            or cls._optional_text(source_payload.get("provider_name"))
            or cls._optional_text(source_payload.get("providerName"))
            or cls._optional_text(source_payload.get("adapterType"))
            or cls._optional_text(profile_config.get("provider_name"))
            or cls._optional_text(profile_config.get("providerName"))
            or cls._optional_text(profile_config.get("adapterType"))
            or cls._optional_text((profile or {}).get("provider_name"))
            or cls._optional_text((profile or {}).get("providerName"))
        )
        if provider:
            return cls._normalize_provider_name(provider)
        if model and model.strip().lower().startswith("gemini-"):
            return "gemini_api_key"
        return None

    @staticmethod
    def _normalize_provider_name(provider: str) -> str:
        normalized = provider.strip().lower()
        if normalized in {"gemini", "gemini_api", "gemini_api_key"}:
            return "gemini_api_key"
        if normalized in {"openai", "openai_api", "openai_api_key", "openai_user_api_key"}:
            return "openai_api_key"
        return provider

    @staticmethod
    def _duration_since(started_at: float) -> float:
        return round(max(0.0, monotonic() - started_at), 3)

    @staticmethod
    async def _notify_step_updated(callback, *, step, event_type: str, payload: dict[str, Any], summary_message: str | None = None) -> None:
        if callback is None:
            return
        result = callback(step=step, event_type=event_type, payload=payload, summary_message=summary_message)
        if inspect.isawaitable(result):
            await result

    @classmethod
    def _merge_worker_list_detail(cls, current: dict[str, Any] | None, patch: dict[str, Any] | None) -> dict[str, Any]:
        merged = merge_step_detail(current, patch)
        agent_detail = dict(merged.get("agentDetail") or {})
        worker = cls._worker_item(agent_detail)
        existing_workers = [
            dict(item)
            for item in ((current or {}).get("agentDetail") or {}).get("workers", [])
            if isinstance(item, dict)
        ]
        if worker:
            worker_id = worker.get("workerSessionId") or worker.get("agentId")
            replaced = False
            for index, existing in enumerate(existing_workers):
                existing_id = existing.get("workerSessionId") or existing.get("agentId")
                if worker_id and existing_id == worker_id:
                    existing_workers[index] = {**existing, **worker}
                    replaced = True
                    break
            if not replaced:
                existing_workers.append(worker)
        if existing_workers:
            agent_detail["workers"] = existing_workers
            merged["agentDetail"] = agent_detail
        return merged

    @staticmethod
    def _worker_item(agent_detail: dict[str, Any]) -> dict[str, Any] | None:
        if not agent_detail.get("called"):
            return None
        return {
            "agentId": agent_detail.get("agentId"),
            "workerSessionId": agent_detail.get("workerSessionId"),
            "profileKey": agent_detail.get("profileKey"),
            "summary": agent_detail.get("summary"),
            "status": agent_detail.get("status"),
        }

    @staticmethod
    def _tool_result_content(*, summary: str, delegate_summary: dict[str, Any], error_message: str | None) -> str:
        if error_message:
            return f"worker 실행 실패: {error_message}"
        if summary:
            return summary
        if delegate_summary:
            return json.dumps(delegate_summary, ensure_ascii=False)
        return "worker 실행이 완료되었습니다."

    @staticmethod
    def _api_call_count(*, result_payload: dict[str, Any], output_payload: dict[str, Any]) -> int:
        for payload in (output_payload, result_payload):
            detail = payload.get("llmDetail") if isinstance(payload.get("llmDetail"), dict) else None
            if detail is not None and detail.get("callCount") is not None:
                return int(detail.get("callCount") or 0)
            usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None
            if usage:
                return 1
        return 0

    @staticmethod
    def _model_name(*, result_payload: dict[str, Any], output_payload: dict[str, Any], contract: dict[str, Any]) -> str | None:
        metadata = result_payload.get("metadata") if isinstance(result_payload.get("metadata"), dict) else {}
        for value in (
            output_payload.get("model"),
            result_payload.get("model"),
            metadata.get("model"),
            metadata.get("resolved_model"),
            contract.get("model"),
        ):
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    @staticmethod
    def _tokens(*, result_payload: dict[str, Any], output_payload: dict[str, Any]) -> dict[str, Any]:
        for payload in (output_payload, result_payload):
            usage = payload.get("usage")
            if isinstance(usage, dict):
                return dict(usage)
            tokens = payload.get("tokens")
            if isinstance(tokens, dict):
                return dict(tokens)
        return {}

    @staticmethod
    def _tool_trace(*, result_payload: dict[str, Any], output_payload: dict[str, Any]) -> list[dict[str, Any]]:
        raw_results = output_payload.get("tool_results") or result_payload.get("tool_results") or []
        if not isinstance(raw_results, list):
            return []
        trace = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            result = item.get("result") if isinstance(item.get("result"), dict) else {}
            trace.append(
                {
                    "tool_call_id": item.get("tool_call_id"),
                    "name": item.get("name"),
                    "status": "failed" if result.get("ok") is False else "completed",
                    "error": result.get("error"),
                }
            )
        return trace


def _profile_allowed_toolsets(profile_toolsets: Any) -> set[str] | None:
    if not isinstance(profile_toolsets, list):
        return None
    allowed = {str(item or "").strip() for item in profile_toolsets}
    allowed.discard("")
    return allowed or None
