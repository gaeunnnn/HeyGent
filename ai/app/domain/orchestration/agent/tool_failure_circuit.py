from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolFailureRecord:
    tool_name: str
    args_hash: str
    normalized_args: str
    failure_kind: str
    status_code: int | None
    error_code: str | None
    retry_after_ms: int | None
    cooldown_until: float | None
    result_hash: str
    unknown_tool_name: str | None
    count: int = 0
    blocked_count: int = 0
    first_seen_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)

    @property
    def signature(self) -> str:
        status = self.status_code if self.status_code is not None else self.error_code or "none"
        return f"{self.tool_name}:{self.args_hash}:{self.failure_kind}:{status}"


@dataclass(frozen=True)
class ToolFailure:
    failure_kind: str
    status_code: int | None
    error_code: str | None
    retry_after_ms: int | None
    cooldown_until: float | None
    result_hash: str
    unknown_tool_name: str | None
    message: str


@dataclass(frozen=True)
class CircuitDecision:
    action: str
    record: ToolFailureRecord | None = None
    should_abort: bool = False


@dataclass(frozen=True)
class ProviderFailure:
    failure_kind: str
    status_code: int | None
    error_code: str | None
    retry_after_ms: int | None
    cooldown_until: float | None
    message: str
    retryable: bool


class RunLocalToolFailureCircuit:
    """한 agent.loop 실행 안에서 반복되는 도구 실패를 실행 전에 차단한다."""

    _THRESHOLDS = {
        "rate_limited": 1,
        "tool_unavailable": 1,
        "unknown_tool": 1,
        "auth_missing": 1,
        "invalid_args": 1,
        "timeout": 2,
        "execution_error": 2,
    }

    def __init__(self) -> None:
        self._records: dict[str, ToolFailureRecord] = {}
        self._unavailable_by_tool: dict[str, ToolFailureRecord] = {}

    def pre_call_decision(self, *, tool_name: str, args: dict[str, Any]) -> CircuitDecision:
        args_hash = canonical_args_hash(args)
        for record in self._candidate_records(tool_name=tool_name, args_hash=args_hash):
            threshold = self._threshold(record.failure_kind)
            if record.count >= threshold:
                return CircuitDecision(
                    action="block_with_synthetic_result",
                    record=record,
                    should_abort=record.blocked_count >= 1,
                )
        return CircuitDecision(action="allow")

    def record_result(self, *, tool_name: str, args: dict[str, Any], result: Any) -> ToolFailureRecord | None:
        failure = classify_tool_failure(result)
        if failure is None:
            return None

        normalized_args = canonical_tool_args(args)
        record = ToolFailureRecord(
            tool_name=tool_name,
            args_hash=_digest(normalized_args),
            normalized_args=normalized_args,
            failure_kind=failure.failure_kind,
            status_code=failure.status_code,
            error_code=failure.error_code,
            retry_after_ms=failure.retry_after_ms,
            cooldown_until=failure.cooldown_until,
            result_hash=failure.result_hash,
            unknown_tool_name=failure.unknown_tool_name,
        )
        signature = record.signature
        existing = self._records.get(signature)
        if existing is None:
            record.count = 1
            self._records[signature] = record
            existing = record
        else:
            existing.count += 1
            existing.last_seen_at = time.time()
            existing.retry_after_ms = failure.retry_after_ms
            existing.cooldown_until = failure.cooldown_until
            existing.result_hash = failure.result_hash

        if existing.failure_kind in {"tool_unavailable", "unknown_tool"}:
            self._unavailable_by_tool[tool_name] = existing
        return existing

    def record_block(self, record: ToolFailureRecord) -> None:
        record.blocked_count += 1
        record.last_seen_at = time.time()

    def build_blocked_result(self, *, record: ToolFailureRecord) -> dict[str, Any]:
        threshold = self._threshold(record.failure_kind)
        retryable = record.failure_kind in {"timeout", "execution_error"} and record.cooldown_until is None
        error = {
            "code": "tool_circuit_open",
            "type": record.failure_kind,
            "message": (
                f"Repeated {record.failure_kind} failure for {record.tool_name} "
                "with the same run-local failure signature was blocked."
            ),
            "tool_name": record.tool_name,
            "signature": record.signature,
            "attempts": record.count,
            "threshold": threshold,
            "retryable": retryable,
            "previous_error_code": record.error_code or record.failure_kind,
        }
        if record.status_code is not None:
            error["status_code"] = record.status_code
        if record.retry_after_ms is not None:
            error["retry_after_ms"] = record.retry_after_ms
        if record.cooldown_until is not None:
            error["cooldown_until"] = record.cooldown_until

        payload = {"error": error}
        return {
            "ok": False,
            "error": error,
            "circuit_breaker": {
                "scope": "run",
                "failure_type": record.failure_kind,
                "blocked": True,
            },
            "content": json.dumps(payload, ensure_ascii=False),
        }

    def _candidate_records(self, *, tool_name: str, args_hash: str) -> list[ToolFailureRecord]:
        candidates = [
            record
            for record in self._records.values()
            if record.tool_name == tool_name and record.args_hash == args_hash
        ]
        by_tool = self._unavailable_by_tool.get(tool_name)
        if by_tool is not None and by_tool not in candidates:
            candidates.append(by_tool)
        return candidates

    @classmethod
    def _threshold(cls, failure_kind: str) -> int:
        return cls._THRESHOLDS.get(failure_kind, 2)


