from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx


logger = logging.getLogger(__name__)

DEFAULT_MEMORY_PROVIDER_RETRY_DELAYS = (0.5, 1.0)
RETRYABLE_MEMORY_PROVIDER_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}


async def respond_provider_with_retry(
    provider: Any,
    *,
    retry_delays: tuple[float, ...] = DEFAULT_MEMORY_PROVIDER_RETRY_DELAYS,
    **kwargs: Any,
) -> Any:
    attempts = len(retry_delays) + 1
    selected_model = _selected_model(kwargs)
    provider_name = _provider_name(provider)
    for index in range(attempts):
        try:
            response = await _respond_provider_once(provider, **kwargs)
            if index > 0:
                logger.info(
                    "memory provider call succeeded after retry",
                    extra={
                        "memory_provider_name": provider_name,
                        "memory_selected_model": selected_model,
                        "memory_retry_attempts": index + 1,
                    },
                )
            return response
        except Exception as exc:
            if index >= len(retry_delays) or not is_retryable_memory_provider_error(exc):
                _attach_retry_metadata(
                    exc,
                    selected_model=selected_model,
                    provider_name=provider_name,
                    retry_attempts=index + 1,
                    max_attempts=attempts,
                )
                logger.warning(
                    "memory provider call failed",
                    extra={
                        "memory_provider_name": provider_name,
                        "memory_selected_model": selected_model,
                        "memory_retry_attempts": index + 1,
                        "memory_max_attempts": attempts,
                        **memory_provider_error_details(exc),
                    },
                    exc_info=True,
                )
                raise
            _attach_retry_metadata(
                exc,
                selected_model=selected_model,
                provider_name=provider_name,
                retry_attempts=index + 1,
                max_attempts=attempts,
            )
            logger.info(
                "memory provider call retrying after retryable error",
                extra={
                    "memory_provider_name": provider_name,
                    "memory_selected_model": selected_model,
                    "memory_retry_attempts": index + 1,
                    "memory_max_attempts": attempts,
                    **memory_provider_error_details(exc),
                },
            )
            await asyncio.sleep(retry_delays[index])
    raise RuntimeError("memory provider retry loop exhausted")


def memory_provider_error_details(exc: BaseException) -> dict[str, Any]:
    details: dict[str, Any] = {"error_type": type(exc).__name__}
    selected_model = getattr(exc, "memory_selected_model", None)
    if isinstance(selected_model, str) and selected_model.strip():
        details["selected_model"] = selected_model.strip()
    provider_name = getattr(exc, "memory_provider_name", None)
    if isinstance(provider_name, str) and provider_name.strip():
        details["provider_name"] = provider_name.strip()
    retry_attempts = getattr(exc, "memory_retry_attempts", None)
    if isinstance(retry_attempts, int):
        details["retry_attempts"] = retry_attempts
    max_attempts = getattr(exc, "memory_max_attempts", None)
    if isinstance(max_attempts, int):
        details["max_attempts"] = max_attempts
    if isinstance(exc, httpx.HTTPStatusError):
        details["provider_status_code"] = exc.response.status_code
        details["retryable"] = is_retryable_memory_provider_error(exc)
        response_text = str(getattr(exc.response, "text", "") or "").strip()
        if response_text:
            details["provider_error_message"] = response_text[:500]
    return details


def is_retryable_memory_provider_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in RETRYABLE_MEMORY_PROVIDER_STATUSES
    return isinstance(exc, (httpx.TimeoutException, httpx.TransportError))


async def _respond_provider_once(provider: Any, **kwargs: Any) -> Any:
    respond_async = getattr(provider, "respond_async", None)
    if callable(respond_async):
        return await respond_async(**kwargs)
    return await asyncio.to_thread(provider.respond, **kwargs)


def _attach_retry_metadata(
    exc: BaseException,
    *,
    selected_model: str | None,
    provider_name: str | None,
    retry_attempts: int,
    max_attempts: int,
) -> None:
    setattr(exc, "memory_retry_attempts", retry_attempts)
    setattr(exc, "memory_max_attempts", max_attempts)
    if selected_model:
        setattr(exc, "memory_selected_model", selected_model)
    if provider_name:
        setattr(exc, "memory_provider_name", provider_name)


def _selected_model(kwargs: dict[str, Any]) -> str | None:
    model = kwargs.get("model")
    return str(model or "").strip() or None


def _provider_name(provider: Any) -> str | None:
    name = getattr(provider, "name", None) or getattr(provider, "provider_name", None)
    return str(name or "").strip() or provider.__class__.__name__
