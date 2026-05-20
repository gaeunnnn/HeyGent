from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from app.core.utils.ids import new_id
from app.domain.work import WorkComment, WorkRunClaimConflict, WorkService
from app.domain.session.sessions.transcript_store import TranscriptStore
from app.tools.runtime.registry import (
    build_runtime_tool_entries,
    list_runtime_tool_availability,
    list_runtime_tool_definitions,
)
from app.tools.runtime.tool_result_tool import tool_result_read_handler
from app.tools.runtime.toolsets import resolve_runtime_tool_names


FILE_TOOL_NAMES = {"read_file", "write_file", "patch", "search_files"}
# PoC 단계 3: terminal + file 4개를 사용자 PC 브릿지로 위임한다.
# 분기 자리는 한 곳뿐이라 호출자(tool_calling_loop, transcript 기록)는 결과 dict가 같으면 변경을 인지할 필요 없음.
BRIDGE_ROUTABLE_TOOLS = {"terminal.run", "read_file", "write_file", "patch", "search_files"}
MAX_TERMINAL_STREAM_CHARS = 12_000
MAX_SKILL_RESOURCE_BYTES = 200_000
SECRET_FILE_NAME_PATTERN = re.compile(
    r"(^|[._-])(secret|secrets|token|password|passwd|credential|credentials|env)($|[._-])",
    re.IGNORECASE,
)