def classify_tool_failure(result: Any) -> ToolFailure | None:
    if not isinstance(result, dict):
        return None

    raw_error = result.get("error")
    has_error = raw_error is not None
    ok_false = result.get("ok") is False
    legacy_error_only = has_error and result.get("ok") is not True
    if not (ok_false or legacy_error_only):
        return None

    error = raw_error if isinstance(raw_error, dict) else {}
    message = _error_message(raw_error, result)
    status_code = _int_value(
        error.get("status_code")
        or error.get("status")
        or error.get("http_status")
        or result.get("status_code")
        or result.get("status")
    )
    error_code = _text(error.get("code") or result.get("code"))
    retry_after_ms = _retry_after_ms(error, result)
    cooldown_until = time.time() + retry_after_ms / 1000 if retry_after_ms is not None else None
    failure_kind = _failure_kind(code=error_code, status_code=status_code, message=message)
    return ToolFailure(
        failure_kind=failure_kind,
        status_code=status_code,
        error_code=error_code,
        retry_after_ms=retry_after_ms,
        cooldown_until=cooldown_until,
        result_hash=_digest(_stable_json(result)),
        unknown_tool_name=_text(error.get("tool_name") or result.get("tool_name")),
        message=message,
    )


def classify_provider_failure(error: BaseException) -> ProviderFailure | None:
    status_code = _provider_status_code(error)
    message = f"{type(error).__name__}: {error}"
    lowered = message.lower()
    if status_code is None and not any(token in lowered for token in ("rate limit", "too many requests", "timeout", "timed out")):
        return None

    retry_after_ms = _provider_retry_after_ms(error)
    cooldown_until = time.time() + retry_after_ms / 1000 if retry_after_ms is not None else None
    error_code = _provider_error_code(error)
    failure_kind = _failure_kind(code=error_code, status_code=status_code, message=message)
    return ProviderFailure(
        failure_kind=failure_kind,
        status_code=status_code,
        error_code=error_code,
        retry_after_ms=retry_after_ms,
        cooldown_until=cooldown_until,
        message=message,
        retryable=failure_kind in {"rate_limited", "timeout", "execution_error"},
    )


def build_provider_failure_payload(failure: ProviderFailure) -> dict[str, Any]:
    code = "provider_rate_limited" if failure.failure_kind == "rate_limited" else "provider_call_failed"
    error = {
        "code": code,
        "type": failure.failure_kind,
        "message": failure.message,
        "retryable": failure.retryable,
    }
    if failure.status_code is not None:
        error["status_code"] = failure.status_code
    if failure.error_code is not None:
        error["provider_error_code"] = failure.error_code
    if failure.retry_after_ms is not None:
        error["retry_after_ms"] = failure.retry_after_ms
    if failure.cooldown_until is not None:
        error["cooldown_until"] = failure.cooldown_until
    return error


def canonical_tool_args(args: dict[str, Any]) -> str:
    return _stable_json(args)


def canonical_args_hash(args: dict[str, Any]) -> str:
    return _digest(canonical_tool_args(args))


def _failure_kind(*, code: str | None, status_code: int | None, message: str) -> str:
    lowered_code = (code or "").lower()
    lowered_message = (message or "").lower()
    rate_limit_tokens = ("429", "rate limit", "rate_limit", "too many requests", "resource_exhausted")
    if (
        status_code == 429
        or any(token in lowered_code for token in rate_limit_tokens)
        or any(token in lowered_message for token in rate_limit_tokens)
    ):
        return "rate_limited"
    if lowered_code in {"tool_unavailable", "unknown_tool"} or "unknown or disabled runtime tool" in lowered_message:
        return "tool_unavailable"
    if lowered_code == "invalid_tool_arguments" or "missing required argument" in lowered_message:
        return "invalid_args"
    if lowered_code in {"owner_required", "auth_missing"} or any(token in lowered_message for token in ("api key", "credential", "unauthorized", "forbidden", "auth")):
        return "auth_missing"
    if "timeout" in lowered_code or "timeout" in lowered_message or "timed out" in lowered_message:
        return "timeout"
    return "execution_error"


def _error_message(raw_error: Any, result: dict[str, Any]) -> str:
    if isinstance(raw_error, dict):
        return str(raw_error.get("message") or raw_error.get("detail") or raw_error)
    if raw_error is not None:
        return str(raw_error)
    return str(result)


def _retry_after_ms(error: dict[str, Any], result: dict[str, Any]) -> int | None:
    value = error.get("retry_after_ms") or result.get("retry_after_ms")
    if isinstance(value, int) and value > 0:
        return value
    seconds = _int_value(error.get("retry_after") or result.get("retry_after"))
    if seconds is not None and seconds > 0:
        return seconds * 1000
    return None


def _provider_status_code(error: BaseException) -> int | None:
    status = getattr(error, "status_code", None)
    if status is None:
        response = getattr(error, "response", None)
        status = getattr(response, "status_code", None)
    return _int_value(status)


def _provider_retry_after_ms(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    value = None
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")
    except AttributeError:
        return None
    seconds = _int_value(value)
    if seconds is None or seconds <= 0:
        return None
    return seconds * 1000


def _provider_error_code(error: BaseException) -> str | None:
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        raw = body.get("error")
        if isinstance(raw, dict):
            return _text(raw.get("code") or raw.get("type"))
    return None


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _int_value(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(float(value.strip()))
        except ValueError:
            return None
    return None


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
