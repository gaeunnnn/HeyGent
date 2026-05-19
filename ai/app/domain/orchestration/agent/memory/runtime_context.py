from __future__ import annotations

from typing import Any


DEFAULT_MEMORY_PROVIDER_NAME = "openai_api_key"


def resolve_memory_provider_name(provider_name: Any = None, model: Any = None) -> str:
    text = _text(provider_name)
    if text:
        if text == "openai":
            return "openai_api_key"
        if text == "gemini":
            return "gemini_api_key"
        return text
    model_text = (_text(model) or "").lower()
    if model_text.startswith("gemini-"):
        return "gemini_api_key"
    return DEFAULT_MEMORY_PROVIDER_NAME


def build_memory_provider_runtime_context(
    *,
    user_id: Any,
    provider_name: Any = None,
    task_run_id: Any = None,
    step_run_id: Any = None,
    session_id: Any = None,
    model: Any = None,
) -> dict[str, str] | None:
    normalized_user_id = _text(user_id)
    if not normalized_user_id:
        return None
    context: dict[str, str] = {
        "user_id": normalized_user_id,
        "provider_name": resolve_memory_provider_name(provider_name, model),
    }
    _put_if_present(context, "task_run_id", _text(task_run_id))
    _put_if_present(context, "step_run_id", _text(step_run_id))
    _put_if_present(context, "session_id", _text(session_id))
    _put_if_present(context, "model", _text(model))
    return context


def memory_provider_runtime_context_from_task_input(
    task_input: dict[str, Any] | None,
    *,
    user_id: Any,
    task_run_id: Any = None,
    step_run_id: Any = None,
    session_id: Any = None,
    model: Any = None,
) -> dict[str, str] | None:
    payload = dict(task_input or {})
    settings_snapshot = payload.get("settings_snapshot")
    if not isinstance(settings_snapshot, dict):
        settings_snapshot = {}
    return build_memory_provider_runtime_context(
        user_id=user_id,
        provider_name=(
            payload.get("provider_name")
            or payload.get("providerName")
            or settings_snapshot.get("provider_name")
            or settings_snapshot.get("providerName")
        ),
        task_run_id=task_run_id or payload.get("task_run_id") or payload.get("taskRunId"),
        step_run_id=step_run_id or payload.get("step_run_id") or payload.get("stepRunId"),
        session_id=session_id or payload.get("session_id") or payload.get("sessionId"),
        model=model or payload.get("model") or settings_snapshot.get("model"),
    )


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _put_if_present(target: dict[str, str], key: str, value: str | None) -> None:
    if value:
        target[key] = value