class LocalToolRuntime:
    """현재 백본에서 실제로 실행 가능한 로컬 runtime tool dispatcher 다.

    runtime tool은 agent.loop 안에서 LLM이 호출할 수 있는 실제 기능이다.
    """

    def __init__(
        self,
        *,
        skill_registry,
        session_store: TranscriptStore,
        workspace_root: str | os.PathLike[str] | None = None,
        bridge_session_manager=None,
        owner_key: str | None = None,
        work_repository=None,
        agent_repository=None,
        prototype_repository=None,
        runtime_context: dict[str, Any] | None = None,
    ) -> None:
        self.skill_registry = skill_registry
        self.session_store = session_store
        self.bridge_session_manager = bridge_session_manager
        self.owner_key = str(owner_key) if owner_key else None
        self.work_repository = work_repository
        self.agent_repository = agent_repository
        self.prototype_repository = prototype_repository
        self.runtime_context = dict(runtime_context or {})
        self.workspace_root = self._resolve_workspace_root(workspace_root)
        self._todo_items: list[dict[str, str]] = []
        self._tool_entries = build_runtime_tool_entries(
            {
                "skills.list": self._list_skills,
                "skills.read": self._read_skill,
                "skills.read_file": self._read_skill_file,
                "skill.execute": self._execute_skill,
                "skill.run_script": self._run_skill_script,
                "session.record": self._record_session_message,
                "session.search": self._search_sessions,
                "todo": self._todo,
                "delegate_task": self._delegate_task,
                "session_agent_task": self._session_agent_task,
                "mattermost.send": self._send_mattermost_message,
                "notion.execute": self._execute_notion,
                "gmail.execute": self._execute_gmail,
                "health.execute": self._execute_health,
                "design.list_presets": self._list_design_presets,
                "design.read_preset": self._read_design_preset,
                "prototype.get_active_artifact": self._get_active_prototype_artifact,
                "prototype.create_artifact": self._create_prototype_artifact,
                "tool_result.read": self._read_tool_result,
                "terminal.run": self._run_terminal_command,
                "http_get": self._run_http_get,
                "read_file": self._read_file,
                "write_file": self._write_file,
                "patch": self._patch_file,
                "search_files": self._search_files,
            }
        )

    def list_tool_definitions(self, *, enabled_toolsets: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        definitions = list_runtime_tool_definitions(
            {name: entry.handler for name, entry in self._tool_entries.items()}
        )
        allowed_tool_names = resolve_runtime_tool_names(enabled_toolsets)
        if allowed_tool_names is None:
            return definitions
        return [item for item in definitions if item["name"] in allowed_tool_names]

    def list_tool_availability(self, *, enabled_toolsets: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
        availability = list_runtime_tool_availability(
            {name: entry.handler for name, entry in self._tool_entries.items()}
        )
        allowed_tool_names = resolve_runtime_tool_names(enabled_toolsets)
        if allowed_tool_names is None:
            return availability
        return [item for item in availability if item["name"] in allowed_tool_names]

    def bind_workspace_root(self, workspace_root: str | os.PathLike[str] | None) -> "LocalToolRuntime":
        if workspace_root is None or str(workspace_root).strip() == "":
            return self

        bound = self.__class__(
            skill_registry=self.skill_registry,
            session_store=self.session_store,
            workspace_root=workspace_root,
            bridge_session_manager=self.bridge_session_manager,
            owner_key=self.owner_key,
            work_repository=self.work_repository,
            agent_repository=self.agent_repository,
            prototype_repository=self.prototype_repository,
            runtime_context=self.runtime_context,
        )
        bound._todo_items = [dict(item) for item in self._todo_items]
        return bound

    def bind_request_context(
        self,
        *,
        workspace_root: str | os.PathLike[str] | None = None,
        owner_key: str | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> "LocalToolRuntime":
        bound = self.__class__(
            skill_registry=self.skill_registry,
            session_store=self.session_store,
            workspace_root=workspace_root if workspace_root is not None else self.workspace_root,
            bridge_session_manager=self.bridge_session_manager,
            owner_key=owner_key or self.owner_key,
            work_repository=self.work_repository,
            agent_repository=self.agent_repository,
            prototype_repository=self.prototype_repository,
            runtime_context=runtime_context if runtime_context is not None else self.runtime_context,
        )
        bound._todo_items = [dict(item) for item in self._todo_items]
        return bound

    def run_calls(
        self,
        calls: list[dict[str, Any]],
        *,
        enabled_toolsets: tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for call in calls:
            name = str(call.get("name") or "").strip()
            args = dict(call.get("args") or {})
            result = self.run_call(name=name, args=args, enabled_toolsets=enabled_toolsets)
            results.append(
                {
                    "name": name,
                    "args": args,
                    "result": result,
                }
            )
        return results

    def run_call(
        self,
        *,
        name: str,
        args: dict[str, Any],
        enabled_toolsets: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        normalized_name = str(name or "").strip()
        allowed_tool_names = resolve_runtime_tool_names(enabled_toolsets)
        if allowed_tool_names is not None and normalized_name not in allowed_tool_names:
            return self._tool_error(
                code="tool_unavailable",
                message=f"unknown or disabled runtime tool: {normalized_name}",
                tool_name=normalized_name,
            )

        entry = self._tool_entries.get(normalized_name)
        if entry is None:
            return self._tool_error(
                code="tool_unavailable",
                message=f"unknown or disabled runtime tool: {normalized_name}",
                tool_name=normalized_name,
            )

        # validation 실패도 tool result(tool 실행 결과를 모델에게 다시 넘기는 메시지)로 돌려
        # LLM이 인자 수정, 우회, 중단 중 다음 행동을 판단하게 한다.
        validation_error = self._validate_args(entry.definition.schema, args)
        if validation_error:
            return self._tool_error(
                code="invalid_tool_arguments",
                message=validation_error,
                tool_name=normalized_name,
            )

        trusted_args = self._bind_trusted_runtime_args(tool_name=normalized_name, args=args)

        # ★ PoC 단계 2 분기 ★
        # 로컬 자원 도구는 사용자 PC 브릿지에 위임. 분기 자리는 여기 한 곳뿐이라
        # 호출자(tool_calling_loop, transcript 기록 등)는 결과 dict 형식이 그대로면 변경을 인지할 필요 없음.
        if normalized_name in BRIDGE_ROUTABLE_TOOLS and self.bridge_session_manager is not None:
            bridge_result = self._maybe_route_via_bridge(tool_name=normalized_name, args=trusted_args)
            if bridge_result is not None:
                return bridge_result

        try:
            result = entry.handler(trusted_args)
        except Exception as error:
            # handler 예외도 raise로 loop를 끊지 않고 관찰 가능한 tool result로 남긴다.
            return self._tool_error(
                code="tool_execution_failed",
                message=f"{type(error).__name__}: {error}",
                tool_name=normalized_name,
            )
        return result

    def require_call(self, *, name: str, args: dict[str, Any]) -> dict[str, Any]:
        entry = self._tool_entries.get(name)
        if entry is None:
            raise KeyError(name)
        return entry.handler(dict(args))

    def _maybe_route_via_bridge(self, *, tool_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
        """현재 요청 user 의 브릿지가 연결돼 있으면 도구 호출을 위임하고 결과 dict를 그대로 반환한다.

        결과 형식은 기존 로컬 실행과 동일해야 한다 (브릿지 executor가 맞춤).
        브릿지 미연결·타임아웃 등은 _tool_error 형식으로 변환.
        """

        manager = self.bridge_session_manager
        user_id = self.owner_key
        if manager is None or not user_id or not manager.is_alive(user_id):
            return self._tool_error(
                code="bridge_not_connected",
                message="로컬 브릿지가 연결되어 있지 않습니다",
                tool_name=tool_name,
            )

        # 순환 import 방지를 위해 함수 내부에서 import.
        from app.bridge import BridgeDisconnected, BridgeError, BridgeTimeout

        try:
            return manager.execute_sync(user_id=user_id, name=tool_name, args=args)
        except BridgeTimeout as error:
            return self._tool_error(code="bridge_timeout", message=str(error), tool_name=tool_name)
        except BridgeDisconnected as error:
            return self._tool_error(code="bridge_disconnected", message=str(error), tool_name=tool_name)
        except BridgeError as error:
            return self._tool_error(
                code="bridge_error",
                message=f"{type(error).__name__}: {error}",
                tool_name=tool_name,
            )

    def _list_skills(self, args: dict[str, Any]) -> dict[str, object]:
        skills = self._runtime_skills()
        names = sorted(skills.keys())
        return {
            "count": len(names),
            "items": names,
            "skills": [
                {
                    "name": name,
                    "description": str(skills[name].get("description") or ""),
                }
                for name in names
            ],
        }

    def _read_skill(self, args: dict[str, Any]) -> dict[str, object]:
        skill_name = str(args["skill_name"])
        if not self._is_runtime_skill_enabled(skill_name):
            return self._tool_error(
                code="skill_disabled",
                message=f"disabled skill: {skill_name}",
                tool_name="skills.read",
            )
        skill = getattr(self.skill_registry, "_skills", {}).get(skill_name)
        if skill is None:
            raise KeyError(skill_name)
        return {
            "name": skill_name,
            "path": str(skill.get("path") or ""),
            "body": str(skill.get("body") or ""),
        }

    def _read_skill_file(self, args: dict[str, Any]) -> dict[str, object]:
        skill_name = str(args["skill_name"])
        if not self._is_runtime_skill_enabled(skill_name):
            return self._tool_error(
                code="skill_disabled",
                message=f"disabled skill: {skill_name}",
                tool_name="skills.read_file",
            )

        skill = getattr(self.skill_registry, "_skills", {}).get(skill_name)
        if skill is None:
            return self._tool_error(
                code="skill_not_found",
                message=f"unknown skill: {skill_name}",
                tool_name="skills.read_file",
            )

        inline_file = self._read_inline_skill_file(skill, args.get("path"))
        if inline_file is not None:
            return inline_file

        document_path = self._resolve_skill_document_path(skill.get("path"))
        if document_path is None or not self._is_allowed_skill_path(document_path):
            return self._tool_error(
                code="skill_path_not_allowed",
                message="skill document path must stay inside app/skills",
                tool_name="skills.read_file",
            )

        resource_path = self._resolve_skill_resource_path(document_path, args.get("path"))
        if resource_path is None:
            return self._tool_error(
                code="skill_file_not_allowed",
                message="skill file path must stay inside the selected skill",
                tool_name="skills.read_file",
            )
        if not resource_path.exists() or not resource_path.is_file():
            return self._tool_error(
                code="skill_file_not_found",
                message="skill file not found",
                tool_name="skills.read_file",
            )

        raw = resource_path.read_bytes()
        truncated = len(raw) > MAX_SKILL_RESOURCE_BYTES
        raw = raw[:MAX_SKILL_RESOURCE_BYTES]
        if b"\x00" in raw:
            return self._tool_error(
                code="skill_file_not_text",
                message="skill file is not a text file",
                tool_name="skills.read_file",
            )

        return {
            "ok": True,
            "skill_name": skill_name,
            "path": resource_path.relative_to(document_path.parent).as_posix(),
            "content": raw.decode("utf-8", errors="replace"),
            "bytes_read": len(raw),
            "truncated": truncated,
        }

    def _execute_skill(self, args: dict[str, Any]) -> dict[str, object]:
        skill_name = str(args.get("skill_name") or "").strip()
        action = str(args.get("action") or "").strip()
        if not self._is_runtime_skill_enabled(skill_name):
            return self._tool_error(
                code="skill_disabled",
                message=f"disabled skill: {skill_name}",
                tool_name="skill.execute",
            )
        if action != "inspect":
            return self._tool_error(
                code="unsupported_skill_action",
                message=f"unsupported skill action: {action}",
                tool_name="skill.execute",
            )

        skill = getattr(self.skill_registry, "_skills", {}).get(skill_name)
        if skill is None:
            return self._tool_error(
                code="skill_not_found",
                message=f"unknown skill: {skill_name}",
                tool_name="skill.execute",
            )

        if self._is_inline_skill(skill):
            return {
                "ok": True,
                "skill_name": skill_name,
                "action": action,
                "path": str(skill.get("path") or ""),
                "files": self._list_inline_skill_files(skill),
                "content": str(skill.get("body") or ""),
            }

        document_path = self._resolve_skill_document_path(skill.get("path"))
        if document_path is not None and not self._is_allowed_skill_path(document_path):
            return self._tool_error(
                code="skill_path_not_allowed",
                message="skill document path must stay inside app/skills",
                tool_name="skill.execute",
            )

        return {
            "ok": True,
            "skill_name": skill_name,
            "action": action,
            "path": str(skill.get("path") or ""),
            "files": self._list_skill_files(document_path),
            "content": str(skill.get("body") or ""),
        }

    def _run_skill_script(self, args: dict[str, Any]) -> dict[str, object]:
        skill_name = str(args.get("skill_name") or "").strip()
        if not self._is_runtime_skill_enabled(skill_name):
            return self._tool_error(
                code="skill_disabled",
                message=f"disabled skill: {skill_name}",
                tool_name="skill.run_script",
            )

        skill = getattr(self.skill_registry, "_skills", {}).get(skill_name)
        if skill is None:
            return self._tool_error(
                code="skill_not_found",
                message=f"unknown skill: {skill_name}",
                tool_name="skill.run_script",
            )

        document_path = self._resolve_skill_document_path(skill.get("path"))
        if document_path is None or not self._is_allowed_skill_path(document_path):
            return self._tool_error(
                code="skill_path_not_allowed",
                message="skill document path must stay inside app/skills",
                tool_name="skill.run_script",
            )

        script_path = self._resolve_skill_resource_path(document_path, args.get("script_path"))
        skill_dir = document_path.parent.resolve(strict=False)
        scripts_dir = (skill_dir / "scripts").resolve(strict=False)
        if (
            script_path is None
            or not self._is_relative_to(script_path, scripts_dir)
            or script_path.suffix != ".py"
        ):
            return self._tool_error(
                code="skill_script_not_allowed",
                message="skill script path must be a Python file inside the selected skill's scripts directory",
                tool_name="skill.run_script",
            )
        if not script_path.exists() or not script_path.is_file():
            return self._tool_error(
                code="skill_script_not_found",
                message="skill script not found",
                tool_name="skill.run_script",
            )

        env = os.environ.copy()
        injected_secret_keys: list[str] = []
        secret_values = self._agent_secret_env_for_skill(skill_name)
        for key, value in secret_values.items():
            env[key] = value
            injected_secret_keys.append(key)

        required_secret_keys = self._string_list(args.get("required_secret_keys"))
        missing_secret_keys = [key for key in required_secret_keys if not env.get(key)]
        if missing_secret_keys:
            error_payload = self._tool_error(
                code="missing_skill_secrets",
                message="required skill secrets are not saved",
                tool_name="skill.run_script",
                details={"missing_secret_keys": missing_secret_keys},
            )
            error_payload["missing_secret_keys"] = missing_secret_keys
            return error_payload

        argv = [sys.executable, str(script_path), *self._string_list(args.get("argv"))]
        timeout_seconds = float(args.get("timeout_seconds") or 30.0)
        completed = subprocess.run(
            argv,
            cwd=str(skill_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        stdout, stdout_truncated = self._truncate_terminal_stream("stdout", completed.stdout)
        stderr, stderr_truncated = self._truncate_terminal_stream("stderr", completed.stderr)
        return {
            "ok": completed.returncode == 0,
            "skill_name": skill_name,
            "script_path": script_path.relative_to(skill_dir).as_posix(),
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "injected_secret_keys": sorted(injected_secret_keys),
        }

    def _agent_secret_env_for_skill(self, skill_name: str) -> dict[str, str]:
        profile_id = self._runtime_agent_profile_id()
        if not profile_id or not self.owner_key or self.agent_repository is None:
            return {}
        getter = getattr(self.agent_repository, "get_agent_secret_values", None)
        if not callable(getter):
            return {}
        values = getter(
            profile_id=profile_id,
            owner_key=self.owner_key,
            document_key="SECRETS.md",
            section_key=skill_name,
        )
        if not isinstance(values, dict):
            return {}
        section_values = values.get(skill_name)
        if not isinstance(section_values, dict):
            return {}
        return {
            str(key).strip(): str(value)
            for key, value in section_values.items()
            if str(key).strip() and str(value)
        }

    def _runtime_agent_profile_id(self) -> str | None:
        for key in ("agentProfileId", "agent_profile_id", "workAssigneeAgentId", "work_assignee_agent_id"):
            value = self._optional_text(self.runtime_context.get(key))
            if value:
                return value
        profile = self.runtime_context.get("targetAgentProfile")
        if isinstance(profile, dict):
            return self._optional_text(profile.get("profileId") or profile.get("profile_id"))
        return None

    def _runtime_skills(self) -> dict[str, Any]:
        skills = getattr(self.skill_registry, "_skills", {})
        allowed = self._runtime_enabled_skill_names()
        if allowed is None:
            return skills
        return {name: skills[name] for name in sorted(allowed) if name in skills}

    def _runtime_enabled_skill_names(self) -> set[str] | None:
        if "enabledSkillNames" not in self.runtime_context:
            return None
        return {
            str(item).strip()
            for item in list(self.runtime_context.get("enabledSkillNames") or [])
            if str(item).strip()
        }

    def _is_runtime_skill_enabled(self, skill_name: str) -> bool:
        allowed = self._runtime_enabled_skill_names()
        return allowed is None or skill_name in allowed

    def _is_inline_skill(self, skill: dict[str, Any]) -> bool:
        metadata = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
        has_inline_body = bool(str(skill.get("body") or "").strip()) and str(skill.get("path") or "").startswith(
            "custom://"
        )
        return has_inline_body or bool(metadata.get("documents"))

    def _list_inline_skill_files(self, skill: dict[str, Any]) -> list[str]:
        files = ["SKILL.md"] if str(skill.get("body") or "").strip() else []
        metadata = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
        raw_documents = metadata.get("documents") if isinstance(metadata.get("documents"), list) else []
        for document in raw_documents:
            if not isinstance(document, dict):
                continue
            path = str(document.get("documentKey") or document.get("document_key") or "").strip()
            if path and path not in files and not self._is_secret_skill_file(Path(path)):
                files.append(path)
        return files

    def _read_inline_skill_file(self, skill: dict[str, Any], raw_path: Any) -> dict[str, object] | None:
        path = str(raw_path or "").strip().replace("\\", "/")
        if not path:
            return None
        relative_path = Path(path)
        if relative_path.is_absolute() or ".." in relative_path.parts or self._is_secret_skill_file(relative_path):
            return self._tool_error(
                code="skill_file_not_allowed",
                message="skill file path must stay inside the selected skill",
                tool_name="skills.read_file",
            )
        if path == "SKILL.md":
            content = str(skill.get("body") or "")
            if not content:
                return None
            return {
                "ok": True,
                "skill_name": str(skill.get("name") or ""),
                "path": "SKILL.md",
                "content": content,
                "bytes_read": len(content.encode("utf-8")),
                "truncated": False,
            }
        metadata = skill.get("metadata") if isinstance(skill.get("metadata"), dict) else {}
        raw_documents = metadata.get("documents") if isinstance(metadata.get("documents"), list) else []
        for document in raw_documents:
            if not isinstance(document, dict):
                continue
            document_key = str(document.get("documentKey") or document.get("document_key") or "").strip()
            if document_key != path:
                continue
            content = str(document.get("content") or "")
            return {
                "ok": True,
                "skill_name": str(skill.get("name") or ""),
                "path": document_key,
                "content": content,
                "bytes_read": len(content.encode("utf-8")),
                "truncated": False,
            }
        return None

    def _record_session_message(self, args: dict[str, Any]) -> dict[str, object]:
        session_key = str(args.get("session_key") or "runtime-probe")
        latest = self.session_store.get_latest_session_by_key(session_key)
        if latest is None:
            session_id = new_id("session")
            self.session_store.create_session(
                session_id=session_id,
                session_key=session_key,
                source=str(args.get("source") or "runtime-probe"),
                title=str(args.get("title") or session_key),
            )
        else:
            session_id = str(latest["id"])

        message_id = self.session_store.append_message(
            session_id=session_id,
            role=str(args.get("role") or "user"),
            content=str(args.get("content") or ""),
        )
        return {
            "session_id": session_id,
            "message_id": message_id,
            "session_key": session_key,
        }

    def _search_sessions(self, args: dict[str, Any]) -> dict[str, object]:
        limit = int(args.get("limit") or 5)
        if not self.owner_key:
            return self._tool_error(
                code="owner_required",
                message="session.search requires a bound owner",
                tool_name="session.search",
            )
        results = self.session_store.search_transcript_sessions(
            str(args.get("query") or ""),
            owner_key=self.owner_key,
            limit=limit,
        )
        return {
            "count": len(results),
            "items": results,
        }

    def _todo(self, args: dict[str, Any]) -> dict[str, object]:
        if "todos" in args:
            self._todo_items = self._write_todos(list(args.get("todos") or []), merge=bool(args.get("merge", False)))
        return {
            "todos": [dict(item) for item in self._todo_items],
            "summary": self._todo_summary(self._todo_items),
        }

    def _read_file(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_file_tool_handler("read_file_handler", args)

    def _write_file(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_file_tool_handler("write_file_handler", args)

    def _patch_file(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_file_tool_handler("patch_handler", args)

    def _search_files(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_file_tool_handler("search_files_handler", args)

    def _run_http_get(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_external_tool_handler("app.tools.web.web_tools", "http_get_handler", args)

    def _read_tool_result(self, args: dict[str, Any]) -> dict[str, Any]:
        return tool_result_read_handler(args)

    def _send_mattermost_message(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_external_tool_handler(
            "app.tools.messaging.mattermost_tool",
            "send_mattermost_message_handler",
            args,
        )

    def _execute_notion(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_external_tool_handler(
            "app.tools.notion.notion_tool",
            "execute_notion_handler",
            args,
        )

    def _execute_gmail(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_external_tool_handler(
            "app.tools.gmail.gmail_tool",
            "execute_gmail_handler",
            args,
        )

    def _execute_health(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_external_tool_handler(
            "app.tools.health.health_tool",
            "execute_health_handler",
            args,
        )

    def _list_design_presets(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_external_tool_handler(
            "app.tools.design.design_tool",
            "list_design_presets_handler",
            args,
        )

    def _read_design_preset(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._run_external_tool_handler(
            "app.tools.design.design_tool",
            "read_design_preset_handler",
            args,
        )

    def _create_prototype_artifact(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.prototype.prototype_tool import normalize_prototype_files, prototype_tool_error
        from app.tools.prototype.prototype_validation import (
            validate_prototype_preview_files,
            validation_issues_payload,
        )

        if self.prototype_repository is None:
            return prototype_tool_error("prototype_repository_unavailable", "prototype artifact storage is not configured.")

        session_id = self._optional_text(
            args.get("_trusted_session_id")
            or self.runtime_context.get("sessionId")
            or self.runtime_context.get("session_id")
        )
        owner_key = self._optional_text(args.get("_trusted_owner_key") or self.owner_key)
        if not session_id or not owner_key:
            return prototype_tool_error(
                "prototype_context_required",
                "prototype artifact creation requires a bound session and owner.",
            )

        files = normalize_prototype_files(args.get("files"))
        if not files:
            return prototype_tool_error("prototype_files_required", "prototype files are required.")

        title = self._optional_text(args.get("title")) or "프로토타입"
        framework = self._optional_text(args.get("framework")) or "react"
        styling = self._optional_text(args.get("styling")) or "css"
        entry_file = self._optional_text(args.get("entryFile") or args.get("entry_file")) or _default_entry_file(files)
        design_preset_id = self._optional_text(args.get("designPresetId") or args.get("design_preset_id"))
        if not design_preset_id:
            active_record = self.prototype_repository.get_active_artifact(session_id=session_id, owner_key=owner_key)
            if active_record is not None:
                design_preset_id = self._optional_text(active_record.get("design_preset_id"))
        if not design_preset_id:
            return prototype_tool_error(
                "design_preset_required",
                "DESIGN.md prototype creation requires designPresetId. Call design.list_presets, "
                "read one preset with design.read_preset, then retry with that exact preset_id.",
            )
        validation_issues = validate_prototype_preview_files(files, entry_file=entry_file, framework=framework)
        if validation_issues:
            issues_payload = validation_issues_payload(validation_issues)
            issue_summary = "; ".join(issue["message"] for issue in issues_payload[:3])
            return prototype_tool_error(
                "prototype_validation_failed",
                "Prototype preview validation failed before saving. Fix the files and call "
                f"prototype.create_artifact again. {issue_summary}",
                details={"issues": issues_payload},
            )
        summary = self._optional_text(args.get("summary")) or "프로토타입 버전을 생성했습니다."
        metadata = args.get("metadata") if isinstance(args.get("metadata"), dict) else {}
        task_run_id = self._optional_text(self.runtime_context.get("taskRunId") or self.runtime_context.get("task_run_id"))
        prompt_message_id = self._optional_text(
            self.runtime_context.get("promptMessageId") or self.runtime_context.get("prompt_message_id")
        )

        saved = self.prototype_repository.create_artifact_version(
            session_id=session_id,
            owner_key=owner_key,
            title=title,
            framework=framework,
            styling=styling,
            design_preset_id=design_preset_id,
            entry_file=entry_file,
            files=files,
            summary=summary,
            task_run_id=task_run_id,
            prompt_message_id=prompt_message_id,
            metadata=metadata,
        )
        return {
            "ok": True,
            "activeArtifactId": saved["artifact_id"],
            "activeArtifactVersionId": saved["version_id"],
            "artifactId": saved["artifact_id"],
            "versionId": saved["version_id"],
            "versionNumber": saved["version_number"],
            "framework": saved["framework"],
            "styling": saved["styling"],
            "designPresetId": saved.get("design_preset_id"),
            "entryFile": saved["entry_file"],
            "previewMode": "sandpack" if saved["framework"] == "react" else "iframe",
            "fileCount": len(saved["files"]),
            "summary": saved.get("summary") or "",
        }

    def _get_active_prototype_artifact(self, args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.prototype.prototype_tool import prototype_tool_error

        _ = args
        if self.prototype_repository is None:
            return prototype_tool_error("prototype_repository_unavailable", "prototype artifact storage is not configured.")

        session_id = self._optional_text(
            self.runtime_context.get("sessionId") or self.runtime_context.get("session_id")
        )
        owner_key = self._optional_text(self.owner_key)
        if not session_id or not owner_key:
            return prototype_tool_error(
                "prototype_context_required",
                "prototype artifact lookup requires a bound session and owner.",
            )

        record = self.prototype_repository.get_active_artifact(session_id=session_id, owner_key=owner_key)
        if record is None:
            return {
                "ok": True,
                "artifact": None,
                "content": json.dumps({"ok": True, "artifact": None}, ensure_ascii=False),
            }

        artifact = {
            "artifactId": str(record["artifact_id"]),
            "versionId": str(record["version_id"]),
            "sessionId": str(record["session_id"]),
            "title": str(record.get("title") or "프로토타입"),
            "framework": str(record.get("framework") or "react"),
            "styling": str(record.get("styling") or "css"),
            "designPresetId": record.get("design_preset_id"),
            "entryFile": str(record.get("entry_file") or "/src/App.tsx"),
            "versionNumber": int(record.get("version_number") or 1),
            "summary": str(record.get("summary") or ""),
            "files": record.get("files") if isinstance(record.get("files"), dict) else {},
        }
        return {
            "ok": True,
            "artifact": artifact,
            "content": json.dumps(
                {
                    "ok": True,
                    "artifactId": artifact["artifactId"],
                    "versionId": artifact["versionId"],
                    "title": artifact["title"],
                    "fileCount": len(artifact["files"]),
                },
                ensure_ascii=False,
            ),
        }

    @staticmethod
    def _run_file_tool_handler(handler_name: str, args: dict[str, Any]) -> dict[str, Any]:
        from app.tools.file import file_tools

        # 파일 도구 구현은 별도 모듈 소유라 실행 시점에만 함수 존재를 확인한다.
        handler = getattr(file_tools, handler_name)
        result = handler(dict(args))
        if isinstance(result, dict):
            return result
        return {"ok": True, "result": result}

    @staticmethod
    def _run_external_tool_handler(module_name: str, handler_name: str, args: dict[str, Any]) -> dict[str, Any]:
        # 검색/외부 연동 모듈은 선택 의존성이 많아 호출 시점에만 불러온다.
        import importlib

        module = importlib.import_module(module_name)
        handler = getattr(module, handler_name)
        result = handler(dict(args))
        if isinstance(result, dict):
            return result
        return {"ok": True, "result": result}

    def _write_todos(self, todos: list[Any], *, merge: bool) -> list[dict[str, str]]:
        normalized = [
            self._normalize_todo_item(item, index=index)
            for index, item in enumerate(todos)
            if isinstance(item, dict)
        ]
        if not merge:
            return self._dedupe_todos(normalized)

        existing = {item["id"]: dict(item) for item in self._todo_items}
        order = [item["id"] for item in self._todo_items]
        for item in normalized:
            if item["id"] not in existing:
                order.append(item["id"])
            existing[item["id"]] = item
        return [existing[item_id] for item_id in order if item_id in existing]

    def _delegate_task(self, args: dict[str, Any]) -> dict[str, Any]:
        """worker 위임 요청을 실행 엔진이 해석할 수 있는 handoff 계약으로 정규화한다."""

        goal = str(args.get("goal") or "").strip()
        context = args.get("context")
        profile_key = self._optional_text(args.get("profile_key")) or "worker.default"
        toolsets = self._normalize_delegate_toolsets(args.get("toolsets"))
        max_iterations = self._optional_positive_int(args.get("max_iterations"))
        input_payload = {
            "prompt": goal,
            "goal": goal,
            "context": context if context is not None else {},
            "enabled_toolsets": toolsets,
            "toolsets": toolsets,
            "profile_key": profile_key,
        }
        if max_iterations is not None:
            input_payload["max_iterations"] = max_iterations

        child_session = {
            "goal": goal,
            "context": context if context is not None else {},
            "toolsets": toolsets,
            "max_iterations": max_iterations,
            "role": "worker",
            "profile_key": profile_key,
            "agent_id": self._optional_text(args.get("agent_id")),
            "tasks": args.get("tasks") if isinstance(args.get("tasks"), list) else [],
            "acp_command": self._optional_text(args.get("acp_command")),
            "acp_args": dict(args.get("acp_args") or {}) if isinstance(args.get("acp_args"), dict) else {},
            "input_payload": input_payload,
            "metadata": {
                "profile_key": profile_key,
            },
        }
        if max_iterations is None:
            child_session.pop("max_iterations", None)

        # parent transcript에는 수락 메시지만 남기고, worker 실행 계약은 별도 필드로 넘긴다.
        return {
            "ok": True,
            "content": f"worker delegation accepted: {goal}",
            "child_session": child_session,
        }

    def _session_agent_task(self, args: dict[str, Any]) -> dict[str, Any]:
        """세션 보드에 보이는 하위 작업을 만들고 실행 엔진이 깨울 계약을 만든다."""

        if self.work_repository is None or self.agent_repository is None:
            return self._tool_error(
                code="work_runtime_unavailable",
                message="work runtime repositories are not configured",
                tool_name="session_agent_task",
            )

        context = dict(self.runtime_context or {})
        parent_work_id = self._optional_text(context.get("workId") or context.get("work_id"))
        if not parent_work_id:
            if context.get("allowSessionAgentRootWork") is True or context.get("allow_session_agent_root_work") is True:
                parent = self._create_session_agent_root_work(args=args, context=context)
                if parent is None:
                    return self._tool_error(
                        code="work_context_required",
                        message="session_agent_task requires a connected team lead work item",
                        tool_name="session_agent_task",
                    )
                self.runtime_context["workId"] = parent.work_id
                self.runtime_context["workIdentifier"] = parent.identifier
                self.runtime_context["workAssigneeAgentId"] = parent.assignee_agent_id
                root_claim_error = self._mark_session_agent_root_run_started(parent.work_id)
                if root_claim_error is not None:
                    return root_claim_error
                parent_work_id = parent.work_id
            else:
                return self._tool_error(
                    code="work_context_required",
                    message="session_agent_task requires a connected team lead work item",
                    tool_name="session_agent_task",
                )
        else:
            parent = self.work_repository.get_work(parent_work_id)
            if parent is None:
                return self._tool_error(
                    code="work_not_found",
                    message="connected work item was not found",
                    tool_name="session_agent_task",
                )
        if str(parent.assignee_agent_id or "CEO") != "CEO":
            return self._tool_error(
                code="ceo_work_required",
                message="only team-lead-owned work can create child work for session agents",
                tool_name="session_agent_task",
            )

        title = str(args.get("title") or "").strip()
        instruction = str(args.get("instruction") or "").strip()
        description = str(args.get("description") or instruction or title).strip()
        workflow_execution = self._strict_workflow_execution(context)
        if workflow_execution is not None:
            return self._session_agent_existing_work_task(
                args=args,
                context=context,
                parent=parent,
                workflow_execution=workflow_execution,
                title=title,
                instruction=instruction,
                description=description,
            )
        required_skill_names = self._required_session_agent_skill_names(
            args=args,
            context=context,
            text_parts=[
                title,
                instruction,
                description,
                self._optional_text(args.get("expectedDeliverable") or args.get("expected_deliverable")) or "",
            ],
        )
        profile = self._resolve_session_agent_profile(
            session_id=parent.session_id,
            owner_key=parent.owner_key,
            assignee_agent_id=self._optional_text(args.get("assigneeAgentId") or args.get("assignee_agent_id")),
            assignee_hint=self._optional_text(args.get("assigneeHint") or args.get("assignee_hint")),
            required_skill_names=required_skill_names,
        )
        if profile is None:
            return self._tool_error(
                code="session_agent_not_found",
                message="no available session agent was found for this work",
                tool_name="session_agent_task",
            )
        missing_skill_names = self._missing_profile_skills(profile, required_skill_names)
        if missing_skill_names:
            config = dict(profile.get("config_snapshot") or {})
            profile_name = str(config.get("name") or profile.get("profile_key") or profile.get("profile_id") or "session agent")
            profile_id = str(profile.get("profile_id") or "").strip()
            return self._tool_error(
                code="session_agent_capability_mismatch",
                message=f"{profile_name} does not have required skills: {', '.join(missing_skill_names)}",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "requiredSkillNames": required_skill_names,
                    "missingSkillNames": missing_skill_names,
                    "agent": {
                        "profileId": profile_id,
                        "name": profile_name,
                        "skills": self._profile_skill_names(profile),
                    },
                },
            )

        profile_id = str(profile.get("profile_id") or "").strip()
        child_client_request_id = self._session_agent_child_client_request_id(
            context=context,
            parent_work_id=parent.work_id,
            profile_id=profile_id,
            title=title,
            instruction=instruction,
            description=description,
            args=args,
            required_skill_names=required_skill_names,
        )
        existing_child = self.work_repository.get_work_by_client_request_id(parent.session_id, child_client_request_id)
        child = WorkService(self.work_repository).create_from_payload(
            session_id=parent.session_id,
            owner_key=parent.owner_key,
            owner_user_id=parent.owner_user_id,
            payload={
                "title": title,
                "description": description,
                "rawUserInput": instruction,
                "executionInstruction": instruction,
                "assigneeAgentId": profile_id,
                "parentId": parent.work_id,
                "expectedDeliverable": self._optional_text(args.get("expectedDeliverable") or args.get("expected_deliverable")),
                "acceptanceCriteria": self._string_list(args.get("acceptanceCriteria") or args.get("acceptance_criteria")),
                "constraints": self._string_list(args.get("constraints")),
                "labelNames": self._string_list(args.get("labelNames") or args.get("label_names")),
                "metadata": {
                    "createdByWorkId": parent.work_id,
                    "createdByTool": "session_agent_task",
                    "clientRequestId": child_client_request_id,
                },
            },
            client_request_id=child_client_request_id,
        )
        block_parent_until_done = args.get("blockParentUntilDone", args.get("block_parent_until_done"))
        if block_parent_until_done is True and existing_child is None:
            self.work_repository.add_relation(
                source_work_id=child.work_id,
                target_work_id=parent.work_id,
                relation_type="blocks",
            )
        if existing_child is None:
            self.work_repository.add_comment(
                WorkComment(
                    comment_id=new_id("comment"),
                    work_id=parent.work_id,
                    author_type="system",
                    body=f"{child.identifier} 하위 작업을 만들고 세션 에이전트에게 배정했습니다.",
                    metadata={
                        "childWorkId": child.work_id,
                        "assigneeAgentId": profile_id,
                        "clientRequestId": child_client_request_id,
                    },
                )
            )
        config = dict(profile.get("config_snapshot") or {})
        return {
            "ok": True,
            "content": (
                f"{child.identifier} child work already accepted: {child.title}"
                if existing_child is not None
                else f"{child.identifier} child work accepted: {child.title}"
            ),
            "parent_work": self._work_tool_payload(parent),
            "child_work": self._work_tool_payload(child),
            "agent": {
                "profileId": profile_id,
                "name": str(config.get("name") or profile.get("profile_key") or profile_id),
                "role": str(config.get("role") or profile.get("agent_type") or "user_subagent"),
            },
            "reused": existing_child is not None,
            "startExecution": existing_child is None,
        }

    def _session_agent_existing_work_task(
        self,
        *,
        args: dict[str, Any],
        context: dict[str, Any],
        parent,
        workflow_execution: dict[str, Any],
        title: str,
        instruction: str,
        description: str,
    ) -> dict[str, Any]:
        """워크플로우 strict 모드에서는 이미 생성된 child WorkItem만 실행한다."""

        child = self._resolve_strict_workflow_child(parent=parent, workflow_execution=workflow_execution, args=args)
        if isinstance(child, dict):
            return child
        blocking_error = self._strict_workflow_child_blocking_error(child)
        if blocking_error is not None:
            return blocking_error
        if child.status in {"done", "cancelled"}:
            return self._tool_error(
                code="workflow_child_already_terminal",
                message="selected workflow child work is already terminal",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "childWorkId": child.work_id,
                    "status": child.status,
                    "allowedChildren": self._strict_workflow_allowed_children(parent=parent, workflow_execution=workflow_execution),
                },
            )

        required_skill_names = self._required_session_agent_skill_names(
            args=args,
            context=context,
            text_parts=[
                title or child.title,
                instruction or child.execution_instruction or "",
                description or child.description or "",
                self._optional_text(args.get("expectedDeliverable") or args.get("expected_deliverable")) or "",
            ],
        )
        profile = self._resolve_session_agent_profile(
            session_id=parent.session_id,
            owner_key=parent.owner_key,
            assignee_agent_id=child.assignee_agent_id,
            assignee_hint=self._optional_text(args.get("assigneeHint") or args.get("assignee_hint")),
            required_skill_names=required_skill_names,
        )
        if profile is None:
            return self._tool_error(
                code="session_agent_not_found",
                message="no available session agent was found for this workflow child work",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "childWorkId": child.work_id,
                    "allowedChildren": self._strict_workflow_allowed_children(parent=parent, workflow_execution=workflow_execution),
                },
            )
        missing_skill_names = self._missing_profile_skills(profile, required_skill_names)
        if missing_skill_names:
            config = dict(profile.get("config_snapshot") or {})
            profile_name = str(config.get("name") or profile.get("profile_key") or profile.get("profile_id") or "session agent")
            profile_id = str(profile.get("profile_id") or "").strip()
            return self._tool_error(
                code="session_agent_capability_mismatch",
                message=f"{profile_name} does not have required skills: {', '.join(missing_skill_names)}",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "requiredSkillNames": required_skill_names,
                    "missingSkillNames": missing_skill_names,
                    "agent": {
                        "profileId": profile_id,
                        "name": profile_name,
                        "skills": self._profile_skill_names(profile),
                    },
                },
            )

        config = dict(profile.get("config_snapshot") or {})
        profile_id = str(profile.get("profile_id") or child.assignee_agent_id or "").strip()
        active_run_id = self._optional_text(getattr(child, "active_run_id", None))
        return {
            "ok": True,
            "content": (
                f"{child.identifier} workflow child work is already running: {child.title}"
                if active_run_id
                else f"{child.identifier} workflow child work accepted: {child.title}"
            ),
            "parent_work": self._work_tool_payload(parent),
            "child_work": self._work_tool_payload(child),
            "agent": {
                "profileId": profile_id,
                "name": str(config.get("name") or profile.get("profile_key") or profile_id),
                "role": str(config.get("role") or profile.get("agent_type") or "user_subagent"),
            },
            "reused": True,
            "startExecution": active_run_id is None,
            "workflowExecution": {
                "mode": "strict_reuse_children",
                "rootWorkId": parent.work_id,
                "childWorkIds": self._strict_workflow_child_ids(workflow_execution),
                "childrenBySlotKey": self._strict_workflow_slot_map(workflow_execution),
            },
        }

    def _resolve_strict_workflow_child(self, *, parent, workflow_execution: dict[str, Any], args: dict[str, Any]):
        child_work_id = self._optional_text(args.get("childWorkId") or args.get("child_work_id"))
        slot_key = self._optional_text(args.get("workflowSlotKey") or args.get("workflow_slot_key"))
        slot_map = self._strict_workflow_slot_map(workflow_execution)
        if not child_work_id and slot_key:
            child_work_id = slot_map.get(slot_key)
        if not child_work_id:
            return self._tool_error(
                code="workflow_child_reuse_required",
                message="workflow execution must choose one of the already-created child work ids",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "allowedChildren": self._strict_workflow_allowed_children(parent=parent, workflow_execution=workflow_execution),
                },
            )
        allowed_ids = set(self._strict_workflow_child_ids(workflow_execution))
        if child_work_id not in allowed_ids:
            return self._tool_error(
                code="workflow_child_not_allowed",
                message="selected child work id is not allowed in this workflow execution",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "childWorkId": child_work_id,
                    "allowedChildren": self._strict_workflow_allowed_children(parent=parent, workflow_execution=workflow_execution),
                },
            )
        child = self.work_repository.get_work(child_work_id) if self.work_repository is not None else None
        if child is None:
            return self._tool_error(
                code="workflow_child_not_found",
                message="selected workflow child work was not found",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "childWorkId": child_work_id,
                    "allowedChildren": self._strict_workflow_allowed_children(parent=parent, workflow_execution=workflow_execution),
                },
            )
        if child.parent_id != parent.work_id:
            return self._tool_error(
                code="workflow_child_parent_mismatch",
                message="selected workflow child work is not under the current root work",
                tool_name="session_agent_task",
                details={
                    "recoverable": True,
                    "childWorkId": child_work_id,
                    "rootWorkId": parent.work_id,
                    "actualParentId": child.parent_id,
                    "allowedChildren": self._strict_workflow_allowed_children(parent=parent, workflow_execution=workflow_execution),
                },
            )
        return child

    def _strict_workflow_child_blocking_error(self, child) -> dict[str, Any] | None:
        if self.work_repository is None:
            return None
        list_relations = getattr(self.work_repository, "list_relations", None)
        if not callable(list_relations):
            return None
        blockers: list[dict[str, Any]] = []
        for relation in list_relations(child.work_id):
            if relation.relation_type != "blocks" or relation.target_work_id != child.work_id:
                continue
            blocker = self.work_repository.get_work(relation.source_work_id)
            if blocker is not None and not self._strict_workflow_blocker_allows_handoff(blocker):
                blockers.append(
                    {
                        "workId": blocker.work_id,
                        "identifier": blocker.identifier,
                        "title": blocker.title,
                        "status": blocker.status,
                    }
                )
        if not blockers:
            return None
        return self._tool_error(
            code="workflow_child_blocked_by_predecessor",
            message="selected workflow child work has unfinished blockers",
            tool_name="session_agent_task",
            details={
                "recoverable": True,
                "childWorkId": child.work_id,
                "blockers": blockers,
            },
        )

    def _strict_workflow_blocker_allows_handoff(self, blocker) -> bool:
        if blocker.status == "done":
            return True
        if blocker.active_run_id is not None or blocker.latest_run_id is None:
            return False
        list_runs = getattr(self.work_repository, "list_runs", None) if self.work_repository is not None else None
        if not callable(list_runs):
            return False
        for run in list_runs(blocker.work_id, limit=5, offset=0):
            if run.task_run_id == blocker.latest_run_id:
                return run.status == "COMPLETED"
        return False

    def _strict_workflow_allowed_children(self, *, parent, workflow_execution: dict[str, Any]) -> list[dict[str, Any]]:
        children: list[dict[str, Any]] = []
        slot_by_work_id = {work_id: slot for slot, work_id in self._strict_workflow_slot_map(workflow_execution).items()}
        for child_work_id in self._strict_workflow_child_ids(workflow_execution):
            child = self.work_repository.get_work(child_work_id) if self.work_repository is not None else None
            if child is None or child.parent_id != parent.work_id:
                continue
            children.append(
                {
                    "workId": child.work_id,
                    "identifier": child.identifier,
                    "title": child.title,
                    "status": child.status,
                    "assigneeAgentId": child.assignee_agent_id,
                    "workflowSlotKey": slot_by_work_id.get(child.work_id),
                }
            )
        return children

    @staticmethod
    def _strict_workflow_execution(context: dict[str, Any]) -> dict[str, Any] | None:
        candidate = context.get("workflowExecution") or context.get("workflow_execution")
        if not isinstance(candidate, dict):
            return None
        mode = str(candidate.get("mode") or "").strip()
        return candidate if mode == "strict_reuse_children" else None

    @staticmethod
    def _strict_workflow_child_ids(workflow_execution: dict[str, Any]) -> list[str]:
        raw = workflow_execution.get("childWorkIds") or workflow_execution.get("child_work_ids") or []
        if not isinstance(raw, list):
            return []
        return [str(item).strip() for item in raw if str(item).strip()]

    @staticmethod
    def _strict_workflow_slot_map(workflow_execution: dict[str, Any]) -> dict[str, str]:
        raw = workflow_execution.get("childrenBySlotKey") or workflow_execution.get("children_by_slot_key") or {}
        if not isinstance(raw, dict):
            return {}
        return {str(key).strip(): str(value).strip() for key, value in raw.items() if str(key).strip() and str(value).strip()}

    def _create_session_agent_root_work(self, *, args: dict[str, Any], context: dict[str, Any]):
        session_id = self._optional_text(context.get("sessionId") or context.get("session_id"))
        owner_key = self._optional_text(context.get("ownerKey") or context.get("owner_key"))
        if not session_id or not owner_key:
            return None
        owner_user_id = self._optional_int(context.get("ownerUserId") or context.get("owner_user_id"))
        prompt = str(context.get("prompt") or "").strip()
        title = str(args.get("title") or prompt or "세션 에이전트 작업").strip()
        description = str(prompt or args.get("description") or title).strip()
        client_request_id = self._session_agent_root_client_request_id(
            context=context,
            title=title,
            description=description,
            prompt=prompt,
        )
        return WorkService(self.work_repository).create_from_payload(
            session_id=session_id,
            owner_key=owner_key,
            owner_user_id=owner_user_id,
            payload={
                "title": title,
                "description": description,
                "rawUserInput": prompt,
                "executionInstruction": description,
                "assigneeAgentId": "CEO",
                "source": "session_agent_task",
                "metadata": {
                    "createdByTool": "session_agent_task",
                    "clientRequestId": client_request_id,
                },
            },
            client_request_id=client_request_id,
        )

    def _mark_session_agent_root_run_started(self, work_id: str) -> dict[str, Any] | None:
        task_run_id = self._optional_text(self.runtime_context.get("taskRunId") or self.runtime_context.get("task_run_id"))
        if not task_run_id:
            return None
        try:
            WorkService(self.work_repository).mark_run_started(work_id=work_id, task_run_id=task_run_id)
        except WorkRunClaimConflict:
            return self._tool_error(
                code="work_run_conflict",
                message="session agent root work already has an active run",
                tool_name="session_agent_task",
                details={"workId": work_id, "taskRunId": task_run_id},
            )
        return None

    @classmethod
    def _session_agent_root_client_request_id(
        cls,
        *,
        context: dict[str, Any],
        title: str,
        description: str,
        prompt: str,
    ) -> str:
        turn_id = cls._session_agent_turn_id(context)
        digest = cls._stable_digest({"title": title, "description": description, "prompt": prompt})
        return f"session-agent-root:v1:{turn_id}:{digest}"

    @classmethod
    def _session_agent_child_client_request_id(
        cls,
        *,
        context: dict[str, Any],
        parent_work_id: str,
        profile_id: str,
        title: str,
        instruction: str,
        description: str,
        args: dict[str, Any],
        required_skill_names: list[str],
    ) -> str:
        turn_id = cls._session_agent_turn_id(context)
        digest = cls._stable_digest(
            {
                "parentWorkId": parent_work_id,
                "profileId": profile_id,
                "title": title,
                "instruction": instruction,
                "description": description,
                "expectedDeliverable": args.get("expectedDeliverable") or args.get("expected_deliverable"),
                "acceptanceCriteria": args.get("acceptanceCriteria") or args.get("acceptance_criteria"),
                "constraints": args.get("constraints"),
                "requiredSkillNames": required_skill_names,
            }
        )
        return f"session-agent-child:v1:{turn_id}:{parent_work_id}:{profile_id}:{digest}"

    @staticmethod
    def _session_agent_turn_id(context: dict[str, Any]) -> str:
        # 같은 사용자 턴이 재실행되어도 같은 work를 가리키게 하는 안정 키다.
        # 값이 없는 오래된 호출은 task_run_id를 마지막 경계로 쓰고, 그래도 없으면 prompt hash로 떨어진다.
        for key in (
            "promptMessageId",
            "prompt_message_id",
            "client_message_id",
            "clientMessageId",
            "retry_source_message_id",
            "after_user_message_version",
            "completion_expected_version",
            "taskRunId",
            "task_run_id",
        ):
            value = str(context.get(key) or "").strip()
            if value:
                return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value)[:120]
        return LocalToolRuntime._stable_digest({"prompt": context.get("prompt") or ""})

    @staticmethod
    def _stable_digest(value: Any) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:16]

    def _run_terminal_command(self, args: dict[str, Any]) -> dict[str, Any]:
        argv = list(args.get("argv") or []) or None
        command = args.get("command")
        blocked = self._blocked_terminal_command(command=command, argv=argv)
        if blocked is not None:
            return blocked

        cwd = self._resolve_terminal_cwd(args.get("cwd"))
        timeout_seconds = float(args.get("timeout_seconds") or 15.0)

        if argv:
            completed = subprocess.run(
                argv,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
            executed = argv
        elif command:
            completed = subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
                shell=True,
            )
            executed = [command]
        else:
            raise ValueError("command or argv is required")

        stdout, stdout_truncated = self._truncate_terminal_stream("stdout", completed.stdout)
        stderr, stderr_truncated = self._truncate_terminal_stream("stderr", completed.stderr)
        return {
            "command": executed,
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
        }

    def _bind_trusted_runtime_args(self, *, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        trusted_args = dict(args)
        if tool_name in FILE_TOOL_NAMES:
            # 모델이 workspace_root를 넓혀도 서버가 바인딩한 루트만 사용한다.
            trusted_args["workspace_root"] = str(self.workspace_root)
        if tool_name == "mattermost.send":
            # 사용자 식별자는 모델 인자가 아니라 서버가 바인딩한 owner_key만 신뢰한다.
            trusted_args["_trusted_user_id"] = self.owner_key
        if tool_name == "notion.execute":
            # 사용자 식별자는 모델 인자가 아니라 서버가 바인딩한 owner_key만 신뢰한다.
            trusted_args.pop("userId", None)
            trusted_args.pop("user_id", None)
            trusted_args["_trusted_user_id"] = self.owner_key
        if tool_name == "gmail.execute":
            # 사용자 식별자는 모델 인자가 아니라 서버가 바인딩한 owner_key만 신뢰한다.
            trusted_args.pop("userId", None)
            trusted_args.pop("user_id", None)
            trusted_args["_trusted_user_id"] = self.owner_key
        if tool_name == "health.execute":
            # 사용자 식별자는 모델 인자가 아니라 서버가 바인딩한 owner_key만 신뢰한다.
            trusted_args.pop("userId", None)
            trusted_args.pop("user_id", None)
            trusted_args["_trusted_user_id"] = self.owner_key
        if tool_name == "prototype.create_artifact":
            trusted_args["_trusted_owner_key"] = self.owner_key
            trusted_args["_trusted_session_id"] = self._optional_text(
                self.runtime_context.get("sessionId") or self.runtime_context.get("session_id")
            )
        return trusted_args

    def _resolve_terminal_cwd(self, value: Any) -> str:
        raw_value = str(value or "").strip()
        candidate = Path(raw_value).expanduser() if raw_value else self.workspace_root
        resolved = candidate if candidate.is_absolute() else self.workspace_root / candidate
        resolved = resolved.resolve(strict=False)
        # terminal.run도 workspace guard를 적용해 작업 디렉터리가 루트 밖으로 나가지 않게 한다.
        if not self._is_relative_to(resolved, self.workspace_root):
            raise PermissionError("terminal cwd must stay inside the workspace")
        return str(resolved)

    def _blocked_terminal_command(self, *, command: Any, argv: list[Any] | None) -> dict[str, Any] | None:
        command_text = self._terminal_command_text(command=command, argv=argv)
        if not command_text:
            return None

        normalized = re.sub(r"\s+", " ", command_text).strip().lower()
        blocked_patterns = (
            r"\bgit\s+reset\s+--hard\b",
            r"\bgit\s+clean\s+-[a-z]*[fd][a-z]*\b",
            r"\brm\s+-[a-z]*r[a-z]*f[a-z]*\s+(/|\\|[a-z]:\\|\*|\.)(\s|$)",
            r"\bdel\s+/(s|q)\b",
            r"\brmdir\s+/(s|q)\b",
            r"\bremove-item\b\s+\.\s+.*-force\b.*-recurse\b",
            r"\bremove-item\b\s+\.\s+.*-recurse\b.*-force\b",
            r"\bmkfs(\.| )",
            r"\bformat\s+[a-z]:",
        )
        if not any(re.search(pattern, normalized) for pattern in blocked_patterns):
            return None

        executed = list(argv) if argv else [str(command)]
        payload = {
            "error": {
                "code": "blocked_command",
                "message": "dangerous terminal command blocked before execution",
                "tool_name": "terminal.run",
            }
        }
        return {
            "ok": False,
            **payload,
            "command": executed,
            "returncode": None,
            "stdout": "",
            "stderr": "",
            "content": json.dumps(payload, ensure_ascii=False),
        }

    @staticmethod
    def _terminal_command_text(*, command: Any, argv: list[Any] | None) -> str:
        if argv:
            return " ".join(str(item) for item in argv)
        if isinstance(command, str):
            return command
        return ""

    @staticmethod
    def _truncate_terminal_stream(field_name: str, value: str) -> tuple[str, bool]:
        if len(value) <= MAX_TERMINAL_STREAM_CHARS:
            return value, False
        marker = f"\n[truncated: {field_name} exceeded {MAX_TERMINAL_STREAM_CHARS} chars]\n"
        keep = max(0, MAX_TERMINAL_STREAM_CHARS - len(marker))
        return value[:keep] + marker, True

    @staticmethod
    def _resolve_workspace_root(value: str | os.PathLike[str] | None = None) -> Path:
        raw_root = value or os.environ.get("HEYGENT_WORKSPACE_ROOT") or os.environ.get("TERMINAL_CWD") or os.getcwd()
        return Path(str(raw_root)).expanduser().resolve()

    @staticmethod
    def _resolve_skill_document_path(value: Any) -> Path | None:
        raw_value = str(value or "").strip()
        if not raw_value:
            return None
        candidate = Path(raw_value).expanduser()
        if not candidate.is_absolute():
            candidate = Path.cwd() / candidate
        return candidate.resolve(strict=False)

    @classmethod
    def _is_allowed_skill_path(cls, path: Path) -> bool:
        return cls._is_relative_to(
            path.resolve(strict=False),
            cls._default_skills_root().resolve(strict=False),
        )

    @staticmethod
    def _default_skills_root() -> Path:
        return Path(__file__).resolve().parents[2] / "skills"

    @classmethod
    def _list_skill_files(cls, document_path: Path | None) -> list[str]:
        if document_path is None:
            return []
        skill_dir = document_path.parent
        if not skill_dir.exists() or not skill_dir.is_dir():
            return []

        files: list[str] = []
        for path in sorted(item for item in skill_dir.rglob("*") if item.is_file()):
            relative_path = path.relative_to(skill_dir)
            if cls._is_secret_skill_file(relative_path):
                continue
            files.append(relative_path.as_posix())
            if len(files) >= 200:
                break
        return files

    @staticmethod
    def _is_secret_skill_file(relative_path: Path) -> bool:
        return any(SECRET_FILE_NAME_PATTERN.search(part) for part in relative_path.parts)

    @classmethod
    def _resolve_skill_resource_path(cls, document_path: Path, value: Any) -> Path | None:
        raw_value = str(value or "").strip().replace("\\", "/")
        if not raw_value:
            return None
        relative_path = Path(raw_value)
        if relative_path.is_absolute() or cls._is_secret_skill_file(relative_path):
            return None
        skill_dir = document_path.parent.resolve(strict=False)
        candidate = (skill_dir / relative_path).resolve(strict=False)
        if not cls._is_relative_to(candidate, skill_dir):
            return None
        return candidate

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
        except ValueError:
            return False
        return True

    @staticmethod
    def _normalize_todo_item(item: dict[str, Any], *, index: int) -> dict[str, str]:
        item_id = str(item.get("id") or item.get("key") or f"todo-{index + 1}").strip() or f"todo-{index + 1}"
        content = str(item.get("content") or item.get("title") or item_id).strip() or item_id
        status = str(item.get("status") or "pending").strip().lower() or "pending"
        if status == "canceled":
            status = "cancelled"
        if status not in {"pending", "in_progress", "completed", "cancelled"}:
            status = "pending"
        return {
            "id": item_id,
            "content": content,
            "status": status,
        }

    @staticmethod
    def _dedupe_todos(items: list[dict[str, str]]) -> list[dict[str, str]]:
        last_index_by_id = {item["id"]: index for index, item in enumerate(items)}
        return [items[index] for index in sorted(last_index_by_id.values())]

    @staticmethod
    def _normalize_delegate_toolsets(value: Any) -> list[str]:
        if not isinstance(value, list):
            return ["skills", "terminal", "file", "web"]
        tool_name_to_toolset = {
            "http_get": "web",
            "read_file": "file",
            "write_file": "file",
            "patch": "file",
            "search_files": "file",
            "terminal.run": "terminal",
        }
        normalized: list[str] = []
        for item in value:
            name = str(item or "").strip()
            if not name or name in {"delegate", "delegation", "delegate_task"} or name in normalized:
                continue
            # 모델이 toolset 이름 대신 실제 도구 이름을 넣어도 worker에는 올바른 toolset 계약을 넘긴다.
            name = tool_name_to_toolset.get(name, name)
            if name in normalized:
                continue
            normalized.append(name)
        return normalized or ["skills", "terminal", "file", "web"]

    def _resolve_session_agent_profile(
        self,
        *,
        session_id: str,
        owner_key: str,
        assignee_agent_id: str | None,
        assignee_hint: str | None,
        required_skill_names: list[str] | None = None,
    ) -> dict[str, Any] | None:
        if self.agent_repository is None:
            return None
        if assignee_agent_id:
            profile = self.agent_repository.get_session_agent(profile_id=assignee_agent_id, owner_key=owner_key)
            if profile is not None and str(profile.get("session_id") or "") == session_id:
                if str(profile.get("agent_type") or "") == "user_subagent":
                    return profile
            return None

        profiles = list(self.agent_repository.list_session_agents(session_id=session_id, owner_key=owner_key))
        if not profiles:
            return None
        if assignee_hint:
            normalized_hint = self._normalize_match_text(assignee_hint)
            for profile in profiles:
                if self._profile_matches_hint(profile, normalized_hint):
                    return profile
        if required_skill_names:
            for profile in profiles:
                if not self._missing_profile_skills(profile, required_skill_names):
                    return profile
        return profiles[0]

    def _required_session_agent_skill_names(
        self,
        *,
        args: dict[str, Any],
        context: dict[str, Any],
        text_parts: list[str],
    ) -> list[str]:
        explicit = self._string_list(args.get("requiredSkillNames") or args.get("required_skill_names"))
        required: list[str] = list(explicit)

        parent_skill_names = self._string_list(
            context.get("enabledSkillNames")
            or context.get("enabled_skill_names")
            or context.get("skillNames")
            or context.get("skill_names")
        )
        if not parent_skill_names:
            target_profile = context.get("targetAgentProfile") or context.get("target_agent_profile")
            config = target_profile.get("configSnapshot") if isinstance(target_profile, dict) else {}
            if isinstance(config, dict):
                parent_skill_names = self._string_list(config.get("skills"))
        if not parent_skill_names:
            return required

        for skill_name in parent_skill_names:
            if self._has_required_parent_skill_reference(skill_name, text_parts):
                self._append_unique(required, skill_name)
        return required

    def _has_required_parent_skill_reference(self, skill_name: str, text_parts: list[str]) -> bool:
        needle = self._normalize_match_text(skill_name)
        if not needle:
            return False
        for text_part in text_parts:
            haystack = self._normalize_match_text(text_part)
            start = 0
            while True:
                index = haystack.find(needle, start)
                if index < 0:
                    break
                if not self._skill_reference_is_excluded(haystack, index, len(needle)):
                    return True
                start = index + len(needle)
        return False

    @staticmethod
    def _skill_reference_is_excluded(haystack: str, index: int, length: int) -> bool:
        window_start = max(0, index - 80)
        window_end = min(len(haystack), index + length + 80)
        window = haystack[window_start:window_end]
        exclusion_markers = (
            "수행하지",
            "하지마",
            "하지않",
            "맡기지",
            "요구하지",
            "필요없",
            "제외",
            "팀장이직접",
            "직접처리",
            "donot",
            "doesnot",
            "mustnot",
            "shouldnot",
            "notrequire",
            "notrequired",
            "exclude",
            "without",
        )
        return any(marker in window for marker in exclusion_markers)

    def _missing_profile_skills(self, profile: dict[str, Any], required_skill_names: list[str] | None) -> list[str]:
        if not required_skill_names:
            return []
        profile_skill_names = {
            self._normalize_match_text(skill_name)
            for skill_name in self._profile_skill_names(profile)
        }
        return [
            skill_name
            for skill_name in required_skill_names
            if self._normalize_match_text(skill_name) not in profile_skill_names
        ]

    def _profile_skill_names(self, profile: dict[str, Any]) -> list[str]:
        config = dict(profile.get("config_snapshot") or {})
        return self._string_list(config.get("skills") or profile.get("skills"))

    @classmethod
    def _profile_matches_hint(cls, profile: dict[str, Any], normalized_hint: str) -> bool:
        config = dict(profile.get("config_snapshot") or {})
        values = [
            profile.get("profile_id"),
            profile.get("profile_key"),
            profile.get("template_key"),
            config.get("name"),
            config.get("displayName"),
            config.get("role"),
            config.get("title"),
            config.get("description"),
        ]
        for skill in list(config.get("skills") or []):
            values.append(skill)
        haystack = cls._normalize_match_text(" ".join(str(value or "") for value in values))
        return bool(normalized_hint and normalized_hint in haystack)

    @staticmethod
    def _normalize_match_text(value: Any) -> str:
        return re.sub(r"\s+", "", str(value or "").strip().lower())

    @staticmethod
    def _append_unique(values: list[str], item: str) -> None:
        if item not in values:
            values.append(item)

    @staticmethod
    def _work_tool_payload(work) -> dict[str, Any]:
        return {
            "workId": work.work_id,
            "identifier": work.identifier,
            "sessionId": work.session_id,
            "title": work.title,
            "description": work.description,
            "status": work.status,
            "assigneeAgentId": work.assignee_agent_id,
            "parentId": work.parent_id,
            "executionInstruction": work.execution_instruction,
        }

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        try:
            return int(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_positive_int(value: Any) -> int | None:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        if not isinstance(value, str):
            return None
        stripped = value.strip()
        return stripped or None

    @staticmethod
    def _todo_summary(items: list[dict[str, str]]) -> dict[str, int]:
        return {
            "total": len(items),
            "pending": sum(1 for item in items if item["status"] == "pending"),
            "in_progress": sum(1 for item in items if item["status"] == "in_progress"),
            "completed": sum(1 for item in items if item["status"] == "completed"),
            "cancelled": sum(1 for item in items if item["status"] == "cancelled"),
        }

    @staticmethod
    def _tool_error(*, code: str, message: str, tool_name: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
        error = {
            "code": code,
            "message": message,
            "tool_name": tool_name,
        }
        if details:
            error.update(details)
        payload = {
            "error": error
        }
        return {
            "ok": False,
            **payload,
            "content": json.dumps(payload, ensure_ascii=False),
        }

    @classmethod
    def _validate_args(cls, schema: dict[str, Any], args: dict[str, Any]) -> str | None:
        parameters = schema.get("parameters") if isinstance(schema, dict) else {}
        if not isinstance(parameters, dict):
            return None
        if parameters.get("type") == "object" and not isinstance(args, dict):
            return "tool arguments must be an object"

        properties = parameters.get("properties") if isinstance(parameters.get("properties"), dict) else {}
        required = parameters.get("required") if isinstance(parameters.get("required"), list) else []
        for key in required:
            if key not in args:
                return f"missing required argument: {key}"

        for key, value in args.items():
            property_schema = properties.get(key)
            if not isinstance(property_schema, dict):
                continue
            error = cls._validate_value(value, property_schema, path=key)
            if error:
                return error
        return None

    @classmethod
    def _validate_value(cls, value: Any, schema: dict[str, Any], *, path: str) -> str | None:
        expected_type = schema.get("type")
        if isinstance(expected_type, list):
            errors = [cls._validate_value(value, {**schema, "type": item}, path=path) for item in expected_type]
            return None if any(error is None for error in errors) else errors[0]

        if expected_type == "array":
            if not isinstance(value, list):
                return f"{path} must be an array"
            item_schema = schema.get("items")
            if isinstance(item_schema, dict):
                for index, item in enumerate(value):
                    error = cls._validate_value(item, item_schema, path=f"{path}.{index}")
                    if error:
                        return error
            return None

        if expected_type == "object":
            if not isinstance(value, dict):
                return f"{path} must be an object"
            properties = schema.get("properties") if isinstance(schema.get("properties"), dict) else {}
            required = schema.get("required") if isinstance(schema.get("required"), list) else []
            for key in required:
                if key not in value:
                    return f"missing required argument: {path}.{key}"
            for key, nested_value in value.items():
                nested_schema = properties.get(key)
                if isinstance(nested_schema, dict):
                    error = cls._validate_value(nested_value, nested_schema, path=f"{path}.{key}")
                    if error:
                        return error
            return None

        if expected_type == "string" and not isinstance(value, str):
            return f"{path} must be a string"
        if expected_type == "boolean" and not isinstance(value, bool):
            return f"{path} must be a boolean"
        if expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
            return f"{path} must be an integer"
        if expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
            return f"{path} must be a number"

        allowed_values = schema.get("enum")
        if isinstance(allowed_values, list) and value not in allowed_values:
            return f"{path} must be one of: {', '.join(str(item) for item in allowed_values)}"
        return None


def _default_entry_file(files: dict[str, Any]) -> str:
    for candidate in ("/src/App.tsx", "/src/App.jsx", "/src/main.tsx", "/src/main.jsx", "/index.html"):
        if candidate in files:
            return candidate
    return next(iter(files))
